"""组件 worker 的公共协议循环（T8.0）。

协议（M8 §2.3）：一行一个 JSON，stdin 进 stdout 出。
**stdout 只许放协议行** —— 组件里任何一个 print 都会打断主程序的 id 配对；
日志一律 stderr，主程序转到 `app.log`（前缀 `[embed]` 这种）。

```jsonc
{"id":1,"op":"encode","kind":"doc","texts":["..."]}      // 请求
{"id":1,"ok":true,"vectors":[[...]],"dim":512}            // 响应
{"id":2,"event":"progress","pct":42}                      // 长任务的进度
{"id":2,"ok":false,"code":"ASR_FAILED","message":"..."}   // 出错
{"id":1,"op":"hello"} → {"id":1,"ok":true,"component":"embed","version":"0.2.0",...}
```

`--selftest` 是**起一个自己的子进程**跑握手 + 一次最小任务，不是"直接调函数"：
T8.2 打包后最容易坏的地方是 exe 起不来、stdout 被污染、中文编码错，
这些只有真起进程才测得出来。
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import traceback
from pathlib import Path

MIN_APP_VERSION = "0.2.0"
SELFTEST_TIMEOUT = 120.0


class OpError(Exception):
    """handler 里想回报一个带码的业务错误时抛它。"""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _log(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _utf8_stdio() -> None:
    """Windows 上默认 cp936，中文进去就是乱码。两个方向都要钉死 utf-8。"""
    for stream, kwargs in ((sys.stdin, {"errors": "replace"}),
                           (sys.stdout, {"newline": "\n"}),
                           (sys.stderr, {"newline": "\n"})):
        try:
            stream.reconfigure(encoding="utf-8", **kwargs)   # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - 被重定向成不支持 reconfigure 的流时忽略
            pass


def serve(cid: str, version: str, handlers: dict) -> int:
    _utf8_stdio()
    _log(f"{cid} worker 就绪，version={version}")
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            _log(f"忽略一行非 JSON：{raw[:120]}")
            continue
        rid = req.get("id")
        op = str(req.get("op") or "")
        try:
            if op == "hello":
                _emit({"id": rid, "ok": True, "component": cid, "version": version,
                       "min_app_version": MIN_APP_VERSION, "pid": _pid()})
                continue
            if op == "shutdown":
                _emit({"id": rid, "ok": True})
                return 0
            handler = handlers.get(op)
            if handler is None:
                raise OpError("COMPONENT_BAD_OP", f"不认识的 op：{op}")
            result = handler(req, lambda pct: _emit({"id": rid, "event": "progress",
                                                     "pct": max(0, min(100, int(pct)))}))
            payload = {"id": rid, "ok": True}
            payload.update(result or {})
            _emit(payload)
        except OpError as exc:
            _emit({"id": rid, "ok": False, "code": exc.code, "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - 任何异常都要回一条，不能让主程序等到超时
            _emit({"id": rid, "ok": False, "code": "COMPONENT_FAILED",
                   "message": f"{type(exc).__name__}: {exc}"})
            traceback.print_exc(file=sys.stderr)
    return 0


def _pid() -> int:
    import os

    return os.getpid()


# ── 自检 ────────────────────────────────────────────────
def selftest(cid: str, version: str, sample: dict, expect) -> int:
    """`expect(payload) -> (bool, str)`；返回退出码。"""
    _utf8_stdio()
    if getattr(sys, "frozen", False):
        argv = [sys.executable, "--serve"]
    else:
        argv = [sys.executable, str(Path(sys.argv[0]).resolve()), "--serve"]
    print(f"· 自检 {cid}：起子进程 {' '.join(argv)}")

    proc = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    killer = threading.Timer(SELFTEST_TIMEOUT, proc.kill)
    killer.start()
    try:
        hello = _ask(proc, {"id": 1, "op": "hello"})
        if not (hello and hello.get("ok") and hello.get("component") == cid):
            print(f"× 握手失败：{hello}")
            return 1
        print(f"  hello ok：version={hello.get('version')} pid={hello.get('pid')}")

        reply = _ask(proc, {"id": 2, **sample})
        ok, detail = expect(reply or {})
        print(("  " if ok else "× ") + detail)
        return 0 if ok else 1
    finally:
        killer.cancel()
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _ask(proc: subprocess.Popen, body: dict) -> dict | None:
    proc.stdin.write(json.dumps(body, ensure_ascii=False) + "\n")   # type: ignore[union-attr]
    proc.stdin.flush()                                            # type: ignore[union-attr]
    while True:
        line = proc.stdout.readline()                             # type: ignore[union-attr]
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print(f"  ! stdout 混进非协议内容：{line[:80]}")
            continue
        if msg.get("event") == "progress":
            print(f"  progress {msg.get('pct')}%")
            continue
        return msg


def main(cid: str, version: str, handlers: dict, sample: dict, expect) -> int:
    """worker 的统一入口：`--serve` 起服务，`--selftest` 自检，默认也起服务。"""
    if "--selftest" in sys.argv:
        return selftest(cid, version, sample, expect)
    return serve(cid, version, handlers)
