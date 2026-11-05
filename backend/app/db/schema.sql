-- Cairn 全量表结构（T1.3）
-- 唯一真相：docs/contracts/数据契约.md §2。代码落地后以本文件为准。
-- 注意：PRAGMA journal_mode / foreign_keys 不在本文件，由 db/migrate.py 与 db/conn.py 处理
--        （foreign_keys 是连接级，必须每个连接都开；WAL 只在建库时设一次）。
-- 注意：依赖可选扩展 sqlite-vec 的 chunk_vec 单独放 schema_vec.sql，见数据契约 §1 例外。

-- ── 知识条目 ────────────────────────────────────────────
CREATE TABLE knowledge_item (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  title           TEXT    NOT NULL,
  source_type     TEXT    NOT NULL,   -- text | web | video | file
  source_url      TEXT,
  raw_content     TEXT    NOT NULL,
  content_hash    TEXT    NOT NULL,   -- sha256(raw_content)，用于去重
  summary         TEXT,
  key_points      TEXT,               -- JSON 数组字符串
  structured_note TEXT,               -- Markdown，用户可编辑
  note_edited     INTEGER NOT NULL DEFAULT 0,
  category        TEXT,
  tags            TEXT,               -- JSON 数组字符串
  status          TEXT    NOT NULL DEFAULT 'pending',
                  -- pending | organizing | ready | failed
  truncated       INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT    NOT NULL,
  updated_at      TEXT    NOT NULL
);
CREATE UNIQUE INDEX idx_item_url  ON knowledge_item(source_url) WHERE source_url IS NOT NULL;
CREATE INDEX        idx_item_hash ON knowledge_item(content_hash);
CREATE INDEX        idx_item_cat  ON knowledge_item(category, status);

-- ── 分块 ────────────────────────────────────────────────
CREATE TABLE chunk (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id  INTEGER NOT NULL REFERENCES knowledge_item(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  content  TEXT    NOT NULL,
  source   TEXT    NOT NULL DEFAULT 'raw'   -- raw = 原文切块 | note = 用户笔记切块
);
CREATE INDEX idx_chunk_item ON chunk(item_id, source);

-- ── 全文索引（trigram 是中文可搜的唯一前提）───────────────
CREATE VIRTUAL TABLE chunk_fts USING fts5(
  content, content='chunk', content_rowid='id', tokenize='trigram'
);
CREATE TRIGGER chunk_ai AFTER INSERT ON chunk BEGIN
  INSERT INTO chunk_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER chunk_ad AFTER DELETE ON chunk BEGIN
  INSERT INTO chunk_fts(chunk_fts, rowid, content) VALUES('delete', old.id, old.content);
END;
CREATE TRIGGER chunk_au AFTER UPDATE ON chunk BEGIN
  INSERT INTO chunk_fts(chunk_fts, rowid, content) VALUES('delete', old.id, old.content);
  INSERT INTO chunk_fts(rowid, content) VALUES (new.id, new.content);
END;

-- ── 异步任务 ────────────────────────────────────────────
CREATE TABLE agent_task (
  id          TEXT PRIMARY KEY,        -- uuid4
  type        TEXT NOT NULL,           -- fetch_url | transcribe_video | organize | index_embed
  status      TEXT NOT NULL,           -- queued | running | done | failed
  progress    INTEGER NOT NULL DEFAULT 0,
  stage       TEXT,
  input_json  TEXT,
  output_json TEXT,
  error_code  TEXT,
  error_msg   TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX idx_task_status ON agent_task(status, created_at);

-- ── HTML 学习页 ─────────────────────────────────────────
CREATE TABLE html_artifact (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  title        TEXT NOT NULL,
  item_ids     TEXT NOT NULL,
  html_content TEXT NOT NULL,
  created_at   TEXT NOT NULL
);

-- ── 题目 ────────────────────────────────────────────────
CREATE TABLE question (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id     INTEGER REFERENCES knowledge_item(id) ON DELETE CASCADE,
  type        TEXT NOT NULL,
  difficulty  TEXT NOT NULL,
  payload     TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_q_fp ON question(fingerprint);

-- ── 作答记录 ────────────────────────────────────────────
CREATE TABLE quiz_attempt (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id INTEGER NOT NULL REFERENCES question(id) ON DELETE CASCADE,
  user_answer TEXT NOT NULL,
  is_correct  INTEGER,
  feedback    TEXT,
  duration_ms INTEGER,
  created_at  TEXT NOT NULL
);
CREATE INDEX idx_attempt_q ON quiz_attempt(question_id, created_at);

-- ── 复习队列 ────────────────────────────────────────────
CREATE TABLE review_item (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id   INTEGER NOT NULL REFERENCES question(id) ON DELETE CASCADE,
  due_at        TEXT NOT NULL,
  interval_days INTEGER NOT NULL DEFAULT 1,
  lapses        INTEGER NOT NULL DEFAULT 0,
  last_result   INTEGER,
  updated_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_review_q   ON review_item(question_id);
CREATE INDEX        idx_review_due ON review_item(due_at);

-- ── 番茄钟 ──────────────────────────────────────────────
CREATE TABLE study_session (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  target_type      TEXT,
  target_id        INTEGER,
  start_time       TEXT NOT NULL,
  end_time         TEXT,
  duration_seconds INTEGER NOT NULL DEFAULT 0,
  planned_seconds  INTEGER NOT NULL DEFAULT 1500,
  status           TEXT NOT NULL DEFAULT 'running',
  note             TEXT,
  created_at       TEXT NOT NULL
);
CREATE INDEX idx_session_time ON study_session(start_time);

-- ── LLM 调用日志（reasoning_tokens 见 ADR-022）────────────
CREATE TABLE llm_call_log (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  agent             TEXT NOT NULL,
  model             TEXT NOT NULL,
  prompt_tokens     INTEGER,
  completion_tokens INTEGER,
  reasoning_tokens  INTEGER,
  duration_ms       INTEGER,
  ok                INTEGER NOT NULL,
  error_msg         TEXT,
  created_at        TEXT NOT NULL
);
