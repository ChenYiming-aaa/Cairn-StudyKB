-- v5 → v6：content_hash 唯一（去重竞态）
--
-- 起因：`create_item` 是「先 find_by_hash 再 INSERT」，两个请求同时导入同一份内容时
-- 都会看到"没有"，于是各插一条 —— 库里出现两份同哈希的内容，界面看起来是重复条目，
-- 复习/统计还各算一遍。
--
-- 建唯一索引前先把**历史重复行**处理掉，否则 CREATE UNIQUE INDEX 会直接失败：
-- 重复组里保留 id 最小的那条（`find_by_hash` 一直只认它），其余把
-- content_hash 改写成 "hash:id"。这样既不删内容、也不动 chunk/question 的关联，
-- 只是让这些副本从此不参与去重匹配（它们本来就没被匹配到过）。
--
-- 与 schema.sql 的 v6 段必须一致（数据契约 §1）。

UPDATE knowledge_item
   SET content_hash = content_hash || ':' || id
 WHERE id NOT IN (SELECT MIN(id) FROM knowledge_item GROUP BY content_hash);

DROP INDEX IF EXISTS idx_item_hash;

CREATE UNIQUE INDEX idx_item_hash ON knowledge_item(content_hash);
