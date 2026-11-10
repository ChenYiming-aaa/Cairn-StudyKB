"""M8 验收脚本（分组长大的那种）。

用法：
    cd backend && uv run python scripts/verify_m8.py
    cd backend && uv run python scripts/verify_m8.py --only protocol   # 只跑某一组

退出码：0 全绿 / 1 有用例失败 / 2 环境不满足

覆盖分组（对应 `M8-补充记录.md` §1.1 的六层）：
  §1 protocol   T8.0/T8.2 组件清单 / 三态可用性 / 协议往返（真子进程）/ 缺组件降级 / HTTP 不 500
  §3 install    T8.3 下载中心（安装 / 续传 / 源不支持 Range / 坏包 / 取消 / 卸载 / 端点）
  §4 slim       T8.1 主包瘦身（体积与 excludes）—— 见 tools/ 与 HANDOFF，不在本脚本里
  §5 update     T8.5/T8.6 版本元数据形状、四处版本一致、更新器接线、版本比较边界

**不联网、不调模型**：组件用的是真子进程但只做最小任务；下载走本地 HTTP 服务器
（`CAIRN_COMPONENT_BASE_URL` 只为本脚本存在），后端起在 127.0.0.1 的临时端口上。

用法补充：
    uv run python scripts/verify_m8.py --only install    # 只跑下载中心那一组
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-m8-"))
(TMP / ".env").write_text("LLM_API_KEY=sk-verify-m8-not-a-real-key\n", encoding="utf-8")
os.environ["DATA_DIR"] = str(TMP)            # 必须早于 import app
os.environ["VECTOR_ENABLED"] = "1"           # 故意开着：验的是"算不出向量也别 500"
os.environ["CAIRN_ENV_STRICT"] = "1"
os.environ.setdefault("LOG_LEVEL", "WARNING")
# 组件的默认模型目录（payload 没带 cache_dir 时用它）。指到项目自己的
# data/models，验收就不会因为"这台机器没下过 bge"去拉 90 MB。
os.environ.setdefault("CAIRN_MODELS_DIR", str(ROOT / "data" / "models"))
os.environ.pop("LLM_API_KEY", None)
# CAIRN_COMPONENT_MODE 刻意**不清**：`CAIRN_COMPONENT_MODE=process` 跑本脚本是验
# 「走组件管道」那条路的标准做法（见 运行与打包.md），清掉就等于那条命令是假的
FORCED = os.environ.get("CAIRN_COMPONENT_MODE", "auto").strip().lower() or "auto"

sys.path.insert(0, str(BACKEND))

from app.services import component_proc, components, embedder, retriever, transcriber  # noqa: E402
from app.services.fetch_errors import FetchError, message_for  # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 46 - len(title)))


# ── §1 protocol ─────────────────────────────────────────────
def group_protocol() -> None:
    step("§1.1 清单")
    man = components.manifest()
    entries = components.entries()
    check("app/components.json 可读", bool(man.get("components")), str(man.get("manifest_version")))
    check("三个组件都在清单里", set(entries) == set(components.IDS), f"{sorted(entries)}")
    need = {"id", "name", "size", "asset", "unpack_dir", "why"}
    missing = {cid: sorted(need - set(e)) for cid, e in entries.items() if need - set(e)}
    check("条目字段齐全", not missing, str(missing))
    check("清单自带 min_app_version", bool(man.get("min_app_version")), str(man.get("min_app_version")))
    check("shasum 字段存在（T8.2 才填真值，现在可以空）",
          all("sha256" in e for e in entries.values()))

    step("§1.2 三态可用性")
    expect = {"process": "component", "local": "local"}.get(FORCED, "local")
    check(f"可用性判定符合预期（模式 {FORCED} → {expect}；auto 下本机有 torch 就该是 local）",
          components.resolve("embed") == expect, str(components.resolve("embed")))
    os.environ["CAIRN_COMPONENT_MODE"] = "process"
    try:
        components.reset_cache()
        check("强制 process 时 embed 能定位到组件入口",
              components.resolve("embed") == "component", str(components.resolve("embed")))
    finally:
        if FORCED == "auto":
            os.environ.pop("CAIRN_COMPONENT_MODE", None)
        else:
            os.environ["CAIRN_COMPONENT_MODE"] = FORCED
        components.reset_cache()
    check("不认识的组件 id 直接返回 None", components.resolve("nope") is None)

    step("§1.3 协议往返（真子进程）")
    hello = components.call("embed", "hello", {}, timeout=10)
    check("hello 通且组件自报家门",
          hello.get("ok") and hello.get("component") == "embed", str(hello.get("version")))
    check("hello 带 min_app_version", bool(hello.get("min_app_version")))
    pid1 = components.call("embed", "hello", {}, timeout=10).get("pid")
    check("同一组件复用同一个进程（没有每次重启）",
          pid1 == hello.get("pid"), f"{hello.get('pid')} vs {pid1}")

    reply = components.call("embed", "encode",
                            {"kind": "doc", "texts": ["番茄工作法", "间隔重复"]}, timeout=30)
    vectors = reply.get("vectors") or []
    check("encode 文档：条数与输入一致", len(vectors) == 2, f"{len(vectors)} 条")
    check("encode 文档：维度 = 512", all(len(v) == 512 for v in vectors), str(reply.get("dim")))
    norm = sum(v * v for v in vectors[0]) ** 0.5 if vectors else 0.0
    check("向量已归一化", abs(norm - 1.0) < 1e-3, f"|v|={norm:.4f}")
    check("不同文本给不同向量", vectors[0] != vectors[1])

    again = components.call("embed", "encode", {"kind": "doc", "texts": ["番茄工作法"]}, timeout=30)
    # 真模型（bge）不是"逐位可复现"的：这次只送 1 条，上一次是 2 条，批大小不同
    # 会让 BLAS 的归约顺序变，末位会差 1e-7 量级。要求的是"同一个模型稳定输出"，
    # 所以比容差而不是比相等（空实现时期这条比的是相等，T8.2 起放宽）。
    delta = max(abs(a - b) for a, b in zip(again["vectors"][0], vectors[0]))
    check("同样的文本给同样的向量（容差 1e-4）", delta < 1e-4, f"max|Δ|={delta:.2e}")

    query = components.call("embed", "encode", {"kind": "query", "texts": ["番茄工作法"]},
                            timeout=30)
    check("查询向量与文档向量不同（前缀在组件里加）", query["vectors"][0] != vectors[0])

    empty = components.call("embed", "encode", {"kind": "doc", "texts": []}, timeout=10)
    check("空输入返回空向量，不报错", empty.get("ok") and empty.get("vectors") == [])

    try:
        components.call("embed", "nonsense", {}, timeout=10)
        check("未知 op 回业务错误而不是超时", False, "居然没抛")
    except components.ComponentError as exc:
        check("未知 op 回业务错误而不是超时", exc.code == "COMPONENT_BAD_OP", exc.code)

    seen: list[int] = []
    wav = TMP / "silence.wav"
    _blank_wav(wav)
    reply = components.call("asr", "transcribe", {"path": str(wav), "model": "tiny"},
                            on_progress=seen.append, timeout=180, idle=True)
    check("长任务收到 progress 事件", len(seen) >= 1, str(seen))
    check("转录回的是 segments 列表（静音可以是 0 段）",
          isinstance(reply.get("segments"), list), f"{len(reply.get('segments') or [])} 段")

    step("§1.4 缺组件时降级（注入 resolve=None，模拟没装的机器）")
    real_resolve = components.resolve
    try:
        components.resolve = lambda cid: None          # type: ignore[assignment]
        check("embedder 自己知道算不出向量", embedder.usable() is False)
        check("检索宣称向量不可用（不是先报能再炸）", retriever.vector_ready() is False)
        try:
            embedder.encode_docs(["x"])
            check("直接要向量时报 COMPONENT_MISSING", False, "居然没抛")
        except components.ComponentError as exc:
            check("直接要向量时报 COMPONENT_MISSING", exc.code == "COMPONENT_MISSING", exc.code)
        try:
            transcriber._load_model("small")
            check("转录报 COMPONENT_MISSING", False, "居然没抛")
        except FetchError as exc:
            check("转录报 COMPONENT_MISSING", exc.code == "COMPONENT_MISSING", exc.code)
            check("转录文案不是兜底句", "采集失败" not in exc.message, exc.message)
        check("补向量任务不再派发", embedder.schedule(item_id=1) is None)
    finally:
        components.resolve = real_resolve          # type: ignore[assignment]

    step("§1.5 错误码与文案登记")
    check("后端登记了 COMPONENT_MISSING 文案",
          "设置" in message_for("COMPONENT_MISSING"), message_for("COMPONENT_MISSING"))
    js = (ROOT / "frontend" / "src" / "api" / "client.js").read_text(encoding="utf-8")
    check("前端 FRIENDLY 映射了 COMPONENT_MISSING", "COMPONENT_MISSING" in js)
    check("前端不再教用户跑 playwright install", "playwright install" not in js)

    step("§1.6 HTTP 层：没组件也不能 500")
    port = _free_port()
    server = _start_server(port)
    base = f"http://127.0.0.1:{port}"
    try:
        for path in ("/api/health", "/api/knowledge", "/api/tasks"):
            with urllib.request.urlopen(base + path, timeout=10) as resp:
                check(f"GET {path} 200", resp.status == 200, str(resp.status))
        with urllib.request.urlopen(base + "/api/search?q=" + "%E7%95%AA%E8%8C%84", timeout=10) as resp:
            body = json.load(resp)
            check("GET /api/search 200 且给出了降级原因",
                  resp.status == 200 and "fallback" in body, str(body.get("fallback")))
        # S-1：缺组件时的原因码必须是"没装组件"，不能是"向量距离太远"（前端对后者无文案）
        real = components.resolve
        try:
            components.resolve = lambda cid: None          # type: ignore[assignment]
            with urllib.request.urlopen(base + "/api/search?q=" + quote("zzz库里没有这个zzz"),
                                        timeout=10) as resp:
                body = json.load(resp)
                check("缺向量组件时 fallback 指名是缺组件",
                      body.get("fallback") == "vector_component_missing",
                      str(body.get("fallback")))
        finally:
            components.resolve = real                       # type: ignore[assignment]
    except Exception:
        traceback.print_exc()
        check("HTTP 层无异常", False, "见上面的栈")
    finally:
        server.should_exit = True
        time.sleep(0.4)

    step("§1.7 生命周期")
    # HTTP 段（uvicorn 的 lifespan shutdown）已经 stop_all 过一次，这里重新起一个再验，
    # 否则拿到的是空会话表，"进程退出了"就是句空话
    components.call("embed", "hello", {}, timeout=10)
    proc = component_proc._registry.get("embed")
    held = proc.proc if proc else None
    check("重新起了一个组件进程", held is not None and held.poll() is None)
    components.stop_all()
    check("stop_all 之后会话表清空", not component_proc._registry)
    check("组件进程真的退出了", held is None or held.poll() is not None,
          "仍在运行" if held and held.poll() is None else "已退出")


# ── §3 install（T8.3 下载中心） ──────────────────────────────
# 为什么不拿真包验：embed 的 zip 262 MB、解包 690 MB，一次验收要好几分钟且吃满硬盘。
# 这里现造三个**结构完全一致**的假包（`cairn-<id>.exe` + `_internal/` + `manifest.json`），
# 用本地 HTTP 服务器当下载源 —— 验的是「下载/续传/校验/解压/就位/卸载」这条链路，
# 与包多大无关。真包的端到端验证在 T8.8 的干净机器走查里做。
def group_install() -> None:
    import hashlib
    import http.server
    import shutil
    import zipfile

    from app.db.migrate import init_db
    from app.services import component_install

    init_db()

    # 装完之后 status() 会去探 exe 能不能跑；假 exe 显然跑不起来，会污染 state。
    # 用 none 模式把"探活"整段关掉，验的是文件落位，不是组件能不能跑（§1 已验过）。
    keep_mode = os.environ.get("CAIRN_COMPONENT_MODE")
    os.environ["CAIRN_COMPONENT_MODE"] = "none"

    pkg_dir = TMP / "pkgs"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    def make_pkg(cid: str, pad: int = 0) -> tuple[Path, str, int]:
        """造一个结构合法的组件包，返回 (zip 路径, sha256, 字节数)。"""
        stage = TMP / f"stage-{cid}"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        (stage / f"cairn-{cid}.exe").write_bytes(b"MZ fake component exe\n")
        (stage / "manifest.json").write_text(json.dumps(
            {"id": cid, "version": "0.2.0", "min_app_version": "0.2.0"},
            ensure_ascii=False), encoding="utf-8")
        (stage / "_internal").mkdir()
        if pad:
            (stage / "_internal" / "payload.bin").write_bytes(b"\x00" * pad)
        else:
            (stage / "_internal" / "payload.bin").write_bytes(b"x" * 2048)
        out = pkg_dir / f"fake-{cid}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(stage).as_posix())
        data = out.read_bytes()
        return out, hashlib.sha256(data).hexdigest(), len(data)

    pkgs = {cid: make_pkg(cid, pad=(8 * 1024 * 1024 if cid == "asr" else 0))
            for cid in components.IDS}
    # 当前生效的 (zip, sha256, size)。§3.4 会把 sha 换成一个假的再换回来，
    # `fake_manifest` 每次都从这张表读，所以换完立刻生效（不要在这里快照成常量）。
    sha_size = {cid: (p, sha, size) for cid, (p, sha, size) in pkgs.items()}

    def fake_manifest() -> dict:
        return {
            "manifest_version": 1,
            "min_app_version": "0.2.0",
            "release_tag": "test-tag",
            "repo": "test/repo",
            "components": [
                {"id": cid, "name": components.LABELS[cid], "why": "验收用假包",
                 "size": sha_size[cid][2], "sha256": sha_size[cid][1],
                 "asset": f"fake-{cid}.zip", "unpack_dir": cid}
                for cid in components.IDS
            ],
        }

    class Source(http.server.BaseHTTPRequestHandler):
        files: dict[str, Path] = {}
        ranges: list[str] = []
        ignore_range = False
        slow = 0.0

        def do_GET(self) -> None:                       # noqa: N802 - 基类命名
            name = self.path.lstrip("/").split("?")[0]
            path = self.files.get(name)
            if not path or not path.exists():
                self.send_error(404)
                return
            data = path.read_bytes()
            total = len(data)
            rng = self.headers.get("Range")
            if rng:
                Source.ranges.append(rng)
            start = 0
            if rng and not Source.ignore_range:
                start = int(rng.split("=")[1].split("-")[0] or 0)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{total - 1}/{total}")
            else:
                self.send_response(200)
            body = data[start:]
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            step = 64 * 1024
            try:
                for i in range(0, len(body), step):
                    self.wfile.write(body[i:i + step])
                    if Source.slow:
                        time.sleep(Source.slow)
            except (ConnectionError, OSError):
                # 取消安装时客户端会直接断开，这是预期行为，别在验收输出里刷栈
                pass

        def log_message(self, *args) -> None:           # 静音：验收输出里不需要访问日志
            pass

    Source.files = {p.name: p for p, _, _ in pkgs.values()}
    src = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Source)
    threading.Thread(target=src.serve_forever, daemon=True).start()
    os.environ["CAIRN_COMPONENT_BASE_URL"] = f"http://127.0.0.1:{src.server_port}"
    real_manifest = components.manifest
    components.manifest = fake_manifest                  # type: ignore[assignment]
    components.reset_cache()

    def wait(cid: str, timeout: float = 90.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = components.install_state(cid)
            if st.get("status") in ("done", "failed", "cancelled"):
                return st
            time.sleep(0.05)
        return components.install_state(cid)

    def current_sha_size(cid: str, sha: str | None = None) -> None:
        path, good, size = pkgs[cid]
        sha_size[cid] = (path, sha or good, size)

    try:
        step("§3.1 安装（正常路径）")
        from app.db.conn import get_conn
        from app.services import embedder

        def index_task_count() -> int:
            c = get_conn()
            try:
                return int(c.execute(
                    "SELECT COUNT(*) FROM agent_task WHERE type='index_embed'").fetchone()[0])
            finally:
                c.close()

        baseline = index_task_count()       # 装之前先记一笔，才能证明"装的过程没派"
        task_id = component_install.start("embed")
        check("install 立刻返回 task_id", bool(task_id), task_id[:8])
        check("装的过程中 progress 是 running",
              component_install.progress("embed")["status"] in ("running", "done"),
              component_install.progress("embed")["status"])
        st = wait("embed")
        check("安装任务跑完（status=done）", st.get("status") == "done",
              f"{st.get('status')} {st.get('error_code')}")
        base = components.component_dir("embed")
        check("解压到 components/embed/",
              (base / "cairn-embed.exe").exists() and (base / "manifest.json").exists(),
              str(base))
        check("状态变成 installed", components.status("embed")["state"] == "installed",
              components.status("embed")["state"])
        check("进度到 100 且没有残留 .part",
              component_install.progress("embed")["pct"] == 100
              and not component_install.part_path("embed").exists())
        check("没有留下临时解压目录",
              not [p for p in components.root().glob(".tmp-*")], "残留 .tmp-*")

        step("§3.1b 装完补向量（只在组件真能跑时才派）")
        # T8.8 干净机走查逮到的：装完 embed 不回填历史向量，老条目永远只有全文命中。
        # 这里验两半：① 假包握手不通时不许派（否则任务中心一条红）；② 能跑时派一次全库。
        check("假包握手不通 → 不派补向量任务", index_task_count() == baseline,
              f"index_embed {baseline} → {index_task_count()}")

        calls: list = []
        real_resolve, real_schedule = components.resolve, embedder.schedule
        components.resolve = lambda cid: "component"          # 假装握手通过
        embedder.schedule = lambda item_id=None: calls.append(item_id)
        try:
            component_install._backfill_vectors("embed")
            component_install._backfill_vectors("asr")
            component_install._backfill_vectors("browser")
        finally:
            components.resolve, embedder.schedule = real_resolve, real_schedule
        check("能跑时给 embed 派一次全库补（item_id=None）", calls == [None], str(calls))
        check("asr / browser 不补索引（只补一次）", len(calls) == 1, str(calls))

        step("§3.2 断点续传（源支持 Range）")
        components.uninstall("embed")
        part = component_install.part_path("embed")
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(pkgs["embed"][0].read_bytes()[:1024])   # 模拟上次下到 1 KB 断掉
        Source.ranges.clear()
        Source.ignore_range = False
        component_install.start("embed")
        st = wait("embed")
        check("从断点续传后安装成功", st.get("status") == "done",
              f"{st.get('status')} {st.get('error_code')}")
        check("真的带了 Range 头（bytes=1024-）", "bytes=1024-" in Source.ranges,
              str(Source.ranges))
        check("续传后文件完整（sha256 通过才会 done）", st.get("status") == "done")

        step("§3.3 源不支持 Range（必须从头写，不能把新数据接在旧字节后）")
        components.uninstall("embed")
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(pkgs["embed"][0].read_bytes()[:1024])
        Source.ranges.clear()
        Source.ignore_range = True
        component_install.start("embed")
        st = wait("embed")
        check("服务端回 200 时自动从头下载并成功", st.get("status") == "done",
              f"{st.get('status')} {st.get('error_code')}")
        check("请求里确实带了 Range（被服务端忽略了）", bool(Source.ranges), str(Source.ranges))
        Source.ignore_range = False

        step("§3.4 坏包（sha256 不对）必须拒绝并清理")
        components.uninstall("embed")
        current_sha_size("embed", sha="0" * 64)
        component_install.start("embed")
        st = wait("embed")
        check("校验不过时任务失败", st.get("status") == "failed", st.get("status"))
        check("错误码是 COMPONENT_HASH_MISMATCH",
              st.get("error_code") == "COMPONENT_HASH_MISMATCH", st.get("error_code"))
        check("失败后没有装出半个目录", not components.component_dir("embed").exists())
        check("失败后 .part 已清掉", not component_install.part_path("embed").exists())
        check("状态回到 missing", components.status("embed")["state"] == "missing",
              components.status("embed")["state"])
        current_sha_size("embed")

        step("§3.5 取消（下载中途）")
        Source.slow = 0.01                                # 8 MB / 64 KB × 10 ms ≈ 1.3 s
        component_install.start("asr")
        got = 0
        for _ in range(400):
            st = components.install_state("asr")
            got = int(st.get("got") or 0)
            if got > 300_000:
                break
            time.sleep(0.02)
        check("下载确实启动了（下到 300 KB 以上）", got > 300_000, f"{got} 字节")
        check("cancel 返回 True", component_install.cancel("asr") is True)
        st = wait("asr", timeout=30)
        check("取消后状态是 cancelled", st.get("status") == "cancelled", st.get("status"))
        check("取消后不留半成品目录", not components.component_dir("asr").exists())
        check("取消后 .part 已删除", not component_install.part_path("asr").exists())
        Source.slow = 0.0

        step("§3.6 卸载")
        component_install.start("embed")
        wait("embed")
        freed = components.uninstall("embed")
        check("卸载返回释放的字节数", freed > 0, f"{freed} 字节")
        check("目录已删除", not components.component_dir("embed").exists())
        check("状态回到 missing", components.status("embed")["state"] == "missing")

        step("§3.7 HTTP 端点（真 uvicorn）")
        port = _free_port()
        server = _start_server(port)
        base = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(base + "/api/components", timeout=10) as resp:
                body = json.load(resp)
                check("GET /api/components 200 且三个条目",
                      resp.status == 200 and len(body.get("items") or []) == 3,
                      str(len(body.get("items") or [])))
                check("清单元信息一起返回（repo / tag / mirror）",
                      bool(body.get("repo")) and "mirror" in body, str(body.get("release_tag")))
            req = urllib.request.Request(
                base + "/api/components/embed/install", data=b"{}", method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                check("POST install 返回 202", resp.status == 202, str(resp.status))
                check("202 里带 task_id", bool(json.load(resp).get("task_id")))
            done = False
            for _ in range(200):
                with urllib.request.urlopen(base + "/api/components/embed/progress",
                                            timeout=10) as resp:
                    pr = json.load(resp)
                if pr.get("status") == "done":
                    done = True
                    break
                time.sleep(0.05)
            check("GET progress 一路跟到 done", done, str(pr))
            with urllib.request.urlopen(base + "/api/components", timeout=10) as resp:
                items = {i["id"]: i for i in json.load(resp)["items"]}
            check("列表里 embed 显示已安装且带占用空间",
                  items["embed"]["state"] == "installed" and items["embed"]["bytes"] > 0,
                  f"{items['embed']['state']} {items['embed']['bytes']}")
            req = urllib.request.Request(base + "/api/components/embed", method="DELETE")
            with urllib.request.urlopen(req, timeout=10) as resp:
                check("DELETE 卸载 200 且报释放空间", json.load(resp).get("freed", 0) > 0)
            try:
                urllib.request.urlopen(base + "/api/components/nope/install",
                                       data=b"{}", timeout=10)
                check("不认识的组件返回 404", False, "居然 200")
            except urllib.error.HTTPError as exc:
                check("不认识的组件返回 404", exc.code == 404, str(exc.code))
        finally:
            server.should_exit = True
            time.sleep(0.4)

    except Exception:
        traceback.print_exc()
        check("§3 安装组跑完", False, "异常中断，见上面的栈")
    finally:
        components.manifest = real_manifest              # type: ignore[assignment]
        os.environ.pop("CAIRN_COMPONENT_BASE_URL", None)
        if keep_mode is None:
            os.environ.pop("CAIRN_COMPONENT_MODE", None)
        else:
            os.environ["CAIRN_COMPONENT_MODE"] = keep_mode
        components.reset_cache()
        src.shutdown()


# ── 环境 ────────────────────────────────────────────────────
# ── §5 update（T8.5 更新器 / T8.6 版本元数据）────────────────────
def group_update() -> None:
    """验的是"能在源码里验的部分"。

    三个真机断言（断网人话 / 取消删净 / 无孤儿后端）需要装一个包、拉 170 MB、起 NSIS，
    放在 `tools/e2e_update.py` 里单独跑 —— 本脚本的底线是"不装东西、不联网、随时能跑"。
    这里替它们守住的是**形状与常量**：版本四处一致、IPC 通道齐、preload 没敞开、
    版本比较的边界都对。
    """
    from app import version as version_meta

    step("§5.1 版本元数据（T8.6）")
    info = version_meta.info()
    check("GET /api/version 形状固定",
          set(info) == {"version", "commit", "built_at"}, str(sorted(info)))
    check("version 与 app.version.VERSION 同源",
          info["version"] == version_meta.VERSION, info["version"])
    check("源码运行不给编造的 commit / built_at",
          info["commit"] is None and info["built_at"] is None, str(info))

    port = _free_port()
    server = _start_server(port)
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(base + "/api/version", timeout=10) as resp:
            body = json.load(resp)
        check("HTTP GET /api/version 200 且同形", set(body) == {"version", "commit", "built_at"},
              str(sorted(body)))
        with urllib.request.urlopen(base + "/api/health", timeout=10) as resp:
            health = json.load(resp)
        check("health.version 与 version.version 一致",
              health.get("version") == body.get("version"),
              f'{health.get("version")} vs {body.get("version")}')
    finally:
        server.should_exit = True
        time.sleep(0.4)

    step("§5.2 四处版本号一致（bump_version --check）")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "bump_version.py"), "--check"],
                       capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()
    check("tools/bump_version.py --check 通过", r.returncode == 0, tail[-1] if tail else r.stderr[:80])
    check("四处文件都读到了（不是空串算过）",
          all(line.split()[-1] not in ("", "(未读到)") for line in tail if line.strip()),
          " / ".join(tail[:4]))

    step("§5.3 更新器接线（desktop/）")
    desktop = ROOT / "desktop"
    main_js = (desktop / "main.js").read_text(encoding="utf-8")
    preload_js = (desktop / "preload.js").read_text(encoding="utf-8")
    updater_js = (desktop / "updater.js").read_text(encoding="utf-8")
    pkg = json.loads((desktop / "package.json").read_text(encoding="utf-8"))
    files = pkg.get("build", {}).get("files", [])
    for name in ("preload.js", "updater.js", "semver.js"):
        check(f"打包清单包含 {name}", name in files, str(files))
    check("窗口真的挂了 preload", "preload.js" in main_js and "preload:" in main_js)
    for ch in ("update:check", "update:download", "update:cancel", "update:install"):
        check(f"main 注册通道 {ch}", f"ipcMain.handle('{ch}'" in main_js)
    check("preload 暴露四个方法（不多不少）",
          preload_js.count("ipcRenderer.invoke") == 4, str(preload_js.count("ipcRenderer.invoke")))
    check("preload 不把 ipcRenderer 本身递出去",
          "ipcRenderer," not in preload_js and "ipcRenderer:" not in preload_js)
    check("IPC 校验调用来源", "trusted" in main_js and "FORBIDDEN" in main_js)
    check("下载只认主进程缓存的检查结果（不收渲染进程传的 URL）",
          "ipcMain.handle('update:download', guard('download', async () =>" in main_js)
    check("安装前先杀后端（避免目录被占用/孤儿）",
          "quitting = true" in main_js and "killBackend()" in main_js)
    check("更新源默认 api.github.com（不是假地址）",
          "api.github.com" in updater_js and "example.invalid" not in json.dumps(pkg),
          "example.invalid" if "example.invalid" in json.dumps(pkg) else "ok")
    check("有 sha256 校验分支", "createHash('sha256')" in updater_js or 'createHash("sha256")' in updater_js)
    check("取消/失败会删半截文件", "rmSync(file, { force: true })" in updater_js)
    check("安装器不带 /S 静默（默认让用户点下一步）",
          "spawn(file, [], {" in main_js and "'/S'" not in main_js)
    check("关于页已接更新器（不再是要 M8 才接的占位）",
          "useUpdater" in (ROOT / "frontend" / "src" / "components" / "settings" / "AboutTab.vue")
          .read_text(encoding="utf-8"))

    step("§5.4 版本比较（node 直接跑 semver.js）")
    node = shutil.which("node")
    if not node:
        check("这台机器有 node 可跑比较断言", False, "PATH 里没有 node")
    else:
        script = TMP / "semver_check.js"
        script.write_text(
            "const { compareVersions: c, parseVersion: p } = require("
            + json.dumps(str(desktop / "semver.js")) + ");\n"
            "const cases = [\n"
            "  [['0.2.0', '0.1.9'], 1, '新版比旧版新'],\n"
            "  [['0.1.9', '0.2.0'], -1, '旧版不报新'],\n"
            "  [['0.2.0', '0.2.0'], 0, '同版相等'],\n"
            "  [['v0.2.0', '0.2.0'], 0, 'v 前缀忽略'],\n"
            "  [['0.10.0', '0.9.9'], 1, '按数值不按字符串'],\n"
            "  [['1.0', '1.0.0'], 0, '缺段补零'],\n"
            "  [['0.2.0', '0.2.0-rc1'], 1, '正式版高于预发布'],\n"
            "  [['0.2.0-rc1', '0.2.0'], -1, '预发布低于正式版'],\n"
            "  [['garbage', '0.2.0'], 0, '解析不出来不误报'],\n"
            "];\n"
            "let bad = 0;\n"
            "for (const [args, want, label] of cases) {\n"
            "  const got = c(args[0], args[1]);\n"
            "  if (got !== want) { bad += 1; console.log('FAIL', label, got); }\n"
            "}\n"
            "if (!p('0.2.0-alpha.1')) { bad += 1; console.log('FAIL 预发布解析'); }\n"
            "console.log(bad ? 'bad=' + bad : 'ok');\n",
            encoding="utf-8")
        out = subprocess.run([node, str(script)], capture_output=True, text=True)
        check("九条版本比较边界全对", out.stdout.strip().endswith("ok"), out.stdout.strip()[:120])

        # 这条是拿真实教训换来的：updater.js 里既 `const { parseVersion } = require('./semver')`
        # 又留着一份 `function parseVersion()`，语法检查报了 duplicate declaration，
        # 而打包不会报错 —— 装出来双击只弹一个标题为 "Error" 的框，`shell.log` 一行都不写。
        load = TMP / "updater_load.js"
        load.write_text(
            "const Module = require('module');\n"
            "const orig = Module._load;\n"
            "Module._load = function (req) {\n"
            "  if (req === 'electron') return {\n"
            "    app: { getVersion: () => '0.1.9', getPath: () => require('os').tmpdir(), isPackaged: false },\n"
            "    net: { request: () => { throw new Error('不该在这里发请求') } },\n"
            "  };\n"
            "  return orig.apply(this, arguments);\n"
            "};\n"
            "const u = require(" + json.dumps(str(desktop / "updater.js")) + ");\n"
            "const ok = u.compareVersions('0.2.0', '0.1.9') === 1 && typeof u.check === 'function'\n"
            "  && typeof u.download === 'function' && typeof u.cancel === 'function';\n"
            "console.log(ok ? 'ok' : 'bad');\n",
            encoding="utf-8")
        out2 = subprocess.run([node, str(load)], capture_output=True, text=True)
        check("updater.js 能真的加载起来（假 electron 模块）",
              out2.stdout.strip() == "ok", (out2.stderr or out2.stdout).strip()[:160])

    step("§5.5 三个真机断言在别处（不是漏了）")
    e2e = ROOT / "tools" / "e2e_update.py"
    check("存在端到端实测脚本", e2e.exists(), str(e2e.relative_to(ROOT)))
    if e2e.exists():
        text = e2e.read_text(encoding="utf-8")
        for key, label in (("连不上", "断网人话"), ("取消后临时目录没有 exe 残留", "取消删净"),
                           ("没有孤儿 cairn-backend.exe", "无孤儿后端")):
            check(f"端到端脚本里有「{label}」断言", key in text)


def _blank_wav(path: Path, seconds: float = 1.0) -> None:
    """静音 wav 当转录素材：验的是"管道通"，不是识别准确率（见 asr 组件自检的说明）。"""
    import wave

    with wave.open(str(path), "wb") as fp:
        fp.setnchannels(1)
        fp.setsampwidth(2)
        fp.setframerate(16_000)
        fp.writeframes(bytes(2 * int(16_000 * seconds)))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(port: int):
    import uvicorn

    from app.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                            access_log=False)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1):
                return server
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("后端没能在 30 秒内起来")


GROUPS = {"protocol": group_protocol, "install": group_install, "update": group_update}


def main() -> int:
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    if FORCED == "none":
        print("CAIRN_COMPONENT_MODE=none 没有可跑的子进程；本脚本改用 auto/local/process 跑。")
        return 2
    print(f"Cairn M8 验收 · 临时数据目录 {TMP}")
    for name, fn in GROUPS.items():
        if only and only != name:
            continue
        try:
            fn()
        except Exception:
            traceback.print_exc()
            check(f"§{name} 跑完", False, "异常中断，见上面的栈")
    components.stop_all()
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} PASS")
    print(f"临时数据目录：{TMP}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
