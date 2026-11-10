"""网页渲染组件 worker（T8.2：真 playwright）。

三个 op，全部委托给 `shared/browser_pw.py`（主程序本进程模式用的是同一份代码，
理由见那个文件顶部）：`render` / `capture_json` / `login`。

**登录窗口必须开在这个进程里**。跨管道开不了可见窗口：窗口是 playwright 的子进程，
主程序杀不掉也等不到它；更要紧的是 profile 目录同一时刻只能被一个实例打开，
两边各开一个必然撞车。所以"弹窗 → 等用户登录 → 导出 cookies.txt"整段都在组件里，
主程序只负责把状态转成界面上的话。取消靠一个哨兵文件（`cancel_file`）——
管道是串行请求，正在等登录时再发一条 cancel 只会排在它后面。

**浏览器不打包**：优先用用户机器上的 Edge/Chrome（`channel` 由主程序传，
默认 msedge），失败才回落组件自带 Chromium（只有在打包时
`playwright install chromium` 过才有）。这就是 38 MB 组件包的全部内容。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))       # components/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))       # backend/（shared 包）

from _protocol import OpError, main  # noqa: E402
from shared.browser_pw import (      # noqa: E402
    BrowserTimeout,
    BrowserUnavailable,
    capture_json as pw_capture_json,
    open_for_login,
    render as pw_render,
)
from shared.cookies import to_netscape  # noqa: E402

VERSION = "0.2.0"
SELFTEST_URL = "data:text/html,<html><body><p>cairn-selftest</p></body></html>"


def _args(req: dict) -> dict:
    """把"从哪拿播放器目录"这类环境差异收在一处，三个 op 共用。"""
    user_data_dir = str(req.get("user_data_dir") or "").strip()
    if not user_data_dir:
        raise OpError("BROWSER_BAD_INPUT", "没给 user_data_dir（浏览器 profile 目录）")
    return {"user_data_dir": user_data_dir,
            "channel": str(req.get("channel") or ""),
            "headless": bool(req.get("headless", True))}


def _wrap(exc: Exception) -> OpError:
    if isinstance(exc, (BrowserUnavailable, BrowserTimeout)):
        code = "BROWSER_TIMEOUT" if isinstance(exc, BrowserTimeout) else "BROWSER_UNAVAILABLE"
        return OpError(code, str(exc)[:200])
    return OpError("BROWSER_FAILED", f"{type(exc).__name__}: {str(exc)[:160]}")


def render(req: dict, progress) -> dict:
    url = str(req.get("url") or "")
    if not url.lower().startswith(("http://", "https://", "data:")):
        raise OpError("BROWSER_BAD_INPUT", "只接受 http(s) 或 data: 地址")
    timeout_ms = int(req.get("timeout_ms") or 25_000)
    progress(10)
    try:
        html, final_url, status = pw_render(
            url, timeout_ms=timeout_ms,
            headless=bool(req.get("headless", True)),
            user_data_dir=str(req["user_data_dir"]),
            channel=str(req.get("channel") or ""),
        )
    except Exception as exc:      # noqa: BLE001 - 统一成带码的业务错误
        raise _wrap(exc) from exc
    progress(95)
    return {"html": html, "final_url": final_url, "status": status}


def capture_json(req: dict, progress) -> dict:
    url = str(req.get("url") or "")
    contains = str(req.get("contains") or "")
    if not url or not contains:
        raise OpError("BROWSER_BAD_INPUT", "capture_json 需要 url 与 contains")
    progress(10)
    try:
        data, cookies = pw_capture_json(
            url, contains=contains,
            headless=bool(req.get("headless", True)),
            user_data_dir=str(req["user_data_dir"]),
            channel=str(req.get("channel") or ""),
            timeout_ms=int(req.get("timeout_ms") or 25_000),
            wait_ms=int(req.get("wait_ms") or 12_000),
            min_bytes=int(req.get("min_bytes") or 1000),
        )
    except Exception as exc:      # noqa: BLE001
        raise _wrap(exc) from exc
    progress(95)
    return {"json": data, "cookies": cookies}


def login(req: dict, progress) -> dict:
    """可见窗口 + 轮询 cookie。成功就**由组件自己**写 cookies.txt。

    写文件这一步放在组件里，是为了让"同一个 profile 产出的 cookie"只有一个格式转换点；
    主程序拿到条数就够了，不需要再持有 playwright 的 cookie 结构。
    """
    login_url = str(req.get("login_url") or "")
    markers = tuple(req.get("markers") or ())
    cookie_file = str(req.get("cookie_file") or "")
    if not (login_url and markers and cookie_file):
        raise OpError("BROWSER_BAD_INPUT", "login 需要 login_url / markers / cookie_file")
    cancel_path = Path(str(req.get("cancel_file") or "")) if req.get("cancel_file") else None
    timeout_s = int(req.get("timeout_s") or 300)

    started = time.time()

    def cancelled() -> bool:
        try:
            return bool(cancel_path and cancel_path.exists())
        except OSError:
            return False

    def tick(now: float) -> None:
        # 每轮报一次：主程序按"空闲 30 秒无消息"判卡死，进度本身只是给界面看的
        progress(min(95, int((now - started) * 100 / max(1, timeout_s))))

    try:
        cookies = open_for_login(login_url, markers, timeout_s=timeout_s,
                                 cancelled=cancelled, on_tick=tick,
                                 **_args(req))
    except Exception as exc:      # noqa: BLE001
        raise _wrap(exc) from exc

    if not cookies:
        if cancelled():
            return {"cookies": 0, "cancelled": True}
        raise OpError("LOGIN_TIMEOUT", "登录超时或窗口已关闭，可以再试一次")

    try:
        path = Path(cookie_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(to_netscape(cookies), encoding="utf-8")
    except OSError as exc:
        raise OpError("LOGIN_WRITE_FAIL", f"登录成功但写 cookie 失败（{type(exc).__name__}）") from exc
    progress(100)
    return {"cookies": len(cookies)}


# ── 自检 ────────────────────────────────────────────────
def _expect(reply: dict) -> tuple[bool, str]:
    if not reply.get("ok"):
        return False, f"回包形状不对：{str(reply)[:160]}"
    if "cairn-selftest" not in (reply.get("html") or ""):
        return False, f"渲染结果里没有自检标记：{(reply.get('html') or '')[:120]}"
    if not {"html", "final_url", "status"} <= set(reply):
        return False, f"缺字段：{sorted(reply)}"
    return True, f"render ok：{len(reply['html'])} 字节，status={reply['status']}"


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import os
        import tempfile

        from _protocol import selftest

        # 自检用 data: URL：不联网、不依赖站点存活，验的是"真起了一个浏览器、
        # 真拿到了渲染后的 DOM"。profile 用临时目录，不碰用户的登录态。
        with tempfile.TemporaryDirectory(prefix="cairn-browser-") as tmp:
            code = selftest("browser", VERSION,
                            {"op": "render", "url": SELFTEST_URL,
                             "user_data_dir": tmp, "headless": True,
                             "channel": os.environ.get("CAIRN_BROWSER_CHANNEL", "msedge")},
                            _expect)
        sys.exit(code)
    sys.exit(main("browser", VERSION,
                  {"render": render, "capture_json": capture_json, "login": login},
                  sample={"op": "render", "url": SELFTEST_URL}, expect=_expect))
