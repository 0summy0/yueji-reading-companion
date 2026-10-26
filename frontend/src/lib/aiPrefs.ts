/** 云端 AI 使用偏好：只存在本机浏览器，不保存任何密钥。 */
export interface AiPrefs {
  /** 默认回答方式：byok=自带 Key 连接，cloud=云端网关 */
  engine: 'byok' | 'cloud';
  /** 默认云端模型 id */
  modelId: string;
  /** 是否允许在未登录云存储时使用云端 AI（调用 AI 本身不需要登录） */
  allowAnonymousCloud: boolean;
}

const STORAGE_KEY = 'yueji.cloud-ai.prefs.v1';

const DEFAULTS: AiPrefs = { engine: 'byok', modelId: '', allowAnonymousCloud: true };

function safeStore(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function loadAiPrefs(): AiPrefs {
  const store = safeStore();
  if (!store) return { ...DEFAULTS };
  try {
    const raw = store.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw) as Partial<AiPrefs>;
    return {
      engine: parsed.engine === 'cloud' ? 'cloud' : 'byok',
      modelId: typeof parsed.modelId === 'string' ? parsed.modelId : '',
      allowAnonymousCloud: parsed.allowAnonymousCloud !== false,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveAiPrefs(patch: Partial<AiPrefs>): AiPrefs {
  const next = { ...loadAiPrefs(), ...patch };
  const store = safeStore();
  if (store) {
    try {
      store.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // 隐私模式或配额受限时忽略：偏好丢失不影响功能
    }
  }
  return next;
}
