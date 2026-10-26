-- 阶段1增量：可选阅读情境，纯用户文字，不做定位或天气推断。
ALTER TABLE reading_sessions ADD COLUMN reading_context TEXT;
