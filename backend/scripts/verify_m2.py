"""T2.10 验收脚本：一次跑完 M2 §5 DoD 的机器可验部分。

用法：cd backend && uv run python scripts/verify_m2.py [--keep]
退出码：0 全绿 / 1 有用例失败

**不打真实站点**（2026-11-06 交接建议）：网页抓取与视频转录都用
`set_fetcher(假实现)` / `set_transcriber(假实现)` 注入，
三种失败场景因此可重复、秒级完成，也不会给外部站点留下请求。
真实网络那一遍在 HANDOFF 里单独记过（真 uvicorn + 真阮一峰文章 + 真视频）。

全程使用临时 DATA_DIR，不碰 data/data.db，末尾清理。
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import replace
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-m2-"))
os.environ["DATA_DIR"] = str(TMP)  # 必须早于 import app：get_settings() 首次调用即缓存
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402

import app.config as config_mod  # noqa: E402
import app.db.conn as conn_mod  # noqa: E402
from app.main import app  # noqa: E402
from app.services import env_probe, fetcher, transcriber  # noqa: E402
from app.services.fetch_errors import FetchError  # noqa: E402
from app.services.fetcher import BaseFetcher, FetchedPage  # noqa: E402
from app.services.tasks import recover_stale_tasks  # noqa: E402
from app.services.transcriber import BaseTranscriber, Transcript  # noqa: E402

DB = TMP / "data.db"
RESULTS: list[tuple[bool, str]] = []

PAGE_TEXT = (
    "番茄工作法的关键在于把注意力留在当前这一轮，而不是反复估算剩余时间。"
    "计时器给出的不是压力，而是一个边界：边界之内只做一件事。"
) * 12


def check(name: str, ok: bool, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append((ok, name))
    print(f"    [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 46 - len(title)))


def sql(query: str, args: tuple = ()) -> list:
    with sqlite3.connect(DB, timeout=10) as conn:
        return conn.execute(query, args).fetchall()


def wait_task(client: TestClient, task_id: str, timeout: int = 120,
              seen: list | None = None) -> dict:
    """等任务落定；顺带把每次轮询看到的 (progress, stage) 记进 seen。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        point = (task.get("progress"), task.get("stage"))
        if seen is not None and point != last:
            seen.append(point)
            last = point
        if task.get("status") in ("done", "failed"):
            return task
        time.sleep(0.08)
    return {"status": "timeout", "error_code": "TASK_TIMEOUT"}


# ── 假实现（脚本专用）──────────────────────────────────────


class FakeFetcher(BaseFetcher):
    """默认吐一段固定正文；`fail_code` 非空时抛对应错误码。"""

    def __init__(self) -> None:
        self.fail_code = ""
        self.text = PAGE_TEXT
        self.title = "假网页标题"
        self.delay = 0.0
        self.calls = 0

    def fetch(self, url: str) -> FetchedPage:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail_code:
            raise FetchError(self.fail_code, detail="fake")
        return FetchedPage(url=url, title=self.title, text=self.text)


class FakeTranscriber(BaseTranscriber):
    """按四阶段推一遍进度，然后返回带时间戳的文本或抛错。"""

    def __init__(self) -> None:
        self.fail_code = ""
        self.delay = 0.0

    def transcribe(self, url: str, on_progress=None) -> Transcript:
        report = on_progress or (lambda *_: None)
        report(0, "metadata")
        time.sleep(0.15)
        report(5, "downloading")
        time.sleep(0.15)
        report(30, "transcribing")
        time.sleep(self.delay or 0.25)
        report(70, "transcribing")
        time.sleep(0.1)
        report(95, "transcribing")
        if self.fail_code:
            raise FetchError(self.fail_code, detail="fake")
        return Transcript(url=url, title="假视频标题", text="[00:00] 第一段话\n[00:12] 第二段话",
                          duration=24.0, language="zh", segment_count=2)


fake_fetcher = FakeFetcher()
fake_transcriber = FakeTranscriber()


# ── 各组用例 ────────────────────────────────────────────────


def step_endpoints(client: TestClient) -> None:
    step("1/10 端点登记与基座")
    spec = client.get("/openapi.json").json()
    paths = set(spec["paths"])
    check("POST /api/ingest/video 已登记", "/api/ingest/video" in paths)
    check("POST /api/tasks/{task_id}/retry 已登记", "/api/tasks/{task_id}/retry" in paths)
    check("健康检查正常", client.get("/api/health").json().get("status") == "ok")
    check("services/transcriber 默认实现可构造",
          isinstance(transcriber.YtDlpWhisperTranscriber(), BaseTranscriber))


def step_web_ok(client: TestClient) -> int:
    step("2/10 网页采集成功入库")
    fake_fetcher.__init__()
    resp = client.post("/api/ingest/url", json={"url": "https://example.com/a"})
    body = resp.json()
    check("返回 202 + task_id", resp.status_code == 202 and bool(body.get("task_id")),
          f"{resp.status_code} {body}")
    task = wait_task(client, body["task_id"])
    out = task.get("output_json") or {}
    check("任务 done", task.get("status") == "done", task.get("error_code") or "")
    item_id = out.get("item_id")
    check("output 带 item_id / chunk_count",
          isinstance(item_id, int) and out.get("chunk_count", 0) > 0, str(out))

    rows = sql("SELECT source_type, source_url, title, status, length(raw_content) "
               "FROM knowledge_item WHERE id=?", (item_id,))
    check("落库为 web 且标题/URL 正确",
          rows and rows[0][0] == "web" and rows[0][1] == "https://example.com/a"
          and rows[0][2] == "假网页标题", str(rows))
    check("状态 pending（等整理）", rows and rows[0][3] == "pending")
    check("chunk 已切（source='raw'）",
          sql("SELECT COUNT(*) FROM chunk WHERE item_id=? AND source='raw'", (item_id,))[0][0] > 0)
    check("FTS 能搜到正文", sql(
        "SELECT COUNT(*) FROM chunk_fts WHERE chunk_fts MATCH ?", ("番茄工作法的关键",))[0][0] > 0)
    return item_id


def step_dedupe(client: TestClient, item_id: int) -> None:
    step("3/10 去重与 force")
    before = sql("SELECT COUNT(*) FROM knowledge_item")[0][0]
    resp = client.post("/api/ingest/url", json={"url": "https://example.com/a"})
    body = resp.json()
    check("同 URL → 200 且 task_id=null",
          resp.status_code == 200 and body.get("task_id") is None, str(body))
    check("同 URL 指回已有条目", body.get("existing_item_id") == item_id, str(body))
    check("库中未新增", sql("SELECT COUNT(*) FROM knowledge_item")[0][0] == before)

    # 同内容不同 URL：content_hash 撞库
    resp = client.post("/api/ingest/url", json={"url": "https://example.com/a-copy"})
    task = wait_task(client, resp.json()["task_id"])
    out = task.get("output_json") or {}
    check("同内容不同 URL → duplicated=true",
          task.get("status") == "done" and out.get("duplicated") is True, str(out))
    check("content_hash 撞库指回同一条", out.get("existing_item_id") == item_id, str(out))
    check("同内容未新建条目", sql("SELECT COUNT(*) FROM knowledge_item")[0][0] == before)

    # force：只换正文，人工成果不动
    client.patch(f"/api/knowledge/{item_id}",
                 json={"title": "我手写的标题", "category": "时间管理",
                       "tags": ["番茄钟"], "structured_note": "# 我的笔记\n别覆盖我"})
    fake_fetcher.text = PAGE_TEXT + "（第二次抓到的补充段落，用于确认正文真的被替换）"
    resp = client.post("/api/ingest/url", json={"url": "https://example.com/a", "force": True})
    task = wait_task(client, resp.json()["task_id"])
    out = task.get("output_json") or {}
    check("force → replaced=true 且同一条目",
          out.get("replaced") is True and out.get("item_id") == item_id, str(out))
    row = sql("SELECT title, category, tags, structured_note, note_edited, raw_content, status "
              "FROM knowledge_item WHERE id=?", (item_id,))[0]
    check("正文已替换", "补充段落" in row[5])
    check("标题/分类/标签/笔记未被覆盖",
          row[0] == "我手写的标题" and row[1] == "时间管理"
          and "番茄钟" in row[2] and "别覆盖我" in row[3], str(row[:4]))
    check("note_edited 仍为 1", row[4] == 1)
    check("状态回 pending 等重新整理", row[6] == "pending")


def step_web_failures(client: TestClient) -> None:
    step("4/10 网页失败三类（假实现，不碰真实站点）")
    expect = {
        "FETCH_NOT_FOUND": "exists_not",
        "FETCH_EMPTY": "too_short",
        "FETCH_BLOCKED": "blocked",
    }
    for code, slug in expect.items():
        fake_fetcher.__init__()
        fake_fetcher.fail_code = code
        resp = client.post("/api/ingest/url", json={"url": f"https://example.com/{slug}"})
        task = wait_task(client, resp.json()["task_id"])
        check(f"{code} → 任务 failed", task.get("status") == "failed", task.get("error_code") or "")
        check(f"{code} 错误码落库", task.get("error_code") == code, str(task.get("error_code")))
        check(f"{code} 有中文文案", f"错误" not in (task.get("error_msg") or "")
              and any("\u4e00" <= ch <= "\u9fff" for ch in task.get("error_msg") or ""),
              (task.get("error_msg") or "")[:40])
    check("三类失败都没有建条目",
          sql("SELECT COUNT(*) FROM knowledge_item WHERE source_url LIKE 'https://example.com/%'")[0][0] == 1)


def step_video(client: TestClient) -> None:
    step("5/10 视频转录：四阶段进度 + 时间戳正文")
    fake_transcriber.__init__()
    resp = client.post("/api/ingest/video", json={"url": "https://example.com/v/1", "model": "tiny"})
    body = resp.json()
    check("返回 202 + task_id", resp.status_code == 202 and bool(body.get("task_id")), str(body))

    seen: list[tuple] = []
    task = wait_task(client, body["task_id"], seen=seen)
    out = task.get("output_json") or {}
    check("任务 done", task.get("status") == "done", task.get("error_code") or "")

    stages = [s for _, s in seen if s]
    order = ["metadata", "downloading", "transcribing", "saving"]
    check("四阶段都出现过", set(order) <= set(stages), str(sorted(set(stages))))
    check("阶段顺序正确",
          [s for s in dict.fromkeys(stages)] == order, str(list(dict.fromkeys(stages))))
    progresses = [p for p, _ in seen if isinstance(p, int)]
    check("进度单调不减", progresses == sorted(progresses), str(progresses[-6:]))
    check("进度区间合法（0–100）", progresses and min(progresses) >= 0 and max(progresses) <= 100)

    item_id = out.get("item_id")
    row = sql("SELECT source_type, title, raw_content FROM knowledge_item WHERE id=?", (item_id,))[0]
    check("落库为 video", row[0] == "video", str(row[0]))
    check("标题用视频标题", row[1] == "假视频标题", str(row[1]))
    check("正文带 [mm:ss] 时间戳",
          row[2].startswith("[00:00] ") and "[00:12] " in row[2], row[2][:40].replace("\n", "|"))
    check("output 带时长与段数",
          out.get("duration") == 24 and out.get("segment_count") == 2, str(out))

    # 无音轨视频
    fake_transcriber.__init__()
    fake_transcriber.fail_code = "TRANSCRIBE_NO_AUDIO"
    resp = client.post("/api/ingest/video", json={"url": "https://example.com/v/mute"})
    task = wait_task(client, resp.json()["task_id"])
    check("无音轨 → TRANSCRIBE_NO_AUDIO", task.get("error_code") == "TRANSCRIBE_NO_AUDIO",
          str(task.get("error_code")))
    check("无音轨有中文提示", "音轨" in (task.get("error_msg") or ""), (task.get("error_msg") or "")[:40])


def step_retry(client: TestClient) -> None:
    step("6/10 任务重试")
    fake_fetcher.__init__()
    fake_fetcher.fail_code = "FETCH_TIMEOUT"
    resp = client.post("/api/ingest/url", json={"url": "https://example.com/retry-me"})
    failed = wait_task(client, resp.json()["task_id"])
    check("先造一个失败任务", failed.get("status") == "failed", failed.get("error_code") or "")

    fake_fetcher.__init__()          # 这次让它成功
    resp = client.post(f"/api/tasks/{failed['id']}/retry")
    body = resp.json()
    check("重试返回 202 + 新 task_id",
          resp.status_code == 202 and body.get("task_id") != failed["id"], str(body))
    again = wait_task(client, body["task_id"])
    check("重试后成功入库", again.get("status") == "done", again.get("error_code") or "")
    check("原失败任务保留失败现场",
          client.get(f"/api/tasks/{failed['id']}").json().get("status") == "failed")

    done_task = client.post("/api/ingest/url", json={"url": "https://example.com/done-one"})
    done = wait_task(client, done_task.json()["task_id"])
    resp = client.post(f"/api/tasks/{done['id']}/retry")
    check("重试已完成任务 → 409", resp.status_code == 409,
          resp.json().get("error", {}).get("code", ""))
    resp = client.post("/api/tasks/not-exist/retry")
    check("重试不存在的任务 → 404", resp.status_code == 404)


def step_concurrency(client: TestClient) -> None:
    step("7/10 并发：转录期间查询照常响应")
    fake_transcriber.__init__()
    fake_transcriber.delay = 2.0
    resp = client.post("/api/ingest/video", json={"url": "https://example.com/v/slow"})
    task_id = resp.json()["task_id"]

    latencies: list[float] = []
    errors: list[str] = []
    done = threading.Event()

    def hammer() -> None:
        while not done.is_set():
            for path in ("/api/knowledge?page_size=5", "/api/knowledge/categories"):
                started = time.perf_counter()
                try:
                    resp = client.get(path)
                    if resp.status_code != 200:
                        errors.append(f"{path} → {resp.status_code}")
                except Exception as exc:            # noqa: BLE001
                    errors.append(f"{path} → {type(exc).__name__}")
                latencies.append((time.perf_counter() - started) * 1000)
            time.sleep(0.05)

    worker = threading.Thread(target=hammer, daemon=True)
    worker.start()
    task = wait_task(client, task_id)
    done.set()
    worker.join(timeout=5)

    check("转录期间查询无错误", not errors, "; ".join(errors[:3]))
    check("查询次数足够（说明确实在并发）", len(latencies) >= 10, str(len(latencies)))
    check("单次查询 < 1000ms", max(latencies) < 1000, f"max={max(latencies):.0f}ms")
    check("慢任务仍完成", task.get("status") == "done", task.get("error_code") or "")


def step_zombie_and_tmp() -> None:
    step("8/10 僵尸任务与临时目录")
    with sqlite3.connect(DB, timeout=10) as conn:
        conn.execute(
            """INSERT INTO agent_task (id, type, status, progress, created_at, updated_at)
               VALUES ('zombie-1', 'transcribe_video', 'running', 42, '2026-01-01T00:00:00', '2026-01-01T00:00:00')"""
        )
    count = recover_stale_tasks()
    row = sql("SELECT status, error_code FROM agent_task WHERE id='zombie-1'")[0]
    check("启动清理把 running 标 failed", count >= 1 and row[0] == "failed", str(row))
    check("错误码为 TASK_INTERRUPTED", row[1] == "TASK_INTERRUPTED", str(row[1]))

    tmp_dir = TMP / "tmp" / "whisper-dead"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_dir / "audio.wav").write_bytes(b"0" * 16)
    removed = transcriber.clear_tmp()
    check("data/tmp 残留被清理", removed >= 1 and not tmp_dir.exists(), str(removed))


def step_env(client: TestClient) -> None:
    step("9/10 环境自检")
    payload = client.get("/api/env/check").json()
    check("五项齐全", {"ffmpeg", "whisper", "embedding", "sqlite_vec", "llm"} <= set(payload),
          str(sorted(payload)))
    check("whisper 缺模型时给 hint",
          payload["whisper"]["ok"] or bool(payload["whisper"].get("hint")), str(payload["whisper"]))

    original = config_mod._settings
    try:
        config_mod._settings = replace(original, ffmpeg_dir="")
        import shutil as _shutil

        real_which = _shutil.which
        _shutil.which = lambda name, *a, **k: None if name in ("ffmpeg", "ffprobe") else real_which(name, *a, **k)
        try:
            result = env_probe.check_ffmpeg()
        finally:
            _shutil.which = real_which
    finally:
        config_mod._settings = original

    check("缺 ffmpeg → TRANSCRIBE_NO_FFMPEG", result.get("code") == "TRANSCRIBE_NO_FFMPEG", str(result))
    check("缺 ffmpeg 有修复提示", bool(result.get("hint")), str(result.get("hint", ""))[:30])


def cleanup(keep: bool) -> None:
    if keep:
        print(f"\n临时数据目录已保留：{TMP}")
        return
    if conn_mod._keepalive is not None:
        conn_mod._keepalive.close()
        conn_mod._keepalive = None
    shutil.rmtree(TMP, ignore_errors=True)


# ── 字幕优先（T2.6 增强）────────────────────────────────────
def step_subtitles() -> None:
    step("10/10 现成字幕优先：选取 / 解析 / 失败降级")
    from unittest.mock import patch

    from app.services import subtitles as subs
    from app.services.transcriber import YtDlpWhisperTranscriber

    # ── 选取优先级 ──
    track = subs.pick({"subtitles": {}, "automatic_captions": {
        "ja": [{"ext": "vtt", "url": "j"}],
        "zh-Hant": [{"ext": "vtt", "url": "ht"}],
        "zh-Hans": [{"ext": "vtt", "url": "hs"}],
    }})
    check("自动字幕里选简体（跳过繁体/日语）",
          track is not None and track.lang == "zh-Hans" and track.auto, str(track))

    track = subs.pick({"subtitles": {"en": [{"ext": "vtt", "url": "h"}]},
                       "automatic_captions": {"zh-Hans": [{"ext": "vtt", "url": "a"}]}})
    check("人工字幕优先于自动字幕",
          track is not None and track.lang == "en" and not track.auto, str(track))

    check("一个字幕都没有 → None", subs.pick({"subtitles": {}, "automatic_captions": {}}) is None)
    check("只有 srv3 这种不认的格式 → None",
          subs.pick({"automatic_captions": {"zh-Hans": [{"ext": "srv3", "url": "x"}]}}) is None)

    # ── 解析 ──
    vtt = ("WEBVTT\nKind: captions\n\n"
           "00:00:01.000 --> 00:00:04.000\n第一句\n\n"
           "00:01:05.500 --> 00:01:07.000\n<v A>第二句</v>\n")
    cues = subs._parse_cues(vtt)
    check("VTT 解析：时间与文本都对，标签被剥掉",
          cues == [(1.0, "第一句"), (65.5, "第二句")], str(cues))

    cues = subs._parse_json('{"body":[{"from":2.0,"to":4.0,"content":"中文句子"}]}')
    check("B 站 json 解析", cues == [(2.0, "中文句子")], str(cues))

    cleaned = subs._clean([(1.0, "a"), (1.0, "a"), (2.0, "a"), (3.0, "")])
    check("相邻重复与空行被去掉", cleaned == [(1.0, "a")], str(cleaned))

    # ── 命中与降级 ──
    info = {"subtitles": {"zh-Hans": [{"ext": "vtt", "url": "u"}]}}
    with patch.object(subs, "fetch", return_value=[(0.0, "你好"), (12.0, "第二句")]):
        hit = YtDlpWhisperTranscriber._try_subtitles(info)
    check("字幕命中 → 正文带 [mm:ss] 时间戳",
          hit == ("[00:00] 你好\n[00:12] 第二句", "zh-Hans", 2), str(hit))

    with patch.object(subs, "fetch", side_effect=OSError("boom")):
        check("字幕下载失败 → 返回 None（降级，不抛）",
              YtDlpWhisperTranscriber._try_subtitles(info) is None)

    with patch.object(subs, "fetch", return_value=[]):
        check("字幕解析为空 → 返回 None",
              YtDlpWhisperTranscriber._try_subtitles(info) is None)

    check("压根没有字幕 → 返回 None", YtDlpWhisperTranscriber._try_subtitles({}) is None)


def main() -> int:
    keep = "--keep" in sys.argv[1:]
    print("=" * 62)
    print("  Cairn · M2 验收（T2.10）")
    print("=" * 62)
    print(f"临时数据目录：{TMP}")

    aborted = ""
    # 注入假实现：整轮验收不访问任何真实站点
    fetcher.set_fetcher(fake_fetcher)
    transcriber.set_transcriber(fake_transcriber)
    try:
        with TestClient(app) as client:
            step_endpoints(client)
            item_id = step_web_ok(client)
            step_dedupe(client, item_id)
            step_web_failures(client)
            step_video(client)
            step_retry(client)
            step_concurrency(client)
            step_zombie_and_tmp()
            step_env(client)
            step_subtitles()
    except Exception as exc:  # 任何未捕获异常都算验收失败
        aborted = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        fetcher.set_fetcher(None)
        transcriber.set_transcriber(None)
        cleanup(keep)

    passed = sum(1 for ok, _ in RESULTS if ok)
    failed = [name for ok, name in RESULTS if not ok]
    print("\n" + "=" * 62)
    print(f"  结果：{passed}/{len(RESULTS)} PASS")
    if aborted:
        print(f"  中断：{aborted}")
    for name in failed:
        print(f"    - 失败：{name}")
    print("=" * 62)
    return 0 if not aborted and not failed and RESULTS else 1


if __name__ == "__main__":
    sys.exit(main())
