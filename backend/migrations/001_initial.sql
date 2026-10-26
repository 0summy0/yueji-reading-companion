PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS works (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'zh-CN',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS editions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    format TEXT NOT NULL CHECK(format IN ('epub', 'txt', 'sample')),
    source_hash TEXT NOT NULL,
    source_name TEXT NOT NULL,
    parsed_at TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    UNIQUE(user_id, source_hash)
);

CREATE TABLE IF NOT EXISTS bookshelves (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    edition_id TEXT NOT NULL UNIQUE REFERENCES editions(id) ON DELETE CASCADE,
    spine_style_json TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'reading' CHECK(status IN ('reading', 'paused', 'finished')),
    current_anchor TEXT REFERENCES passages(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS passages (
    id TEXT PRIMARY KEY,
    edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
    chapter_order INTEGER NOT NULL,
    chapter_title TEXT NOT NULL,
    passage_order INTEGER NOT NULL,
    position INTEGER NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    text TEXT NOT NULL,
    hash TEXT NOT NULL,
    UNIQUE(edition_id, chapter_order, passage_order),
    UNIQUE(edition_id, position),
    CHECK(start_char >= 0 AND end_char > start_char)
);

CREATE TABLE IF NOT EXISTS reading_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    timezone TEXT NOT NULL,
    start_anchor TEXT REFERENCES passages(id) ON DELETE SET NULL,
    current_anchor TEXT NOT NULL REFERENCES passages(id) ON DELETE RESTRICT,
    session_type TEXT NOT NULL CHECK(session_type IN ('sequential', 'skip', 'reread')),
    sequential_confirmed INTEGER NOT NULL DEFAULT 0,
    anchor_read_confirmed INTEGER NOT NULL DEFAULT 1,
    client_request_id TEXT UNIQUE,
    request_hash TEXT,
    created_at TEXT NOT NULL,
    CHECK(ended_at >= started_at)
);

CREATE TABLE IF NOT EXISTS read_ranges (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
    start_anchor TEXT NOT NULL REFERENCES passages(id) ON DELETE RESTRICT,
    end_anchor TEXT NOT NULL REFERENCES passages(id) ON DELETE RESTRICT,
    start_position INTEGER NOT NULL,
    end_position INTEGER NOT NULL,
    confirmation_method TEXT NOT NULL CHECK(confirmation_method IN ('manual_sequential', 'manual_point', 'photo_confirmed')),
    source_session_id TEXT REFERENCES reading_sessions(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    CHECK(end_position >= start_position)
);

CREATE TABLE IF NOT EXISTS photos (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES reading_sessions(id) ON DELETE SET NULL,
    local_path TEXT,
    captured_at TEXT,
    retention_policy TEXT NOT NULL DEFAULT 'private_local',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS location_attempts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    photo_id TEXT REFERENCES photos(id) ON DELETE CASCADE,
    ocr_text TEXT,
    candidate_json TEXT NOT NULL DEFAULT '[]',
    confidence TEXT,
    chosen_anchor TEXT REFERENCES passages(id) ON DELETE SET NULL,
    state TEXT NOT NULL CHECK(state IN ('pending', 'candidates', 'confirmed', 'rejected', 'failed')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES reading_sessions(id) ON DELETE SET NULL,
    author TEXT NOT NULL DEFAULT 'user' CHECK(author = 'user'),
    client_request_id TEXT UNIQUE,
    request_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS note_versions (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(note_id, version)
);

CREATE TABLE IF NOT EXISTS evidence_links (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    note_version_id TEXT REFERENCES note_versions(id) ON DELETE CASCADE,
    passage_id TEXT REFERENCES passages(id) ON DELETE CASCADE,
    photo_id TEXT REFERENCES photos(id) ON DELETE CASCADE,
    relation TEXT NOT NULL CHECK(relation IN ('anchor', 'quotation', 'photo_source', 'derived_from')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_cards (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    speaker TEXT NOT NULL CHECK(speaker IN ('author', 'user', 'ai')),
    epistemic_type TEXT NOT NULL CHECK(epistemic_type IN ('fact', 'opinion', 'question', 'hypothesis', 'feeling', 'summary')),
    text TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('suggested', 'confirmed', 'edited', 'retracted', 'stale')),
    prompt_version TEXT,
    model_id TEXT,
    source_note_version TEXT REFERENCES note_versions(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_edges (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    from_card_id TEXT NOT NULL REFERENCES knowledge_cards(id) ON DELETE CASCADE,
    to_card_id TEXT NOT NULL REFERENCES knowledge_cards(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_index (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    embedding_model TEXT,
    vector_ref TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(entity_type, entity_id, embedding_model)
);

CREATE TABLE IF NOT EXISTS ai_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued', 'running', 'succeeded', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(job_type, input_hash)
);

CREATE TABLE IF NOT EXISTS answer_traces (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    intent TEXT NOT NULL,
    allowed_source_ids TEXT NOT NULL,
    cited_ids TEXT NOT NULL,
    model_version TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_connections (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    model_id TEXT NOT NULL,
    base_url TEXT NOT NULL,
    secret_ref TEXT,
    adapter_version TEXT NOT NULL,
    config_fingerprint TEXT NOT NULL,
    mock_scenario TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_capability_checks (
    id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL REFERENCES ai_connections(id) ON DELETE CASCADE,
    probe_version TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    text_status TEXT NOT NULL,
    vision_status TEXT NOT NULL,
    page_ocr_status TEXT NOT NULL,
    failure_category TEXT,
    diagnostic_safe_json TEXT NOT NULL,
    config_fingerprint TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_task_routes (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL CHECK(task_type IN ('generate_text', 'analyze_image', 'extract_structured', 'embed_text', 'ocr_page')),
    connection_id TEXT NOT NULL REFERENCES ai_connections(id) ON DELETE CASCADE,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, task_type)
);

CREATE INDEX IF NOT EXISTS idx_passages_edition_position ON passages(edition_id, position);
CREATE INDEX IF NOT EXISTS idx_sessions_edition_started ON reading_sessions(edition_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ranges_edition_position ON read_ranges(edition_id, start_position, end_position);
CREATE INDEX IF NOT EXISTS idx_notes_edition_updated ON notes(edition_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_note_versions_note ON note_versions(note_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_note_version ON evidence_links(note_version_id);
CREATE INDEX IF NOT EXISTS idx_cards_source_version ON knowledge_cards(source_note_version);
CREATE INDEX IF NOT EXISTS idx_checks_connection_time ON ai_capability_checks(connection_id, checked_at DESC);

INSERT OR IGNORE INTO users(id, display_name, created_at)
VALUES ('u_local', '本地读者', '2026-01-01T00:00:00+00:00');
