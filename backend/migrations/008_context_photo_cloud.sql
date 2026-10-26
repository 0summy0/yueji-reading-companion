-- 情境照片支持 WorkBuddy 云存储：允许只保存云端对象路径，本地路径可为空。
CREATE TABLE IF NOT EXISTS reading_context_photos_v2 (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES reading_sessions(id) ON DELETE CASCADE,
    book_id TEXT NOT NULL REFERENCES bookshelves(id) ON DELETE CASCADE,
    local_path TEXT,
    cloud_path TEXT,
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO reading_context_photos_v2 (id, user_id, session_id, book_id, local_path, cloud_path, captured_at, created_at)
SELECT id, user_id, session_id, book_id, local_path, NULL, captured_at, created_at
FROM reading_context_photos;

DROP TABLE reading_context_photos;

ALTER TABLE reading_context_photos_v2 RENAME TO reading_context_photos;

CREATE INDEX IF NOT EXISTS idx_reading_context_photos_session
    ON reading_context_photos(session_id, created_at);
