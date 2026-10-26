-- 阅读情境照片只属于阅读会话；不参与书页 OCR，也不作为证据发送给书童。
CREATE TABLE IF NOT EXISTS reading_context_photos (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES reading_sessions(id) ON DELETE CASCADE,
    book_id TEXT NOT NULL REFERENCES bookshelves(id) ON DELETE CASCADE,
    local_path TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reading_context_photos_session
    ON reading_context_photos(session_id, created_at);
