"""组件子进程的收发机器（T8.0）：起进程、配 id、读回包、超时、崩溃重启。

拆成独立模块的理由只有一条：总纲 §7 要求单文件 ≤300 行，而"协议收发"与
"可用性判定 + 清单 + 状态"是两件事，混在一个文件里 L3 加下载逻辑必然爆。

**stdout 只能是协议行**，组件里任何 print 都会打断 id 配对；日志一律 stderr，
这里转到 `app.log` 并加 `[embed]` 这种前缀。

并发模型：每个组件**一个进程 + 一把锁**，同一时刻只处理一个请求（组件内部串行）。
embedding 本来就是批量的，够用；asr / browser 是长任务，排队正好符合直觉。
"""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
HELLO_TIMEOUT = 10.0
IDLE_EXIT = 600.0          # 空转 10 分钟自杀，下次调用再起（§2.3）
MAX_FAILURES = 2           # 连续两次失败判「异常」，UI 给「重新安装」

_registry_lock = threading.Lock()
_registry: dict[str, "Session"] = {}
_broken: dict[str, str] = {}


class ComponentError(RuntimeError):
    """组件侧的业务错误（`ok=false`）或基础设施错误（超时、进程死）。

    `code` 与 HTTP 层的错误码同构，前端按它查文案；`COMPONENT_MISSING` 由调用方
    （`components.call`）在"根本没有入口"时抛出，不经这里。
    """

    def __init__(self, code: str, message: str, detail: str = ""):
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)


class _Dead(RuntimeError):
    """进程没了（读到 EOF / 管道断）。"""


def _pump(stream, sink: queue.Queue) -> None:
    try:
        for line in stream:
            line = line.strip()
            if line:
                sink.put(line)
    except Exception:                          # noqa: BLE001 - 进程被杀时读会断
        pass
    finally:
        sink.put(None)                         # EOF：让等待方立刻知道人没了


def _pump_log(cid: str, stream) -> None:
    """组件 stderr → 应用日志。诊断时按 `[embed]` 过滤，别开第二个日志文件。"""
    try:
        for line in stream:
            line = line.rstrip()
            if line:
                log.warning("[%s] %s", cid, line)
    except Exception:                          # noqa: BLE001
        pass


class Session:
    def __init__(self, cid: str, argv: list[str]):
        self.cid = cid
        self.argv = argv
        self.proc: subprocess.Popen | None = None
        self.lines: queue.Queue | None = None
        self.lock = threading.Lock()
        self.seq = 0
        self.last_used = 0.0

    # 启动 / 收摊 ──
    def spawn(self) -> None:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"     # 子进程按 utf-8 读写，别跟着系统 GBK 走
        env["PYTHONUNBUFFERED"] = "1"
        log.info("启动组件进程 %s：%s", self.cid, Path(self.argv[0]).name)
        self.proc = subprocess.Popen(
            self.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",                 # 不给 encoding 会用 cp936，中文必乱码
            errors="replace",
            bufsize=1,                        # 行缓冲：协议是一行一个 JSON
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
        self.lines = queue.Queue()
        threading.Thread(target=_pump, args=(self.proc.stdout, self.lines), daemon=True).start()
        threading.Thread(target=_pump_log, args=(self.cid, self.proc.stderr), daemon=True).start()

    def alive(self) -> bool:
        if self.proc is None or self.proc.poll() is not None:
            return False
        if time.monotonic() - self.last_used > IDLE_EXIT:
            self.stop()                        # 空转自杀
            return False
        return True

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.kill()
            # kill() 只发信号；Windows 上要 wait() 才真回收句柄。
            # 不等的话紧接着 poll() 还是 None —— 调用方会误以为"还活着"，
            # 卸载组件时也容易撞到"文件被占用"。
            proc.wait(timeout=5)
        except Exception:                      # noqa: BLE001 - 已经死了 / 等超时
            pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:                  # noqa: BLE001
                pass

    # 收发 ──
    def request(self, op: str, payload: dict, on_progress, timeout: float) -> dict:
        assert self.lines is not None and self.proc is not None
        self.seq += 1
        rid = self.seq
        try:
            self.proc.stdin.write(json.dumps({"id": rid, "op": op, **payload},
                                             ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except Exception as exc:  # noqa: BLE001 - 管道断了
            raise _Dead(str(exc)) from exc
        self.last_used = time.monotonic()
        deadline = self.last_used + timeout
        while True:
            msg = self._read(deadline)
            if msg.get("id") != rid:           # 串行处理，理论上不该出现
                log.debug("组件 %s 回了个不配对的 id=%s", self.cid, msg.get("id"))
                continue
            if msg.get("event") == "progress":
                if on_progress:
                    on_progress(int(msg.get("pct") or 0))
                continue
            if not msg.get("ok"):
                raise ComponentError(str(msg.get("code") or "COMPONENT_FAILED"),
                                     str(msg.get("message") or "组件执行失败"))
            return msg

    def _read(self, deadline: float) -> dict:
        remain = deadline - time.monotonic()
        if remain <= 0:
            raise TimeoutError("组件响应超时")
        try:
            line = self.lines.get(timeout=remain)
        except queue.Empty:
            raise TimeoutError("组件响应超时") from None
        if line is None:
            raise _Dead("组件进程已退出")
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            log.warning("组件 %s 的 stdout 混进非协议内容：%s", self.cid, line[:120])
            return self._read(deadline)


# ── 对外 ────────────────────────────────────────────────
def call(cid: str, argv: list[str], op: str, payload: dict,
         on_progress=None, timeout: float = 120.0, no_retry: bool = False) -> dict:
    """发一条请求，等结果。崩溃时重启一次，连续两次失败标记为「异常」。"""
    with _registry_lock:
        sess = _registry.get(cid)
        if sess is None or sess.argv != argv:
            sess = Session(cid, argv)
            _registry[cid] = sess
    with sess.lock:
        for attempt in range(1, MAX_FAILURES + 1):
            try:
                if not sess.alive():
                    sess.spawn()
                result = sess.request(op, payload, on_progress, timeout)
                _broken.pop(cid, None)
                return result
            except ComponentError:
                raise                          # 组件自己报了错：重启也还是这个错
            except Exception as exc:  # noqa: BLE001 - 超时 / 进程死 / 管道断
                sess.stop()
                log.warning("组件 %s 调用失败（%s），第 %s 次", cid, type(exc).__name__, attempt)
                if no_retry or attempt >= MAX_FAILURES:
                    _broken[cid] = type(exc).__name__
                    raise ComponentError(
                        "COMPONENT_FAILED",
                        "组件没响应，可以重启应用或在设置里重新安装",
                        type(exc).__name__,
                    ) from exc
    raise ComponentError("COMPONENT_FAILED", "组件调用失败")      # 理论不可达


def is_broken(cid: str) -> bool:
    return cid in _broken


def clear_broken(cid: str) -> None:
    _broken.pop(cid, None)


def stop(cid: str) -> None:
    with _registry_lock:
        sess = _registry.get(cid)
    if sess is not None:
        with sess.lock:
            sess.stop()


def stop_all() -> None:
    """主进程退出前调用。留孤儿进程会锁住 `components/<id>/`，卸载时删不掉。"""
    with _registry_lock:
        sessions = list(_registry.values())
        _registry.clear()
    for sess in sessions:
        with sess.lock:
            sess.stop()
