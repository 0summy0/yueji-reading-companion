import type { AIConnection, AskResult, Book, Capabilities, EvidenceItem, MockScenario, Note, Passage, PhotoAttempt, PhotoPath, ProviderType, ReadingSession, SocraticSessionSummary, SocraticSessionView, SpineStyle, TimelineEvent, User } from '../types';

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** 把 Pydantic 的英文校验原文翻译成用户可以照着改的中文。 */
export function humanizeValidationMessage(message: string, loc: string[] = []): string {
  const joined = loc.join('.');
  const field = (fallbackText: string): string => {
    for (const [key, label] of [
      ['password', '密码'],
      ['username', '用户名'],
      ['invite_code', '邀请码'],
      ['title', '书名'],
      ['email', '邮箱'],
      ['body', '正文'],
      ['text', '内容'],
    ] as const) {
      if (joined.includes(key) || fallbackText.includes(key)) return label;
    }
    return '输入';
  };
  const text = message;
  const atLeast = /String should have at least (\d+) characters/.exec(text);
  const atMost = /String should have at most (\d+) characters/.exec(text);
  if (atLeast && atMost) return `${field(text)}长度需在 ${atLeast[1]}–${atMost[1]} 个字符之间`;
  if (atLeast) return `${field(text)}至少需要 ${atLeast[1]} 个字符`;
  if (atMost) return `${field(text)}最多 ${atMost[1]} 个字符`;
  if (/invalid or missing URL scheme|Input should be an? '?https?:?\/?\/?'? ?URL/.test(text) || text.includes('URL')) return '链接格式不正确，请填写 https:// 开头的完整地址';
  if (text.includes('email') || joined.includes('email')) return '邮箱格式不正确';
  if (text.includes('should match pattern')) return `${field(text)}含有不允许的字符，请只用中文、字母、数字、下划线或短横线`;
  if (text.includes('Field required')) return '还有必填项没有填写';
  if (text.includes('Input should be a valid number')) return '这里需要填写数字';
  if (text.includes('Input should be a valid string')) return '这里需要填写文字';
  return text;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    const message = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail
          .map((item) => {
            const loc = Array.isArray(item?.loc) ? item.loc.map(String) : [];
            const raw = typeof item?.msg === 'string' ? item.msg : '';
            // Pydantic 经常只给 msg 不带 loc，此时从 loc[0] 或 msg 都拿不到字段名，用通用兜底。
            return humanizeValidationMessage(raw || `${item?.type || ''}`, loc);
          })
          .join('；')
        : `请求失败（${response.status}）`;
    throw new ApiError(response.status, message);
  }
  return body as T;
}

const json = (method: string, value: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(value),
});

export interface SessionPayload {
  started_at: string;
  ended_at: string;
  timezone: string;
  start_anchor: string | null;
  current_anchor: string;
  session_type: 'sequential' | 'skip' | 'reread';
  sequential_confirmed: boolean;
  anchor_read_confirmed: boolean;
  reading_context?: string | null;
  client_request_id: string;
}

export const api = {
  listBooks: () => request<{ items: Book[] }>('/api/books'),
  getBook: (id: string) => request<Book>(`/api/books/${id}`),
  getPassages: async (id: string) => (await request<{ items: Passage[] }>(`/api/books/${id}/passages`)).items,
  updateSpine: (id: string, style: SpineStyle) => request<Book>(`/api/books/${id}/spine`, json('PATCH', style)),
  updateBookTitle: (id: string, title: string) => request<Book>(`/api/books/${id}/title`, json('PATCH', { title })),
  deleteBook: (id: string) => request<{ deleted: boolean; book_id: string }>(`/api/books/${id}`, { method: 'DELETE' }),
  importBook: async (form: FormData) => request<{ book: Book; duplicate: boolean; message: string }>('/api/books/import', { method: 'POST', body: form }),
  createSession: (bookId: string, payload: SessionPayload) => request<ReadingSession>(`/api/books/${bookId}/sessions`, json('POST', payload)),
  uploadContextPhoto: (sessionId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<{ id: string; session_id: string; captured_at: string; created_at: string; url: string }>(`/api/reading-sessions/${sessionId}/context-photos`, { method: 'POST', body: form });
  },
  attachContextPhotoCloud: (sessionId: string, payload: { photo_url: string; cloud_path: string }) => {
    const form = new FormData();
    form.append('photo_url', payload.photo_url);
    form.append('cloud_path', payload.cloud_path);
    return request<{ id: string; session_id: string; cloud_path?: string | null; url: string | null }>(`/api/reading-sessions/${sessionId}/context-photos`, { method: 'POST', body: form });
  },
  listSessions: async (bookId: string) => (await request<{ items: ReadingSession[] }>(`/api/books/${bookId}/sessions`)).items,
  listNotes: async (bookId: string) => (await request<{ items: Note[] }>(`/api/books/${bookId}/notes`)).items,
  createNote: (payload: { book_id: string; passage_id: string | null; session_id: string | null; text: string; client_request_id: string }) =>
    request<Note>('/api/notes', json('POST', payload)),
  updateNote: (id: string, text: string, passageId: string | null) => request<Note>(`/api/notes/${id}`, json('PATCH', { text, passage_id: passageId })),
  timeline: async (bookId?: string) => (await request<{ items: TimelineEvent[] }>(`/api/timeline${bookId ? `?book_id=${bookId}` : ''}`)).items,
  photoPath: () => request<PhotoPath>('/api/photo-path'),
  uploadPhoto: (bookId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<{ attempt: PhotoAttempt }>(`/api/books/${bookId}/location-attempts`, { method: 'POST', body: form });
  },
  uploadPhotoCloud: (bookId: string, payload: { photo_url: string; cloud_path: string }) => {
    const form = new FormData();
    form.append('photo_url', payload.photo_url);
    form.append('cloud_path', payload.cloud_path);
    return request<{ attempt: PhotoAttempt }>(`/api/books/${bookId}/location-attempts`, { method: 'POST', body: form });
  },
  confirmPhoto: (attemptId: string, payload: { chosen_anchor: string; started_at: string; ended_at: string; timezone: string; session_type: 'sequential' | 'skip' | 'reread'; sequential_confirmed: boolean; anchor_read_confirmed: boolean; reading_context?: string | null; client_request_id: string }) =>
    request<{ session: ReadingSession; attempt_id: string; message: string }>(`/api/location-attempts/${attemptId}/confirm`, json('POST', payload)),
  ask: (payload: { question: string; book_id?: string | null; mode: 'book' | 'cross_book' | 'history' }) =>
    request<AskResult>('/api/ask', json('POST', payload)),
  evidence: (payload: { question: string; book_id?: string | null; mode: 'book' | 'cross_book' | 'history' }) =>
    request<{ items: EvidenceItem[] }>('/api/evidence', json('POST', payload)),
  socraticStart: (payload: { book_id: string; rounds: number; engine: 'byok' | 'cloud'; client_request_id?: string }) =>
    request<SocraticSessionView>('/api/socratic/start', json('POST', payload)),
  socraticList: async () => (await request<{ items: SocraticSessionSummary[] }>('/api/socratic')).items,
  socraticDetail: (id: string) => request<SocraticSessionView>(`/api/socratic/${id}`),
  socraticAnswer: (id: string, turnIndex: number, answer: string) =>
    request<SocraticSessionView>(`/api/socratic/${id}/answer`, json('POST', { turn_index: turnIndex, answer })),
  socraticGenerate: (id: string, raw?: string) =>
    request<SocraticSessionView>(`/api/socratic/${id}/generate`, json('POST', raw ? { raw } : {})),
  socraticFinish: (id: string, raw?: string) =>
    request<SocraticSessionView>(`/api/socratic/${id}/finish`, json('POST', raw ? { raw } : {})),
  me: () => request<{ user: User; auth_required: boolean }>('/api/auth/me'),
  login: (payload: { username: string; password: string }) => request<{ user: User }>('/api/auth/login', json('POST', payload)),
  register: (payload: { invite_code: string; username: string; password: string }) => request<{ user: User }>('/api/auth/register', json('POST', payload)),
  logout: () => request<{ logged_out: boolean }>('/api/auth/logout', { method: 'POST' }),
  connections: async () => (await request<{ items: AIConnection[] }>('/api/ai/connections')).items,
  createConnection: (payload: { connection_id?: string; alias: string; provider_type: ProviderType; model_id: string; base_url: string; scenario?: MockScenario | null; api_key?: string | null }) =>
    request<AIConnection>('/api/ai/connections', json('POST', payload)),
  verifyConnection: (id: string) => request<{ capabilities: Capabilities }>(`/api/ai/connections/${id}/verify`, { method: 'POST' }),
  revokeConnection: (id: string) => request<{ revoked: boolean }>(`/api/ai/connections/${id}/revoke`, { method: 'POST' }),
  getRoutes: async () => (await request<{ routes: Record<string, string> }>('/api/ai/task-routes')).routes,
  saveRoutes: (routes: Record<string, string>) => request<{ routes: Record<string, string> }>('/api/ai/task-routes', json('PUT', { routes })),
};
