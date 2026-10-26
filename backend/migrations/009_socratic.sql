-- 009 · 书格拉底（苏格拉底式理解检查）
-- 会话固定证据快照，服务端生成并校验每轮问题、反馈与报告；作者原文 / 用户回答 / AI 反馈分开存储。

CREATE TABLE IF NOT EXISTS socratic_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id TEXT NOT NULL REFERENCES bookshelves(id) ON DELETE CASCADE,
    edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
    rounds_planned INTEGER NOT NULL,
    engine TEXT NOT NULL DEFAULT 'byok',
    status TEXT NOT NULL DEFAULT 'active',
    state TEXT NOT NULL DEFAULT 'need_question',
    evidence_ids_json TEXT NOT NULL,
    current_turn INTEGER NOT NULL DEFAULT 1,
    client_request_id TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_socratic_sessions_crid
    ON socratic_sessions(client_request_id) WHERE client_request_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS socratic_turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES socratic_sessions(id) ON DELETE CASCADE,
    turn_index INTEGER NOT NULL,
    kind TEXT NOT NULL,
    question TEXT NOT NULL,
    question_evidence_ids_json TEXT NOT NULL,
    answer TEXT,
    answered_at TEXT,
    feedback TEXT,
    feedback_evidence_ids_json TEXT,
    feedback_model_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, turn_index)
);

CREATE TABLE IF NOT EXISTS socratic_reports (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE REFERENCES socratic_sessions(id) ON DELETE CASCADE,
    clear_points_json TEXT NOT NULL,
    vague_points_json TEXT NOT NULL,
    user_viewpoints_json TEXT NOT NULL,
    revisit_evidence_ids_json TEXT NOT NULL,
    follow_up_suggestions_json TEXT NOT NULL,
    recommendations_json TEXT NOT NULL,
    recommendations_note TEXT,
    model_id TEXT,
    created_at TEXT NOT NULL
);
