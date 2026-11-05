-- 可选向量表（M3 启用）。见数据契约 §1 例外 / §2 与 ADR-010。
-- 本文件由 db/migrate.py 在且仅在检测到 sqlite-vec 扩展可用时执行。
-- 扩展不可用时此表不存在，检索降级为 numpy 暴力余弦，功能不中断。
-- 任何读此表的代码必须先判断存在性，不能假设一定在（数据契约 §3）。
CREATE VIRTUAL TABLE chunk_vec USING vec0(
  chunk_id  INTEGER PRIMARY KEY,   -- 对应 chunk.id
  embedding float[512]             -- bge-small-zh-v1.5 输出维度，不可随意改
);
