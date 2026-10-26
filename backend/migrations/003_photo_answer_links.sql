-- 阶段2：照片确认产生的阅读会话可回溯到定位尝试；异步回答留审计索引。
ALTER TABLE reading_sessions ADD COLUMN source_location_attempt_id TEXT REFERENCES location_attempts(id) ON DELETE SET NULL;
