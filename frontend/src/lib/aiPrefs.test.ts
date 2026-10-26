import { beforeEach, describe, expect, it } from 'vitest';

import { loadAiPrefs, saveAiPrefs } from './aiPrefs';

describe('aiPrefs 本地偏好', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('无存储时返回默认值，且默认允许未登录调用云端 AI', () => {
    const prefs = loadAiPrefs();
    expect(prefs).toEqual({ engine: 'byok', modelId: '', allowAnonymousCloud: true });
  });

  it('保存后可以读回，且未指定的字段保持不变', () => {
    saveAiPrefs({ engine: 'cloud', modelId: 'model-a' });
    let prefs = loadAiPrefs();
    expect(prefs.engine).toBe('cloud');
    expect(prefs.modelId).toBe('model-a');
    expect(prefs.allowAnonymousCloud).toBe(true);

    saveAiPrefs({ allowAnonymousCloud: false });
    prefs = loadAiPrefs();
    expect(prefs.engine).toBe('cloud');
    expect(prefs.modelId).toBe('model-a');
    expect(prefs.allowAnonymousCloud).toBe(false);
  });

  it('损坏或异常数据回退到安全默认值', () => {
    window.localStorage.setItem('yueji.cloud-ai.prefs.v1', '{not json');
    expect(loadAiPrefs().allowAnonymousCloud).toBe(true);

    window.localStorage.setItem('yueji.cloud-ai.prefs.v1', JSON.stringify({ engine: 'unknown', modelId: 42, allowAnonymousCloud: 'yes' }));
    const prefs = loadAiPrefs();
    expect(prefs.engine).toBe('byok');
    expect(prefs.modelId).toBe('');
    expect(prefs.allowAnonymousCloud).toBe(true);
  });
});
