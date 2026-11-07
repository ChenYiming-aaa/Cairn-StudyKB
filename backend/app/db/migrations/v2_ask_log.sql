-- v1 → v2：新增问答历史表（T3.12）
-- 与 schema.sql 末尾同名段保持一致。这里不改动任何既有表，只做追加。
CREATE TABLE IF NOT EXISTS ask_log (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  question          TEXT    NOT NULL,
  answer            TEXT    NOT NULL DEFAULT '',
  sources_json      TEXT,
  match_type        TEXT,
  fallback          TEXT,
  no_result         INTEGER NOT NULL DEFAULT 0,
  error_code        TEXT,
  prompt_tokens     INTEGER,
  completion_tokens INTEGER,
  duration_ms       INTEGER,
  created_at        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ask_time ON ask_log(created_at DESC);
