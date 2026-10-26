import { useEffect, useRef, useState } from 'react';
import { CloudCheck, Warning } from '@phosphor-icons/react';

import { cloudErrorMessage, listCloudModels, type CloudModelInfo } from '../cloud/cloudService';
import { loadAiPrefs, saveAiPrefs, type AiPrefs } from '../lib/aiPrefs';

/**
 * WorkBuddy 云端 AI 配置。
 * 要点：调用模型本身只需要应用自身的网关凭据，不要求登录；
 * 登录只影响云备份与云存储（读写你自己的云空间）。
 */
export function CloudAiConfig({ notify }: { notify: (message: string, tone?: 'success' | 'error') => void }) {
  const [prefs, setPrefs] = useState<AiPrefs>(() => loadAiPrefs());
  const [models, setModels] = useState<CloudModelInfo[]>([]);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [error, setError] = useState('');
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  function refresh() {
    setState('loading');
    setError('');
    listCloudModels()
      .then((list) => {
        if (!aliveRef.current) return;
        setModels(list);
        setState('ready');
        const current = loadAiPrefs();
        if (list.length && !list.some((item) => item.id === current.modelId)) {
          update({ modelId: list[0].id });
        }
      })
      .catch((reason) => {
        if (!aliveRef.current) return;
        setState('failed');
        setError(cloudErrorMessage(reason, '云端模型目录读取失败'));
      });
  }

  useEffect(refresh, []);

  function update(patch: Partial<AiPrefs>) {
    const next = saveAiPrefs(patch);
    setPrefs(next);
    return next;
  }

  function pickModel(modelId: string) {
    update({ modelId });
    const model = models.find((item) => item.id === modelId);
    notify(`云端默认模型已设为 ${model?.label ?? modelId}`);
  }

  return (
    <section className="cloud-ai-section" aria-label="WorkBuddy 云端 AI 配置">
      <header className="cloud-ai-head">
        <CloudCheck size={26} />
        <div>
          <h2>WorkBuddy 云端 AI</h2>
          <p className="muted">调用模型只需要本应用的网关凭据，<b>不需要邮箱登录</b>；登录只影响云备份与云存储。</p>
        </div>
        <span className={`cloud-ai-badge ${state === 'ready' ? 'ok' : state === 'loading' ? 'pending' : 'bad'}`}>
          {state === 'ready' ? `可用 · ${models.length} 个模型` : state === 'loading' ? '正在探测…' : '不可用'}
        </span>
      </header>

      <div className="cloud-ai-grid">
        <label>默认回答方式
          <select value={prefs.engine} onChange={(event) => {
            update({ engine: event.target.value as AiPrefs['engine'] });
            notify(`提问与书格拉底默认使用${event.target.value === 'cloud' ? '云端 AI' : '你自己的 AI 连接'}`);
          }}>
            <option value="byok">我的 AI 连接（自带 Key）</option>
            <option value="cloud">云端 AI（免密钥）</option>
          </select>
        </label>
        <label>默认云端模型
          <select value={prefs.modelId} disabled={!models.length} onChange={(event) => pickModel(event.target.value)}>
            {models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}
            {!models.length && <option value="">{state === 'loading' ? '正在读取…' : '暂无可用模型'}</option>}
          </select>
        </label>
      </div>

      <label className="cloud-ai-toggle">
        <input type="checkbox" checked={prefs.allowAnonymousCloud} onChange={(event) => {
          update({ allowAnonymousCloud: event.target.checked });
          notify(event.target.checked ? '未登录云存储时也能调用云端 AI' : '已改为：需要先登录云端身份才能调用云端 AI');
        }} />
        <span>允许在未登录云存储时使用云端 AI（默认开启；关闭后需先在「云服务」页登录）</span>
      </label>

      {state === 'failed' && (
        <div className="form-error" role="alert">
          <Warning size={15} /> {error}
          <button className="button text-button" onClick={refresh}>重试</button>
        </div>
      )}
      {state === 'ready' && !models.length && (
        <p className="muted"><Warning size={15} /> 云端模型目录为空，请稍后重试；期间仍可使用自带 Key 的 AI 连接。</p>
      )}
    </section>
  );
}
