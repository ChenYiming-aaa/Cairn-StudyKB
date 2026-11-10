"""组件下载中心的后端（T8.3）：下载 → 校验 → 解压 → 就位。

**为什么单独一个模块**：`components.py` 只管"装没装、怎么跑、占多少盘"，一装上就完事；
本模块管的是"装的过程"——长任务、可中断、可续传、会失败。两者读写方向相反
（本模块写安装态、`components.status()` 读），所以状态字典放在 `components.py` 里。

**五条硬约束**（每条都踩过或差点踩）：

1. **`.part` 不能放进 `components/<id>/`**：那个目录存在就等于"已安装"，
   下载到 30% 时界面会显示"已安装"、`resolve()` 还会去握手一个半个 exe。
   所以中间文件放在 `components/.parts/`，解压在 `components/.tmp-<uuid>/`。
2. **解压到临时目录再整体改名**：中途失败留下的半个目录既不能跑也删不干净，
   用户看到"已安装"却用不了 —— 这比"安装失败"糟得多。
3. **卸载/重装前先 `stop()`**：Windows 下 exe 被占用会删不掉（`app.asar` 已被锁过一次）。
4. **`Range` 只有服务端认才算数**：GitHub Releases 支持，但镜像/代理不一定；
   所以带了 `Range` 却收到 `200` 时必须**丢掉已有字节从头写**，否则文件会错位
   （sha256 一定不过，但用户要白等一遍）。
5. **进度是"尽力而为"**：`tasks.update_progress` 写库失败只记 warning，不中断下载；
   内存里的 `_install[...]` 才是前端的权威来源（磁盘上 262 MB 的 IO 不该被 SQLite 卡住）。
"""
from __future__ import annotations

import errno
import hashlib
import logging
import os
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path

import httpx

from app.services import components, prefs, tasks as task_queue

log = logging.getLogger(__name__)

TASK_TYPE = "component_install"
CHUNK = 256 * 1024                     # 256 KB：进度条 1% ≈ 2.6 MB，够细且不刷爆回调
PROGRESS_EVERY = 0.4                   # 秒；进度写库/内存的最小间隔
TIMEOUT = httpx.Timeout(connect=20.0, read=120.0, write=120.0, pool=20.0)
UA = "Cairn/0.2 (+https://github.com/ChenYiming-aaa/Cairn-StudyKB)"

# 取消信号：每个组件一个 Event，`cancel()` 置位，下载循环里轮询
_cancel: dict[str, threading.Event] = {}
_cancel_lock = threading.Lock()


class InstallError(Exception):
    """带错误码的业务异常：`tasks.submit` 会把它拆成 error_code + error_msg 落库。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Cancelled(Exception):
    """用户点了「取消」。不算失败，任务按 cancelled 收尾。"""


# ── 目录 ────────────────────────────────────────────────
def parts_dir() -> Path:
    return components.root() / ".parts"


def part_path(cid: str) -> Path:
    return parts_dir() / f"{cid}.zip.part"


def _clear_part(cid: str) -> None:
    try:
        part_path(cid).unlink(missing_ok=True)
    except OSError:
        pass


# ── 地址 ────────────────────────────────────────────────
def direct_url(entry: dict) -> str:
    """`repo + release_tag + asset` 拼 GitHub Releases 直链（换仓库/换 tag 只改清单一处）。

    `CAIRN_COMPONENT_BASE_URL` 是**只给验收用的**整体覆盖：verify_m8 起一个本地
    HTTP 服务器当下载源，才能真测断点续传与坏包，而不是去 GitHub 拉 262 MB。
    """
    override = os.environ.get("CAIRN_COMPONENT_BASE_URL", "").strip().rstrip("/")
    if override:
        return f"{override}/{entry['asset']}"
    man = components.manifest()
    repo = man.get("repo") or "ChenYiming-aaa/Cairn-StudyKB"
    tag = man.get("release_tag") or "components-v1"
    return f"https://github.com/{repo}/releases/download/{tag}/{entry['asset']}"


def mirror() -> str:
    """用户配的镜像前缀。**默认为空**：不偷偷把用户的流量导去第三方（§3.3）。"""
    conf = (prefs.load().get("components") or {})
    return str(conf.get("mirror") or "").strip().rstrip("/")


def resolved_url(entry: dict) -> str:
    base = direct_url(entry)
    prefix = mirror()
    return f"{prefix}/{base}" if prefix else base


# ── 入口 ────────────────────────────────────────────────
def start(cid: str) -> str:
    """校验前置条件 → 登记任务 → 返回 task_id（路由层立即 202 给前端）。"""
    if cid not in components.IDS:
        raise InstallError("COMPONENT_UNKNOWN", f"没有这个组件：{cid}")
    entry = components.entries().get(cid)
    if not entry:
        raise InstallError("COMPONENT_UNKNOWN", f"清单里没有 {cid}，无法下载")

    if components.install_running(cid):
        raise InstallError("COMPONENT_BUSY", f"{components.LABELS.get(cid, cid)}正在安装，等它结束")

    size = int(entry.get("size") or 0)
    _ensure_space(cid, size)

    with _cancel_lock:
        _cancel[cid] = threading.Event()

    components.set_install(cid, status="running", phase="queued", got=0, total=size,
                           pct=0, error_code="", error_msg="", task_id="",
                           started_at=time.time())
    task_id = task_queue.submit(TASK_TYPE, run, {"id": cid}, pass_task_id=True)
    components.set_install(cid, task_id=task_id)
    log.info("组件 %s 开始安装（task=%s，%s）", cid, task_id, resolved_url(entry))
    return task_id


def cancel(cid: str) -> bool:
    """置取消位。下载循环 256 KB 一次检查，最迟一个 chunk 就停。"""
    with _cancel_lock:
        ev = _cancel.get(cid)
    if not ev:
        return False
    ev.set()
    components.set_install(cid, phase="cancelling")
    return True


def _event(cid: str) -> threading.Event:
    with _cancel_lock:
        ev = _cancel.get(cid)
        if ev is None:
            ev = threading.Event()
            _cancel[cid] = ev
        return ev


def _check_cancel(cid: str) -> None:
    if _event(cid).is_set():
        raise Cancelled()


# ── 主流程（在任务线程里跑） ────────────────────────────
def run(payload: dict, task_id: str | None = None) -> dict:
    cid = str((payload or {}).get("id") or "")
    entry = components.entries().get(cid)
    if not entry:
        raise InstallError("COMPONENT_UNKNOWN", f"清单里没有 {cid}，无法下载")

    # 不在这里 clear()：start() 每次都给一个新 Event，而 run() 可能比用户的「取消」
    # 晚几毫秒才被线程池取到 —— 那时 clear 会把刚点下的取消擦掉。
    components.set_install(cid, status="running", phase="download", got=0,
                           total=int(entry.get("size") or 0), pct=0,
                           error_code="", error_msg="", task_id=task_id or "",
                           started_at=time.time())
    tmp: Path | None = None
    try:
        url = resolved_url(entry)
        zip_path = _download(cid, url, entry, task_id)
        _check_cancel(cid)

        components.set_install(cid, phase="verify", pct=99)
        _verify(zip_path, entry)
        _check_cancel(cid)

        components.set_install(cid, phase="extract", pct=100)
        tmp = _extract(cid, zip_path)
        _check_cancel(cid)

        _place(cid, tmp)
        tmp = None
        _clear_part(cid)
        components.reset_cache()          # 装完立刻生效：_hello_at 有 30 s 缓存（S-7 的坑）
        size = components.disk_bytes(cid)
        components.set_install(cid, status="done", phase="done", pct=100,
                               error_code="", error_msg="",
                               finished_at=time.time(), bytes=size)
        log.info("组件 %s 安装完成，占 %.1f MB", cid, size / 1e6)
        if task_id:
            task_queue.update_progress(task_id, 100, stage="已安装")
        return {"id": cid, "bytes": size, "url": url}

    except Cancelled:
        components.set_install(cid, status="cancelled", phase="cancelled",
                               error_code="COMPONENT_CANCELLED",
                               error_msg="已取消，下载了一半的文件已删除",
                               finished_at=time.time())
        _clear_part(cid)
        log.info("组件 %s 安装被取消", cid)
        # 正常返回而不是抛：取消是用户意图，不是故障。落成 failed 会让任务中心
        # 出现一条红条目，下次点「重试」还会把用户刚取消的下载又拉起来。
        return {"id": cid, "cancelled": True}

    except InstallError as exc:
        components.set_install(cid, status="failed", phase="failed",
                               error_code=exc.code, error_msg=exc.message,
                               finished_at=time.time())
        # 失败不留残骸：.part 留着没用（sha 不对就是不对），临时目录清掉
        if exc.code != "COMPONENT_DOWNLOAD_FAILED":
            _clear_part(cid)
        raise

    except Exception as exc:  # noqa: BLE001 - 未知异常也要让界面看到人话
        code = _exc_code(exc)
        message = _exc_message(exc)
        components.set_install(cid, status="failed", phase="failed",
                               error_code=code, error_msg=message,
                               finished_at=time.time())
        log.error("组件 %s 安装失败：%s / %s", cid, type(exc).__name__, str(exc)[:200])
        raise InstallError(code, message) from exc

    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
        with _cancel_lock:
            _cancel.pop(cid, None)


# ── 下载 ────────────────────────────────────────────────
def _download(cid: str, url: str, entry: dict, task_id: str | None) -> Path:
    parts_dir().mkdir(parents=True, exist_ok=True)
    part = part_path(cid)
    got = part.stat().st_size if part.exists() else 0
    total = int(entry.get("size") or 0)

    headers = {"User-Agent": UA}
    if got:
        headers["Range"] = f"bytes={got}-"
        log.info("组件 %s 断点续传：已有 %.1f MB", cid, got / 1e6)

    try:
        with httpx.stream("GET", url, headers=headers, follow_redirects=True,
                          timeout=TIMEOUT) as resp:
            if resp.status_code >= 400:
                raise InstallError(
                    "COMPONENT_DOWNLOAD_FAILED",
                    f"下载失败（HTTP {resp.status_code}）。换网络重试，或在设置里配镜像",
                )
            if got and resp.status_code == 200:
                # 服务端不认 Range：从头写，别把新数据接在旧字节后面
                log.warning("组件 %s 的下载源不支持断点续传，从头开始", cid)
                got = 0
                part.unlink(missing_ok=True)
            length = int(resp.headers.get("content-length") or 0)
            if not total and length:
                total = got + length
            if total:
                components.set_install(cid, total=total)

            last = 0.0
            last_pct = -1
            with part.open("ab" if got else "wb") as fp:
                for chunk in resp.iter_bytes(CHUNK):
                    _check_cancel(cid)
                    fp.write(chunk)
                    got += len(chunk)
                    now = time.monotonic()
                    pct = int(got * 100 / total) if total else 0
                    if now - last >= PROGRESS_EVERY or pct != last_pct:
                        last, last_pct = now, pct
                        components.set_install(cid, got=got, pct=pct)
                        if task_id:
                            # 0–95 给下载，留 5 给校验与解压，别让进度条顶在 100 不动
                            task_queue.update_progress(
                                task_id, min(95, pct), stage=f"下载中 {pct}%")
    except httpx.HTTPError as exc:
        raise InstallError(
            "COMPONENT_DOWNLOAD_FAILED",
            f"下载中断（{type(exc).__name__}）。再点一次安装会从断点继续",
        ) from exc
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise InstallError("COMPONENT_DISK_FULL", "磁盘空间不够，下载中断") from exc
        raise InstallError("COMPONENT_DOWNLOAD_FAILED",
                           f"写文件失败（{type(exc).__name__}）。确认数据目录可写") from exc

    if total and got < total:
        raise InstallError("COMPONENT_DOWNLOAD_FAILED",
                           f"下载不完整（{got}/{total} 字节）。再点一次会从断点继续")
    return part


def _verify(zip_path: Path, entry: dict) -> None:
    want = str(entry.get("sha256") or "").strip().lower()
    if not want:
        raise InstallError("COMPONENT_PACKAGE_INVALID", "清单里没写 sha256，无法确认包是否完整")
    digest = hashlib.sha256()
    try:
        with zip_path.open("rb") as fp:
            for block in iter(lambda: fp.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise InstallError("COMPONENT_PACKAGE_INVALID",
                           f"读不了下载的文件（{type(exc).__name__}）") from exc
    got = digest.hexdigest()
    if got != want:
        raise InstallError(
            "COMPONENT_HASH_MISMATCH",
            "下载的文件校验不通过（可能被网络劫持或镜像改过）。已删除，请重试或换下载源",
        )


# ── 解压 ────────────────────────────────────────────────
def _extract(cid: str, zip_path: Path) -> Path:
    root = components.root()
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f".tmp-{cid}-{uuid.uuid4().hex[:8]}"
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                _guard(name)
            zf.extractall(tmp)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise InstallError("COMPONENT_PACKAGE_INVALID",
                           "下载的不是有效压缩包，已删除") from exc
    except OSError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        if exc.errno == errno.ENOSPC:
            raise InstallError("COMPONENT_DISK_FULL", "磁盘空间不够，解压失败") from exc
        raise InstallError("COMPONENT_PACKAGE_INVALID",
                           f"解压失败（{type(exc).__name__}）") from exc

    exe = tmp / components.ENTRY_EXE.format(id=cid)
    if not exe.exists():
        shutil.rmtree(tmp, ignore_errors=True)
        raise InstallError("COMPONENT_PACKAGE_INVALID",
                           f"包不完整：里面没有 {exe.name}")
    if not (tmp / "manifest.json").exists():
        shutil.rmtree(tmp, ignore_errors=True)
        raise InstallError("COMPONENT_PACKAGE_INVALID", "包不完整：里面没有 manifest.json")
    return tmp


def _guard(name: str) -> None:
    """Zip Slip：包里的路径不许是绝对路径、不许含 `..`。"""
    norm = name.replace("\\", "/")
    if norm.startswith("/") or ".." in norm.split("/") or (len(norm) > 1 and norm[1] == ":"):
        raise InstallError("COMPONENT_PACKAGE_INVALID",
                           "压缩包里有非法路径，已拒绝解压")


def _place(cid: str, tmp: Path) -> None:
    """临时目录整体改名就位。已有旧版本先停进程再删（Windows 下 exe 被占用删不掉）。"""
    target = components.component_dir(cid)
    if target.exists():
        components.stop(cid)
        shutil.rmtree(target, ignore_errors=True)
        if target.exists():
            raise InstallError(
                "COMPONENT_BUSY",
                "旧版本的进程还在占用文件，删不掉。重启应用后再装一次",
            )
    try:
        os.replace(tmp, target)
    except OSError:
        # 跨盘/被占用时 rename 会失败，退回复制（慢但可靠），再删临时目录
        shutil.copytree(tmp, target)
        shutil.rmtree(tmp, ignore_errors=True)


def _ensure_space(cid: str, size: int) -> None:
    """下载 + 解压同时存在，至少要 size × 2 才不至于中途炸（精确解压后大小由包决定）。"""
    if size <= 0:
        return
    try:
        free = shutil.disk_usage(components.root().parent).free
    except OSError:
        return
    if free < size * 2:
        raise InstallError(
            "COMPONENT_DISK_FULL",
            f"磁盘空间不够：需要约 {size * 2 // 1_000_000} MB，"
            f"当前只剩 {free // 1_000_000} MB。清一些空间再装",
        )


def _exc_code(exc: Exception) -> str:
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "COMPONENT_DISK_FULL"
    if isinstance(exc, httpx.HTTPError):
        return "COMPONENT_DOWNLOAD_FAILED"
    return "COMPONENT_INSTALL_FAILED"


def _exc_message(exc: Exception) -> str:
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "磁盘空间不够"
    if isinstance(exc, httpx.HTTPError):
        return "下载没成功，检查网络后再试"
    return f"安装没成功（{type(exc).__name__}）。重启应用后重试；还不行看日志"


# ── 查询 ────────────────────────────────────────────────
def progress(cid: str) -> dict:
    """前端轮询用。**装完之后不靠内存**：内存里的状态重启会丢，磁盘才是事实。"""
    inst = components.install_state(cid)
    if inst.get("status"):
        return {
            "id": cid,
            "status": inst.get("status"),
            "phase": inst.get("phase", ""),
            "got": int(inst.get("got") or 0),
            "total": int(inst.get("total") or 0),
            "pct": int(inst.get("pct") or 0),
            "error_code": inst.get("error_code", ""),
            "error_msg": inst.get("error_msg", ""),
            "task_id": inst.get("task_id", ""),
        }
    st = components.status(cid)
    return {
        "id": cid,
        "status": "installed" if st["state"] in ("installed", "broken") else "idle",
        "phase": "",
        "got": st["bytes"],
        "total": st["size"],
        "pct": 100 if st["state"] == "installed" else 0,
        "error_code": "",
        "error_msg": "",
        "task_id": "",
    }
