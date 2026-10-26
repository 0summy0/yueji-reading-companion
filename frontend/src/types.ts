export type Material = 'cloth' | 'paper' | 'leather' | 'linen';

export interface SpineStyle {
  color: string;
  accent: string;
  material: Material;
  title_layout: 'vertical' | 'horizontal';
  height: number;
  width: number;
}

export interface Progress {
  current_anchor: string | null;
  current_chapter: string | null;
  current_position: number | null;
  current_excerpt: string | null;
  confirmed_passages: number;
  passage_count: number;
  last_read_at: string | null;
}

export interface Book {
  id: string;
  edition_id: string;
  title: string;
  author: string;
  language: string;
  format: 'epub' | 'txt' | 'sample';
  source_hash: string;
  source_name: string;
  parsed_at: string;
  parser_version: string;
  content_sha256: string;
  spine_style: SpineStyle;
  sort_order: number;
  status: 'reading' | 'paused' | 'finished';
  created_at: string;
  updated_at: string;
  progress: Progress;
  chapters?: Chapter[];
  read_ranges?: ReadRange[];
  duplicate?: boolean;
}

export interface Chapter {
  chapter_order: number;
  chapter_title: string;
  passage_count: number;
  first_position: number;
}

export interface ReadRange {
  id: string;
  start_anchor: string;
  end_anchor: string;
  start_position: number;
  end_position: number;
  confirmation_method: string;
  created_at: string;
}

export interface Passage {
  id: string;
  chapter_order: number;
  chapter_title: string;
  passage_order: number;
  position: number;
  start_char: number;
  end_char: number;
  hash: string;
  text: string;
}

export interface ReadingSession {
  id: string;
  edition_id: string;
  started_at: string;
  ended_at: string;
  timezone: string;
  start_anchor: string | null;
  current_anchor: string;
  session_type: 'sequential' | 'skip' | 'reread';
  sequential_confirmed: number;
  reading_context: string | null;
  context_photos?: ContextPhoto[];
  chapter_title: string;
  position: number;
  excerpt: string;
  source: 'user';
}

export interface ContextPhoto {
  id: string;
  session_id: string;
  captured_at: string;
  created_at: string;
  cloud_path?: string | null;
  url: string | null;
}

export interface NoteVersion {
  id: string;
  note_id: string;
  version: number;
  text: string;
  created_at: string;
}

export interface Note {
  id: string;
  book_id: string;
  book_title: string;
  edition_id: string;
  session_id: string | null;
  author: 'user';
  source: 'user';
  text: string;
  version: number;
  current_version_id: string;
  created_at: string;
  updated_at: string;
  evidence: null | {
    passage_id: string;
    chapter_title: string;
    position: number;
    start_char: number;
    end_char: number;
    excerpt: string;
  };
  versions: NoteVersion[];
  stale_cards_marked?: number;
  derivation_state?: string;
}

export interface TimelineEvent {
  kind: 'session' | 'note';
  occurred_at: string;
  book_id: string;
  book_title: string;
  source: 'user';
  data: ReadingSession | Note;
}

export type CapabilityStatus = 'verified' | 'unsupported' | 'inconclusive' | 'vision_partial' | 'unverified_error' | 'untested' | 'stale';

export interface CapabilityDetail {
  status: CapabilityStatus;
  message?: string;
  checked_at?: string;
}

export interface Capabilities {
  text: CapabilityDetail;
  vision_input: CapabilityDetail;
  page_ocr: CapabilityDetail;
  simulated?: boolean;
  provider_alias?: string;
  model_id?: string;
  checked_at?: string;
  probe_version?: string;
  config_fingerprint?: string;
  failure_category?: string | null;
  simulation_notice: string;
  privacy?: string;
}

export type ProviderType = 'mock' | 'openai_compatible';

export interface AIConnection {
  id: string;
  alias: string;
  provider_type: ProviderType;
  model_id: string;
  base_url: string;
  scenario: MockScenario | null;
  enabled: boolean;
  has_saved_key: boolean;
  capabilities: Capabilities | null;
  simulation_notice: string;
  credential_mode: 'not_collected_mock' | 'stored_encrypted';
}

export type MockScenario = 'success' | 'unsupported' | 'hallucinated' | 'partial' | 'auth_error' | 'rate_limited' | 'timeout';

export interface User {
  id: string;
  username: string;
  display_name: string;
}

export interface PhotoCandidate {
  passage_id: string;
  chapter_title: string;
  position: number;
  start_char: number;
  end_char: number;
  excerpt: string;
  score: number;
  confidence: 'high' | 'medium' | 'low';
}

export interface PhotoAttempt {
  id: string;
  photo_id: string;
  state: 'pending' | 'candidates' | 'confirmed' | 'rejected' | 'failed';
  ocr_text: string;
  candidates: PhotoCandidate[];
  message: string;
  cloud_path?: string | null;
  provider?: { alias?: string; model_id?: string; task_route?: string };
  photo?: { width: number; height: number; format: string };
}

export interface PhotoPath {
  automatic_location_available: boolean;
  display_path: 'ai_vision' | 'ai_ocr' | 'manual';
  selected_task?: 'analyze_image' | 'ocr_page' | null;
  message: string;
  simulation_notice: string;
  routes: Record<string, string>;
  capabilities?: Capabilities | null;
}

export interface AskEvidence {
  id: string;
  kind: 'note' | 'passage';
  speaker: 'user' | 'author';
  book_id: string;
  book_title: string;
  note_id: string | null;
  passage_id: string | null;
  chapter_title: string | null;
  position: number | null;
  excerpt: string;
  created_at: string | null;
}

export interface AskResult {
  answer: string;
  citations: string[];
  evidence: AskEvidence[];
  uncertainty: 'low' | 'medium' | 'high';
  follow_up_question: string | null;
  spoiler_risk: 'low' | 'medium' | 'high';
  model: { alias?: string; model_id?: string } | null;
}

/** /api/evidence 返回的证据包条目（仅当前用户已读内容），供免密钥云端问答组织提示词。 */
export interface EvidenceItem {
  id: string;
  kind: 'note' | 'passage';
  speaker: 'user' | 'author';
  book_id: string;
  book_title: string;
  chapter_title: string | null;
  position: number | null;
  excerpt: string;
  text: string;
}

// ---------- 书格拉底（苏格拉底式理解检查） ----------

export type SocraticKind = 'fact' | 'causal' | 'judgment';

export interface SocraticEvidence {
  id: string;
  kind: 'note' | 'passage';
  speaker: 'user' | 'author';
  book_id: string;
  book_title: string;
  note_id: string | null;
  passage_id: string | null;
  chapter_title: string | null;
  position: number | null;
  excerpt: string;
}

export interface SocraticTurn {
  turn_index: number;
  kind: SocraticKind;
  kind_label: string;
  question: string;
  question_evidence_ids: string[];
  answer: string | null;
  answered_at: string | null;
  feedback: string | null;
  feedback_evidence_ids: string[];
  created_at: string;
}

export interface SocraticRecommendation {
  book_id: string;
  title: string;
  reason: string;
  related_theme: string;
  difficulty: '轻松' | '适中' | '有挑战';
  timing: string;
}

export interface SocraticReport {
  clear_points: string[];
  vague_points: string[];
  user_viewpoints: string[];
  revisit_evidence: SocraticEvidence[];
  follow_up_suggestions: string[];
  recommendations: SocraticRecommendation[];
  recommendations_note: string | null;
  model_id: string | null;
  created_at: string;
}

export interface SocraticTask {
  stage: 'question' | 'feedback' | 'report';
  turn_index?: number;
  kind?: SocraticKind;
  prompt?: { messages: { role: string; content: string }[] };
}

export interface SocraticSessionView {
  id: string;
  book_id: string;
  book_title: string;
  book_author: string;
  rounds_planned: number;
  engine: 'byok' | 'cloud';
  status: 'active' | 'finished';
  state: 'need_question' | 'awaiting_answer' | 'need_feedback' | 'need_report' | 'done';
  current_turn: number;
  created_at: string;
  finished_at: string | null;
  evidence: SocraticEvidence[];
  turns: SocraticTurn[];
  report: SocraticReport | null;
  task: SocraticTask | null;
  duplicate?: boolean;
}

export interface SocraticSessionSummary {
  id: string;
  book_id: string;
  book_title: string;
  rounds_planned: number;
  engine: 'byok' | 'cloud';
  status: 'active' | 'finished';
  state: string;
  current_turn: number;
  answered_turns: number;
  has_report: boolean;
  created_at: string;
  finished_at: string | null;
}
