-- v3 → v4：本地文件、工作区、逐页文本（M9 T9.2）
--
-- 只做追加：建三张新表（IF NOT EXISTS）+ knowledge_item 补三列 + question 补两列。
-- 与 schema.sql 的 v4 段必须一致（数据契约 §1：新建库与老库升级形态一致）。
--
-- 老数据回填由 DDL 默认值完成，不写 UPDATE：
--   knowledge_item.kind         = 'material'（老内容都是普通资料）
--   knowledge_item.workspace_id = NULL（未归类）
--   knowledge_item.file_id      = NULL（老内容没有原件）
--   question.origin             = 'ai'（老题目都是模型生成）
--   question.number             = NULL
--
-- 坑：SQLite 的 ALTER TABLE 不能加唯一约束，workspace.name 同名允许只写在契约里；
--     foreign_keys 是连接级，conn.py 已开，这里不要关。
--     kind 必须带 NOT NULL DEFAULT，否则 SQLite 拒绝给已有表加 NOT NULL 列。

CREATE TABLE IF NOT EXISTS workspace (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  color       TEXT,
  sort_order  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ws_sort ON workspace(sort_order, id);

CREATE TABLE IF NOT EXISTS item_file (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id        INTEGER NOT NULL REFERENCES knowledge_item(id) ON DELETE CASCADE,
  role           TEXT NOT NULL DEFAULT 'main',
  original_name  TEXT,
  ext            TEXT,
  mime           TEXT,
  size           INTEGER,
  sha256         TEXT,
  stored_path    TEXT,
  page_count     INTEGER NOT NULL DEFAULT 0,
  has_text_layer INTEGER NOT NULL DEFAULT 0,
  ocr_status     TEXT NOT NULL DEFAULT 'none'
);
CREATE INDEX IF NOT EXISTS idx_file_item ON item_file(item_id);
CREATE INDEX IF NOT EXISTS idx_file_hash ON item_file(sha256);

CREATE TABLE IF NOT EXISTS item_page (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id       INTEGER NOT NULL REFERENCES knowledge_item(id) ON DELETE CASCADE,
  file_id       INTEGER REFERENCES item_file(id) ON DELETE CASCADE,
  page_no       INTEGER NOT NULL,
  text          TEXT NOT NULL DEFAULT '',
  source        TEXT NOT NULL DEFAULT 'ocr',
  avg_conf      REAL,
  image_path    TEXT,
  text_reviewed TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_page_no   ON item_page(file_id, page_no);
CREATE INDEX        IF NOT EXISTS idx_page_item ON item_page(item_id, page_no);

ALTER TABLE knowledge_item ADD COLUMN workspace_id INTEGER REFERENCES workspace(id) ON DELETE SET NULL;
ALTER TABLE knowledge_item ADD COLUMN kind TEXT NOT NULL DEFAULT 'material';
ALTER TABLE knowledge_item ADD COLUMN file_id INTEGER REFERENCES item_file(id);

ALTER TABLE question ADD COLUMN origin TEXT NOT NULL DEFAULT 'ai';
ALTER TABLE question ADD COLUMN number TEXT;
