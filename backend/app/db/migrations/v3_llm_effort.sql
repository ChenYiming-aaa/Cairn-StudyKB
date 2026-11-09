-- v2 → v3：llm_call_log 补两列，记「这次到底发了什么思考强度」（S-2 裁决）
--
-- 为什么必须记实际值：`reasoning_effort` 可能因为两种原因没发出去 ——
-- provider 声明不支持（supports_effort=false），或服务 400 拒绝后被自动去掉。
-- 只记设置里的 effort，日志会骗人：明明没发，看上去发了。
--
--   effort          实际进请求体的值；**没发就是 NULL**，不是字符串 'none'
--                   （「关掉思考」与「这服务不支持」是两件事，靠下一列区分）
--   effort_dropped  1 = 本来要发、最终没发（不支持 / 被拒后去掉）
--
-- ALTER TABLE 只加列不重写数据，老库升级瞬间完成。与 schema.sql 同名段必须一致。
ALTER TABLE llm_call_log ADD COLUMN effort TEXT;
ALTER TABLE llm_call_log ADD COLUMN effort_dropped INTEGER NOT NULL DEFAULT 0;
