-- 010 时间线与照片维护常用查询索引；仅新增索引，不改动既有阅读数据。
CREATE INDEX IF NOT EXISTS idx_sessions_edition_ended
    ON reading_sessions(edition_id, ended_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_location_attempt
    ON reading_sessions(source_location_attempt_id)
    WHERE source_location_attempt_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_photos_book ON photos(book_id);
CREATE INDEX IF NOT EXISTS idx_location_attempts_book ON location_attempts(book_id);
CREATE INDEX IF NOT EXISTS idx_context_photos_book ON reading_context_photos(book_id);
