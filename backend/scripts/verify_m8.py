"""M8 验收脚本（分组长大的那种）。

用法：
    cd backend && uv run python scripts/verify_m8.py
    cd backend && uv run python scripts/verify_m8.py --only protocol   # 只跑某一组

退出码：0 全绿 / 1 有用例失败 / 2 环境不满足

覆盖分组（对应 `M8-补充记录.md` §1.1 的六层）：
  §1 protocol   T8.0 组件清单 / 三态可用性 / 协议往返（真子进程）/ 缺组件降级 / HTTP 不 500
  §2 slim       T8.1 主包瘦身（体积与 excludes）—— 待 L1 落地后填
  §3 install    T8.3 下载中心（安装 / 卸载 / 续传 / 校验）—— 待 L3 落地后填
  §4 update     T8.5 更新器与版本元数据 —— 待 L4 落地后填

**不联网、不调模型**：组件用的是空实现（假向量），后端起在 127.0.0.1 的临时端口上。
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import traceback
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


# ── 环境 ────────────────────────────────────────────────────
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


GROUPS = {"protocol": group_protocol}


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
