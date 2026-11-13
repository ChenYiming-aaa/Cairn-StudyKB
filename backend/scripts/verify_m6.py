"""M6 验收脚本（Part 1：设置链路 / 路由 / 探测）。

用法：cd backend && uv run python scripts/verify_m6.py [--keep]
退出码：0 全绿 / 1 有用例失败

覆盖（对应 `docs/dev/milestones/M6-设置与个性化.md` §4 T6.9 的前六条）：
  1. `GET /api/settings` 不含任何密钥字段，只有 `has_key`
  2. `PATCH /api/settings` 非法 theme / mode / provider / 任务名 → 400 `SETTINGS_INVALID`
  3. `PATCH` 合法值往返一致；缺省即合并；文件损坏自动备份；手改文件即时生效
  4. `settings/probe` 缺 base_url → 400；错 Key → `ok=false` 且响应不含 Key；
     正常服务 → 列出模型与延迟
  5. `settings/llm` 写入后 `has_key=true`，`.env` 里确有其键，**日志里没有值**
  6. 改任务模型后 `llm_call_log.model` 与所选一致；`supports_effort` 决定
     `reasoning_effort` 是否进请求体；服务拒绝该字段时自动去掉重试一次

  7. 6 套主题 × 明暗的 CSS 变量齐全可解析、对比度达标、深色底六套互不相同；
     首屏防白闪的 boot 脚本在、`frontend/src` 里没有写死颜色
     （主题这块的数学在 `tools/check_contrast.py`，这里直接复用，不抄第二份）

**不联网**：起一个本机 mock provider（`/models`、`/chat/completions`），
所有 LLM 请求都打它 —— 验收脚本依赖外网就等于没验收。
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-m6-"))
os.environ["DATA_DIR"] = str(TMP)          # 必须早于 import app：get_settings() 首次调用即缓存
os.environ["VECTOR_ENABLED"] = "0"
# S-3：验收必须在「配置只来自这个临时目录」的前提下跑，否则项目根的 `.env`
# 会把真机 Key 灌进进程环境 —— 那样"没有 Key 会怎样"永远验不出来。
os.environ["CAIRN_ENV_STRICT"] = "1"
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("ALT_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import config_audit, get_settings, load_settings, reload_settings  # noqa: E402
from app.db.conn import get_conn  # noqa: E402
from app.db.migrate import SCHEMA_VERSION, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import llm, prefs  # noqa: E402


def _load_theme_tool():
    """把 `tools/check_contrast.py` 当模块加载：配色数学只有一份，不在这里重写。"""
    path = ROOT / "tools" / "check_contrast.py"
    spec = importlib.util.spec_from_file_location("check_contrast", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cc = _load_theme_tool()

GOOD_KEY = "sk-verify-m6-good-0001"
BAD_KEY = "sk-verify-m6-bad-9999"
RESULTS: list[tuple[bool, str]] = []
SEEN: list[dict] = []          # mock provider 收到的请求体，用于断言 payload

# ── 本机 mock provider ────────────────────────────────────────


class MockProvider(BaseHTTPRequestHandler):
    """最小的 OpenAI 兼容服务。三种路径各演一件事：

    | 路径 | 行为 |
    |---|---|
    | `/v1/models` | 200 + 两个模型；Key 不对则 401 |
    | `/v1/chat/completions` | 200 + 一句固定回答，请求体进 `SEEN` |
    | `/strict/chat/completions` | 带 `reasoning_effort` 就 400（模拟不认该字段的网关） |
    | `/nomodels/...` | `/models` 返 404，对话可用（模拟只给了 chat 接口的服务） |
    """

    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):      # 别把 access log 打到验收输出里
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {GOOD_KEY}"

    def do_GET(self):                    # noqa: N802 - BaseHTTPRequestHandler 的约定
        if self.path.endswith("/models"):
            if self.path.startswith("/nomodels"):
                self._send(404, {"error": {"message": "not found"}})
                return
            if not self._auth_ok():
                self._send(401, {"error": {"message": "invalid api key"}})
                return
            self._send(200, {"object": "list", "data": [
                {"id": "mock-small", "object": "model"},
                {"id": "mock-large", "object": "model"},
            ]})
            return
        self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):                   # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        SEEN.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})

        if not self._auth_ok():
            self._send(401, {"error": {"message": "invalid api key"}})
            return
        if self.path.startswith("/strict") and "reasoning_effort" in body:
            self._send(400, {"error": {
                "message": "unsupported parameter: reasoning_effort",
                "type": "invalid_request_error",
            }})
            return
        self._send(200, {
            "id": "mock-1",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "收到"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        })


def start_mock() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockProvider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


# ── 断言小工具 ───────────────────────────────────────────────


def check(name: str, ok: bool, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append((ok, name))
    print(f"    [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def skip(name: str, why: str) -> None:
    """环境不满足时明确跳过（不计入通过数，也不伪装成 PASS）。"""
    print(f"    [SKIP] {name} — {why}")


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 46 - len(title)))


def walk_keys(node, path=""):
    """递归列出所有键名，用来断言「响应里没有 api_key 这类字段」。"""
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}".lstrip(".")
            yield from walk_keys(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_keys(value, f"{path}[{index}]")


def log_text() -> str:
    """把所有日志文件拼起来：Key 泄漏只会在日志里，不在响应里。"""
    chunks = []
    for path in sorted((TMP / "logs").glob("*.log")):
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n".join(chunks)


def last_log_row():
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT agent, model, ok, error_msg, effort, effort_dropped "
            "FROM llm_call_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()


# ── 主体 ─────────────────────────────────────────────────────


def main() -> int:
    init_db()
    server, base = start_mock()
    print(f"    mock provider: {base}")
    try:
        with TestClient(app) as client:
            # ── 1. 读取不含密钥 ────────────────────────────────
            step("1. GET /api/settings 不泄漏密钥")

            r = client.get("/api/settings")
            body = r.json()
            check("200 且形状完整",
                  r.status_code == 200
                  and set(body) >= {"llm", "appearance", "env_file"},
                  ", ".join(sorted(body)))
            keys = list(walk_keys(body))
            check("没有任何 *api_key* 字段", not [k for k in keys if "api_key" in k],
                  str([k for k in keys if "api_key" in k]))
            check("不暴露 key_env（变量名也是信息）", "key_env" not in " ".join(keys))
            # `has_key` 只说明「配没配」，真值取决于跑脚本这台机器的 `.env`，
            # 所以这里断言类型而不是断言 false（否则验收结果随环境漂移）
            has_keys = [body["llm"]["providers"][pid]["has_key"]
                        for pid in body["llm"]["providers"]]
            check("provider 只给 has_key 布尔值",
                  all(isinstance(v, bool) for v in has_keys), str(has_keys))
            check("四个任务都在", set(body["llm"]["tasks"]) == set(prefs.AGENTS),
                  ", ".join(sorted(body["llm"]["tasks"])))
            check("响应正文里没有 Key 前缀", "sk-" not in r.text)
            check("会告诉前端『配置只来自数据目录』（S-3）",
                  body.get("config", {}).get("ok") is True
                  and body["config"]["legacy_keys"] == [],
                  str(body.get("config")))

            # ── 2. 非法值 ──────────────────────────────────────
            step("2. PATCH 非法值一律 400 SETTINGS_INVALID")

            cases = [
                ("未知主题", {"appearance": {"theme": "nope"}}),
                ("未知明暗", {"appearance": {"mode": "twilight"}}),
                ("未知字号", {"appearance": {"font_size": "huge"}}),
                ("未知 provider", {"llm": {"providers": {"openai": {}}}}),
                ("未知任务名", {"llm": {"tasks": {"translator": {"model": "x"}}}}),
                ("未知思考强度", {"llm": {"tasks": {"asker": {"effort": "max"}}}}),
                ("非法 base_url", {"llm": {"providers": {"custom": {"base_url": "ftp://x"}}}}),
            ]
            for label, payload in cases:
                resp = client.patch("/api/settings", json=payload)
                err = resp.json().get("error", {})
                check(f"{label} → 400 SETTINGS_INVALID",
                      resp.status_code == 400 and err.get("code") == "SETTINGS_INVALID",
                      f"{resp.status_code} {err.get('detail')}")
            check("空 body 也拒", client.patch("/api/settings", json={}).status_code == 400)

            # 非法写入不能污染文件
            check("被拒之后配置仍是默认值",
                  client.get("/api/settings").json()["appearance"]["theme"] == "paper")

            # ── 3. 合法往返 + 合并 / 损坏 / 手改 ───────────────
            step("3. PATCH 合法值往返与容错")

            resp = client.patch("/api/settings",
                               json={"appearance": {"theme": "study", "mode": "dark",
                                                    "font_size": "lg"}})
            got = resp.json()["appearance"]
            check("PATCH 返回更新后的全量",
                  got == {"theme": "study", "mode": "dark", "font_size": "lg"}, str(got))
            again = client.get("/api/settings").json()["appearance"]
            check("再读回一致", again == got, str(again))

            client.patch("/api/settings", json={"appearance": {"theme": "docs"}})
            after = client.get("/api/settings").json()
            check("只改一个键时其余键保留（缺省即合并）",
                  after["appearance"]["mode"] == "dark"
                  and after["appearance"]["font_size"] == "lg", str(after["appearance"]))
            check("只改外观不动任务矩阵",
                  set(after["llm"]["tasks"]) == set(prefs.AGENTS))

            settings_file = TMP / "settings.json"
            check("settings.json 落在数据目录", settings_file.exists(), str(settings_file))

            settings_file.write_text("{ 这不是 JSON", encoding="utf-8")
            time.sleep(0.02)
            prefs.invalidate()
            recovered = prefs.load()
            bad = list(TMP.glob("settings.json.bad-*"))
            check("坏文件被备份成 settings.json.bad-*", len(bad) == 1, str([p.name for p in bad]))
            check("坏文件之后回落默认值", recovered["appearance"]["theme"] == "paper",
                  str(recovered["appearance"]))

            # 坏文件已被挪走，这里重写一份"用户手改过的"文件
            settings_file.write_text(
                json.dumps({"appearance": {"theme": "teal"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            time.sleep(0.02)
            prefs.invalidate()

            hand = json.loads(settings_file.read_text(encoding="utf-8"))
            hand["appearance"]["theme"] = "teal"
            settings_file.write_text(json.dumps(hand, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.02)
            prefs.invalidate()
            check("手改 JSON 后下一次读取即生效（mtime 缓存）",
                  client.get("/api/settings").json()["appearance"]["theme"] == "teal",
                  client.get("/api/settings").json()["appearance"]["theme"])

            # ── 4. 探测 ────────────────────────────────────────
            step("4. settings/probe")

            resp = client.post("/api/settings/probe", json={"provider": "custom"})
            err = resp.json().get("error", {})
            check("缺 base_url → 400 SETTINGS_INVALID",
                  resp.status_code == 400 and err.get("code") == "SETTINGS_INVALID",
                  f"{resp.status_code} {err.get('detail')}")
            check("缺 base_url 的错误指明是哪个键",
                  "base_url" in (err.get("detail") or ""), str(err.get("detail")))

            resp = client.post("/api/settings/probe",
                               json={"provider": "custom", "base_url": base, "api_key": BAD_KEY})
            bad_probe = resp.json()
            check("错 Key → 200 但 ok=false", resp.status_code == 200 and bad_probe["ok"] is False,
                  str(bad_probe.get("error_code")))
            check("错 Key 的错误码是人能懂的（LLM_NO_KEY）",
                  bad_probe.get("error_code") == "LLM_NO_KEY", str(bad_probe.get("error_code")))
            check("错 Key 的响应里没有 Key 明文", BAD_KEY not in resp.text)

            before_probe = settings_file.read_bytes()
            before_models = client.get("/api/settings").json()[
                "llm"]["providers"]["custom"]["models"]

            resp = client.post("/api/settings/probe",
                               json={"provider": "custom", "base_url": f"{base}/v1",
                                     "api_key": GOOD_KEY})
            good_probe = resp.json()
            check("正常服务 → ok=true + 模型列表按字母序",
                  good_probe["ok"] and good_probe["models"] == ["mock-large", "mock-small"],
                  str(good_probe.get("models")))
            check("带延迟（毫秒，非负）", isinstance(good_probe.get("latency_ms"), int)
                  and good_probe["latency_ms"] >= 0, str(good_probe.get("latency_ms")))
            # S-1：探测是只读操作。以前这里会顺手把地址与模型列表写进配置，
            # 用户"只是试试通不通"却被改了配置 —— 这条断言就是防它回来。
            check("探测不改模型列表（S-1：读的不写盘）",
                  client.get("/api/settings").json()["llm"]["providers"]["custom"]["models"]
                  == before_models,
                  str(client.get("/api/settings").json()
                      ["llm"]["providers"]["custom"]["models"]))
            check("探测不动 settings.json（文件字节完全没变）",
                  settings_file.read_bytes() == before_probe,
                  f"{len(before_probe)} → {len(settings_file.read_bytes())} 字节")

            resp = client.post("/api/settings/probe",
                               json={"provider": "custom", "base_url": f"{base}/nomodels",
                                     "api_key": GOOD_KEY, "model": "mock-small"})
            nomodels = resp.json()
            check("服务没有 /models → LLM_MODELS_UNSUPPORTED 但仍判可用",
                  nomodels["ok"] and nomodels["error_code"] == "LLM_MODELS_UNSUPPORTED",
                  str(nomodels))

            resp = client.post("/api/settings/probe", json={"provider": "zzz"})
            check("未知 provider → 400", resp.status_code == 400)

            # ── 5. 写 Key ──────────────────────────────────────
            step("5. settings/llm 落盘与热加载")

            resp = client.post("/api/settings/llm", json={
                "provider": "custom", "api_key": GOOD_KEY, "base_url": f"{base}/v1",
            })
            saved = resp.json()
            check("200 且回了 saved/env_file/settings",
                  resp.status_code == 200
                  and set(saved) >= {"saved", "env_file", "settings"}, str(resp.status_code))
            check("响应里没有 Key 明文", GOOD_KEY not in resp.text)
            check("写完之后 has_key=true（不需要重启）",
                  saved["settings"]["llm"]["providers"]["custom"]["has_key"] is True)
            check("base_url 进了 settings.json",
                  saved["settings"]["llm"]["providers"]["custom"]["base_url"] == f"{base}/v1",
                  saved["settings"]["llm"]["providers"]["custom"]["base_url"])

            env_text = Path(saved["env_file"]).read_text(encoding="utf-8")
            check(".env 里有该 provider 的键", "ALT_API_KEY" in env_text)
            check(".env 里确实是新值", GOOD_KEY in env_text)
            check("日志里没有 Key（红线 7）", GOOD_KEY not in log_text())

            resp = client.post("/api/settings/llm",
                               json={"provider": "custom", "api_key": "", "base_url": ""})
            check("空提交 → 400 ENV_NOTHING_TO_SAVE",
                  resp.status_code == 400
                  and resp.json()["error"]["code"] == "ENV_NOTHING_TO_SAVE")

            # ── 6. 按任务路由 + 日志 + effort ──────────────────
            step("6. 按任务路由 / effort 策略 / 400 兜底")

            client.patch("/api/settings", json={"llm": {"providers": {"custom": {
                "base_url": f"{base}/v1", "supports_effort": False, "models": ["mock-large", "mock-small"],
            }}}})
            client.patch("/api/settings", json={"llm": {"tasks": {"organizer": {
                "provider": "custom", "model": "mock-small", "effort": "high",
            }}}})

            SEEN.clear()
            answer = llm.chat([{"role": "user", "content": "ping"}], agent="organizer")
            check("按任务路由：调用成功", answer == "收到", answer)
            check("custom 声明不支持 effort → 请求体里没有 reasoning_effort",
                  SEEN and "reasoning_effort" not in SEEN[-1]["body"],
                  str(sorted(SEEN[-1]["body"])) if SEEN else "没收到请求")
            row = last_log_row()
            check("llm_call_log 记的是**实际用的**模型",
                  row and row[1] == "mock-small", str(row))
            check("llm_call_log 记的是这个 agent", row and row[0] == "organizer", str(row))
            # S-2：设了 high 但 provider 不支持 → 没发出去，且必须留痕
            check("不支持 effort → effort 记 NULL（不记设置值）",
                  row and row[4] is None, str(row[4]))
            check("不支持 effort → effort_dropped=1（本来要发却没发）",
                  row and row[5] == 1, str(row[5]))

            client.patch("/api/settings", json={"llm": {"providers": {"custom": {
                "supports_effort": True}}}})
            SEEN.clear()
            llm.chat([{"role": "user", "content": "ping"}], agent="organizer")
            check("声明支持 effort → reasoning_effort 进请求体",
                  SEEN and SEEN[-1]["body"].get("reasoning_effort") == "high",
                  str(SEEN[-1]["body"].get("reasoning_effort")) if SEEN else "没收到请求")
            row = last_log_row()
            check("真的发出去了 → effort 记实际值 high",
                  row and row[4] == "high", str(row[4]))
            check("真的发出去了 → effort_dropped=0", row and row[5] == 0, str(row[5]))

            client.patch("/api/settings", json={"llm": {"tasks": {"organizer": {
                "effort": "none"}}}})
            SEEN.clear()
            llm.chat([{"role": "user", "content": "ping"}], agent="organizer")
            check("effort=none → 整条字段不发（而不是发空串）",
                  SEEN and "reasoning_effort" not in SEEN[-1]["body"],
                  str(sorted(SEEN[-1]["body"])) if SEEN else "没收到请求")
            row = last_log_row()
            check("用户主动关掉 → effort 为 NULL 但 dropped=0（不是「不支持」）",
                  row and row[4] is None and row[5] == 0, str(row[4:6]))

            # 服务拒绝该字段：应当自动去掉重试一次，而不是把 400 甩给用户
            client.patch("/api/settings",
                         json={"llm": {"providers": {"custom": {"base_url": f"{base}/strict"}}}})
            client.patch("/api/settings",
                         json={"llm": {"tasks": {"organizer": {"effort": "low"}}}})
            SEEN.clear()
            try:
                answer = llm.chat([{"role": "user", "content": "ping"}], agent="organizer")
                ok_retry = answer == "收到"
            except llm.LLMError as exc:
                ok_retry = False
                answer = f"{exc.code} {exc.detail}"
            check("400 拒绝 reasoning_effort → 自动去掉重试一次并成功", ok_retry, answer)
            check("重试前确实带过该字段（不是一开始就没发）",
                  len(SEEN) == 2 and "reasoning_effort" in SEEN[0]["body"],
                  f"{len(SEEN)} 次请求")
            check("重试那次没带该字段",
                  len(SEEN) == 2 and "reasoning_effort" not in SEEN[1]["body"])
            row = last_log_row()
            check("被 400 拒掉那次：effort 记 NULL + dropped=1",
                  row and row[4] is None and row[5] == 1, str(row[4:6]))

            # 四个任务各自的模型互不影响
            client.patch("/api/settings", json={"llm": {"tasks": {
                "asker": {"provider": "custom", "model": "mock-large", "effort": "low"},
                "quizzer": {"provider": "custom", "model": "mock-small", "effort": "low"},
            }}})
            seen_models = {}
            for agent in ("asker", "quizzer"):
                SEEN.clear()
                llm.chat([{"role": "user", "content": "ping"}], agent=agent)
                seen_models[agent] = SEEN[-1]["body"].get("model") if SEEN else None
            check("不同任务走不同模型",
                  seen_models == {"asker": "mock-large", "quizzer": "mock-small"},
                  str(seen_models))

            # Key 缺了要指明是哪个 provider：把 asker 指到 custom，再把 Key 从
            # `.env` 与进程环境里一起抹掉（`reload_settings` 会从 `.env` 再灌回来）
            env_path = Path(get_settings().env_file)
            kept = [ln for ln in env_path.read_text(encoding="utf-8").splitlines()
                    if not ln.strip().startswith("ALT_API_KEY")]
            env_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
            os.environ.pop("ALT_API_KEY", None)
            reload_settings()
            client.patch("/api/settings",
                         json={"llm": {"providers": {"custom": {"base_url": f"{base}/v1"}},
                                       "tasks": {"asker": {"provider": "custom"}}}})
            try:
                llm.chat([{"role": "user", "content": "ping"}], agent="asker")
                code, message = "", ""
            except llm.LLMError as exc:
                code, message = exc.code, exc.message
            check("缺 Key → LLM_NO_KEY", code == "LLM_NO_KEY", code)
            check("缺 Key 的提示点名是哪个 provider", "OpenAI 兼容" in message, message)

            # ── 7. 主题（T6.7）─────────────────────────────────
            step("7. 六套主题 × 明暗")

            tokens_css = (ROOT / "frontend/src/styles/tokens.css").read_text(encoding="utf-8")
            problems = cc.check(tokens_css)
            check("tokens.css：6 套 × 明暗令牌齐全、对比度全达标",
                  not problems, "；".join(problems[:3]))

            parsed = cc.parse_tokens(tokens_css)
            check("六个主题块都在（浅色 + 深色 = 12 块）",
                  len(parsed) == len(cc.THEME_ORDER) * 2, str(sorted(parsed)))

            dark_bgs = {tid: parsed[(tid, "dark")].get("bg-0") for tid in cc.THEME_ORDER}
            check("深色底六套互不相同（否则暗色下分不出主题）",
                  len(set(dark_bgs.values())) == len(dark_bgs), str(dark_bgs))
            check("每套都有 on-primary（teal 是黑字，不能写死白）",
                  all(parsed[(tid, mode)].get("on-primary") for tid in cc.THEME_ORDER
                      for mode in ("light", "dark")))

            index_html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
            boot = ROOT / "frontend/public/theme-boot.js"
            check("首屏防白闪：index.html 在挂载前引了 theme-boot.js",
                  'src="/theme-boot.js"' in index_html, index_html[:80])
            check("theme-boot.js 存在且读的键与 useTheme 一致",
                  boot.exists()
                  and all(k in boot.read_text(encoding="utf-8")
                          for k in ("cairn.theme", "cairn.mode", "cairn.fs")),
                  str(boot))

            # 组件里写死颜色 → 暗色会「白底白字」。这条断言就是防它复发。
            hardcoded = []
            for path in (ROOT / "frontend/src").rglob("*"):
                if path.suffix not in {".vue", ".css", ".js"}:
                    continue
                if path.name == "tokens.css":
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for match in re.finditer(r"#[0-9a-fA-F]{3,8}\b", text):
                    hardcoded.append(f"{path.relative_to(ROOT)}:{match.group(0)}")
            check("组件/样式里没有写死颜色（全部走 --c-* 令牌）",
                  not hardcoded, "；".join(hardcoded[:5]))

            # ── 8. 迁移 v2 → v3（S-2）───────────────────────────
            step("8. 老库（v2）一路升到当前版本：加列不丢数据")

            # 桩只要「v2 那一年的形态」：llm_call_log 老两列 + v4 迁移要 ALTER 的两张表。
            # **为什么还得有 knowledge_item / question**：T9.2 加了 v4 之后链条变成
            # v2→v3→v4→v5，v4 会对这两张表 `ALTER TABLE ... ADD COLUMN`；
            # 桩里没有就报 `no such table`（2026-11-13 全量回归第一次捞到这条）。
            # 只写迁移会碰的列，其余列不重要 —— 迁移只看表在不在、列在不在。
            legacy = TMP / "legacy-v2.db"
            raw = sqlite3.connect(str(legacy))
            try:
                raw.executescript("""
                    CREATE TABLE llm_call_log (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      agent TEXT NOT NULL, model TEXT NOT NULL,
                      prompt_tokens INTEGER, completion_tokens INTEGER,
                      reasoning_tokens INTEGER, duration_ms INTEGER,
                      ok INTEGER NOT NULL, error_msg TEXT, created_at TEXT NOT NULL
                    );
                    INSERT INTO llm_call_log (agent, model, ok, created_at)
                    VALUES ('asker', 'old-model', 1, '2026-01-01T00:00:00');

                    CREATE TABLE knowledge_item (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      title TEXT NOT NULL DEFAULT '',
                      raw_content TEXT NOT NULL DEFAULT '',
                      category TEXT, tags TEXT, summary TEXT, key_points TEXT,
                      structured_note TEXT,
                      status TEXT NOT NULL DEFAULT 'pending',
                      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    INSERT INTO knowledge_item (title, raw_content, created_at, updated_at)
                    VALUES ('老内容', 'v2 时代写下的正文', '2026-01-01', '2026-01-01');

                    CREATE TABLE question (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      question TEXT NOT NULL, options TEXT, answer TEXT,
                      created_at TEXT NOT NULL
                    );
                    PRAGMA user_version=2;
                """)
                raw.commit()
            finally:
                raw.close()

            init_db(legacy)
            old = sqlite3.connect(str(legacy))
            try:
                version = old.execute("PRAGMA user_version").fetchone()[0]
                cols = {row[1] for row in old.execute("PRAGMA table_info(llm_call_log)")}
                kept = old.execute(
                    "SELECT model, effort, effort_dropped FROM llm_call_log"
                ).fetchall()
                tables = {row[0] for row in old.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                item_cols = {row[1]: row[4] for row in old.execute(
                    "PRAGMA table_info(knowledge_item)")}
                page_cols = {row[1] for row in old.execute("PRAGMA table_info(item_page)")}
                q_cols = {row[1] for row in old.execute("PRAGMA table_info(question)")}
                old_item = old.execute(
                    "SELECT title, kind, workspace_id, file_id FROM knowledge_item"
                ).fetchall()
            finally:
                old.close()
            check("升级后 user_version = 当前版本", version == SCHEMA_VERSION, str(version))
            check("两个新列都加上了",
                  {"effort", "effort_dropped"} <= cols, str(sorted(cols)))
            check("老数据没丢，新列按 NULL / 0 回填",
                  kept == [("old-model", None, 0)], str(kept))
            # 后面几版（v4 / v5）也真的跑过了：别只看版本号跳没跳
            check("v4 建的三张表都在",
                  {"workspace", "item_file", "item_page"} <= tables, str(sorted(tables)))
            check("v4 给 knowledge_item 补的三列在，kind 默认 material",
                  {"kind", "workspace_id", "file_id"} <= set(item_cols)
                  and item_cols["kind"] == "'material'", str(item_cols))
            check("v5 给 item_page 补的 line_conf 在", "line_conf" in page_cols,
                  str(sorted(page_cols)))
            check("v4 给 question 补的 origin / number 在",
                  {"origin", "number"} <= q_cols, str(sorted(q_cols)))
            check("老内容一条不丢，且按默认值落成「普通资料 / 未归类 / 无原件」",
                  old_item == [("老内容", "material", None, None)], str(old_item))

            # ── 9. 严格模式（S-3）──────────────────────────────
            step("9. 配置来源可检查：不再从老地方拿 Key")

            audit = config_audit()
            check("严格模式确实生效", audit["strict"] is True, str(audit["strict"]))
            check("没有从老地方拿过配置（这就是那条必须被断言的东西）",
                  audit["ok"] and audit["legacy_keys"] == [], str(audit))
            check("审计结果带人话（看得见才会被检查）", bool(audit.get("hint")),
                  audit.get("hint"))

            env_resp = client.get("/api/env/check").json()
            check("/api/env/check 也带 config 块",
                  env_resp.get("config", {}).get("ok") is True
                  and env_resp["config"]["legacy_file"] is None,
                  str(env_resp.get("config")))

            # 反证：把严格模式关掉，同一份布局会从项目根 `.env` 补值 —— 这正是 S-3 的病。
            # 只在这一步临时关，且把污染的环境变量全部还原。
            repo_env = ROOT / ".env"
            repo_text = repo_env.read_text(encoding="utf-8") if repo_env.exists() else ""
            if "LLM_API_KEY" in repo_text:
                before_keys = set(os.environ)
                saved_strict = os.environ.pop("CAIRN_ENV_STRICT", None)
                os.environ.pop("LLM_API_KEY", None)
                try:
                    loose = load_settings()
                    check("反证：不设严格模式时确实会从项目根 .env 补值",
                          "LLM_API_KEY" in loose.env_legacy_keys,
                          str(loose.env_legacy_keys))
                    check("反证：那次补充还把值写进了 os.environ（所以要修根）",
                          bool((os.environ.get("LLM_API_KEY") or "").strip()))
                finally:
                    for key in set(os.environ) - before_keys:
                        os.environ.pop(key, None)
                    if saved_strict is not None:
                        os.environ["CAIRN_ENV_STRICT"] = saved_strict
                    reload_settings()
                check("反证做完，进程环境已还原且审计回到干净状态",
                      config_audit()["legacy_keys"] == [],
                      str(config_audit()["legacy_keys"]))
            else:
                skip("反证：不设严格模式时会从项目根 .env 补值",
                     "仓库没有 .env（本机开发才有），换台机器也是同一个结论")
    finally:
        server.shutdown()
        reload_settings()

    total = len(RESULTS)
    passed = sum(1 for ok, _ in RESULTS if ok)
    print(f"\n{'=' * 56}\n  {passed}/{total} 通过")
    if passed != total:
        print("  失败用例：")
        for ok, name in RESULTS:
            if not ok:
                print(f"    - {name}")
    print(f"  临时数据目录：{TMP}" + ("" if "--keep" in sys.argv else "（可删）"))
    return 0 if passed == total else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                  # noqa: BLE001 - 验收脚本要给出完整栈
        traceback.print_exc()
        sys.exit(1)
