import { useCallback, useEffect, useState } from 'react';
import { ArrowsClockwise, Camera, Eye, EyeSlash, FloppyDisk, Key, ShieldCheck, Trash } from '@phosphor-icons/react';
import type { AIConnection, Capabilities, MockScenario, ProviderType } from '../types';
import { api } from '../lib/api';
import { capabilityStatusLabel, formatDate } from '../lib/format';
import { CloudAiConfig } from './CloudAiConfig';

const scenarios: { value: MockScenario; label: string; description: string }[] = [
  { value: 'success', label: '三项模拟通过', description: '文字、随机图片挑战和中文书页均符合校验。' },
  { value: 'unsupported', label: '明确不支持图片', description: '文字可用，图片接口明确拒绝输入。' },
  { value: 'hallucinated', label: '假装识图并答错', description: '请求成功但随机答案错误，状态为未能确认。' },
  { value: 'partial', label: '视觉通过，中文读字不足', description: '图片挑战通过，中文书页缺行，状态为部分通过。' },
  { value: 'auth_error', label: '模拟鉴权失败', description: '401/403 类错误，不误判成不支持图片。' },
  { value: 'rate_limited', label: '模拟限流或配额不足', description: '429 类错误，提供重试而非能力定论。' },
  { value: 'timeout', label: '模拟网络超时', description: '网络类错误，三项均为暂无法验证。' },
];

const providerPresets = [
  { id: 'deepseek', label: 'DeepSeek 官方（推荐）', base_url: 'https://api.deepseek.com', model_id: 'deepseek-flash' },
  { id: 'openai', label: 'OpenAI 官方', base_url: 'https://api.openai.com/v1', model_id: 'gpt-4o-mini' },
];

const taskLabels: Record<string, string> = {
  generate_text: '文字问答', analyze_image: '拍照识别', extract_structured: '知识提取（阶段3）',
  embed_text: '向量生成', ocr_page: '独立 OCR',
};

function providerLabel(connection: AIConnection): string {
  if (connection.provider_type === 'mock') {
    return `Mock · ${scenarios.find((item) => item.value === connection.scenario)?.label || '模拟'}`;
  }
  return `OpenAI-compatible · ${connection.base_url}`;
}

function CapabilityLedger({ capabilities, providerType }: { capabilities: Capabilities | null; providerType: AIConnection['provider_type'] }) {
  if (!capabilities) return <p className="muted">尚未执行检测。</p>;
  const simulated = capabilities.simulated ?? providerType === 'mock';
  const rows = [
    ['文字对话', capabilities.text, simulated ? '只说明模拟文本返回符合校验。' : '真实极短文字任务，只代表当前连接可用。'],
    ['图片输入', capabilities.vision_input, simulated ? '随机答案不在提示词中；答错不会判为通过。' : '真实随机图片挑战；答案只在服务端内存。'],
    ['中文读字', capabilities.page_ocr, simulated ? '独立核对两行顺序与随机标识。' : '真实渲染中文书页；与图片输入分开判定。'],
  ] as const;
  return (
    <div className="capability-ledger">
      {rows.map(([label, detail, note]) => (
        <div className="capability-row" key={label}>
          <div><strong>{label}</strong><small>{note}</small></div>
          <span className={`status-badge status-${detail.status}`}>{capabilityStatusLabel(detail.status, simulated)}</span>
          <p>{detail.message}</p>
        </div>
      ))}
      <p className="checked-at">检测时间 {formatDate(capabilities.checked_at)} · {capabilities.probe_version || 'synthetic-vision-v2'} · {simulated ? 'Mock' : '真实 HTTP'}</p>
    </div>
  );
}

export function Settings({ notify }: { notify: (message: string, tone?: 'success' | 'error') => void }) {
  const [connections, setConnections] = useState<AIConnection[]>([]);
  const [routes, setRoutes] = useState<Record<string, string>>({});
  const [providerType, setProviderType] = useState<ProviderType>('openai_compatible');
  const [preset, setPreset] = useState('deepseek');
  const [alias, setAlias] = useState('我的 DeepSeek 连接');
  const [modelId, setModelId] = useState('deepseek-flash');
  const [baseUrl, setBaseUrl] = useState('https://api.deepseek.com');
  const [apiKey, setApiKey] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [scenario, setScenario] = useState<MockScenario>('success');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [routesBusy, setRoutesBusy] = useState(false);
  const [verifyId, setVerifyId] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setError('');
      const [connectionData, routeData] = await Promise.all([api.connections(), api.getRoutes()]);
      setConnections(connectionData);
      setRoutes(routeData);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '设置读取失败');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function connect(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const payload: Parameters<typeof api.createConnection>[0] = {
        connection_id: editingId || undefined,
        alias,
        provider_type: providerType,
        model_id: modelId,
        base_url: providerType === 'mock' ? 'mock://local' : baseUrl,
        scenario: providerType === 'mock' ? scenario : null,
      };
      if (providerType === 'openai_compatible') payload.api_key = apiKey || null;
      await api.createConnection(payload);
      notify(editingId ? '配置已更新，旧结果失效并完成重新检测' : providerType === 'mock' ? 'Mock 连接已保存并完成检测' : '真实连接已加密保存，并完成三项真实检测（会产生少量 API 费用）');
      setEditingId(null);
      setApiKey('');
      await load();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '连接失败', 'error');
    } finally {
      setBusy(false);
    }
  }

  async function verify(id: string) {
    setVerifyId(id);
    try {
      await api.verifyConnection(id);
      notify('已重新执行三项检测');
      await load();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '重新检测失败', 'error');
    } finally {
      setVerifyId(null);
    }
  }

  async function revoke(connection: AIConnection) {
    if (revokingId) return;
    const credentialNote = connection.provider_type === 'openai_compatible' ? '、加密凭据引用' : '';
    if (!window.confirm(`移除“${connection.alias}”及其检测缓存${credentialNote}？原始笔记不会受影响。`)) return;
    setRevokingId(connection.id);
    try {
      await api.revokeConnection(connection.id);
      notify('连接已移除，手账数据保持不变');
      await load();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '移除失败', 'error');
    } finally {
      setRevokingId(null);
    }
  }

  function editConnection(connection: AIConnection) {
    setEditingId(connection.id);
    setProviderType(connection.provider_type);
    setPreset(providerPresets.find((item) => item.base_url === connection.base_url && item.model_id === connection.model_id)?.id || 'custom');
    setAlias(connection.alias);
    setModelId(connection.model_id);
    setBaseUrl(connection.base_url);
    setScenario(connection.scenario || 'success');
    setApiKey('');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function saveRoutes() {
    if (routesBusy) return;
    setRoutesBusy(true);
    try {
      const cleaned = Object.fromEntries(Object.entries(routes).filter(([, value]) => value));
      const saved = await api.saveRoutes(cleaned);
      setRoutes(saved.routes);
      notify('任务路由已保存；私人照片只发送到你选择的已验证连接');
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '路由保存失败', 'error');
    } finally {
      setRoutesBusy(false);
    }
  }

  return (
    <main className="settings-page page-shell">
      <div className="settings-heading"><p className="eyebrow">BYOK · 可选 AI 工具</p><h1>AI 设置</h1><p className="lede">填写你自己的模型服务商与 Key。未配置时书架、进度、原话、阅读情境和照片手动兜底仍然完整可用。</p></div>
      <div className="simulation-banner real-banner" role="note"><ShieldCheck size={22} /><div><strong>真实连接只由后端调用</strong><p>API Key 使用服务端主密钥加密保存，不回传、不写入 localStorage 或日志。连接/更换模型后会真实执行文字、随机图片、中文书页三项检测；探针只发送程序合成图片。真实检测会产生少量 API 费用。</p></div></div>

      <CloudAiConfig notify={notify} />

      <section className="connection-composer">
        <div className="section-heading"><div><p className="eyebrow">REAL CONNECTION</p><h2>{editingId ? '更换模型并重新检测' : '连接并检测'}</h2></div>{editingId && <button className="inline-action" onClick={() => setEditingId(null)}>取消编辑</button>}</div>
        <form onSubmit={connect} className="connection-form">
          <label>服务商预设
            <select value={preset} onChange={(e) => {
              const next = providerPresets.find((item) => item.id === e.target.value);
              setPreset(e.target.value);
              if (next) {
                setProviderType('openai_compatible');
                setAlias(next.label.includes('DeepSeek') ? '我的 DeepSeek 连接' : '我的 OpenAI 连接');
                setBaseUrl(next.base_url);
                setModelId(next.model_id);
              }
            }}>
              {providerPresets.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              <option value="custom">自定义</option>
            </select>
          </label>
          <label>Provider
            <select value={providerType} onChange={(e) => setProviderType(e.target.value as ProviderType)}>
              <option value="openai_compatible">OpenAI-compatible（真实 HTTP）</option>
              <option value="mock">Mock（仅开发演示）</option>
            </select>
          </label>
          <label>连接名称<input required maxLength={60} value={alias} onChange={(e) => setAlias(e.target.value)} /></label>
          <label>模型 ID<input required maxLength={120} value={modelId} onChange={(e) => setModelId(e.target.value)} placeholder="例如 gpt-4o-mini / deepseek-chat" /></label>
          {providerType === 'openai_compatible' ? (
            <>
              <label>HTTPS Base URL<input required type="url" maxLength={300} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com" /></label>
              <label className="key-field">API Key
                <div className="key-input"><Key size={17} /><input type={showApiKey ? 'text' : 'password'} aria-label="API Key" autoComplete="new-password" maxLength={4096} autoCapitalize="none" spellCheck={false} value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={editingId ? '留空则保留已保存的 Key' : '只发送到后端，浏览器不会保存'} /><button type="button" className="reveal-button" aria-label={showApiKey ? '隐藏 API Key' : '显示 API Key'} aria-pressed={showApiKey} onClick={() => setShowApiKey((value) => !value)}>{showApiKey ? <EyeSlash size={18} /> : <Eye size={18} />}</button></div>
                <p className="field-hint">Key 是一长串随机字符，粘贴后可以点眼睛核对是否完整。</p>
              </label>
              <p className="scenario-description">管理员只允许常见官方/兼容 API 域名；服务端会校验 HTTPS、端口、DNS 公网地址并禁止重定向。</p>
            </>
          ) : (
            <>
              <label>Base URL<input value="mock://local" disabled aria-readonly="true" /></label>
              <label className="scenario-field">演示情形
                <select value={scenario} onChange={(e) => setScenario(e.target.value as MockScenario)}>{scenarios.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
              </label>
              <p className="scenario-description"><strong>模拟检测，不代表真实API能力。</strong>{scenarios.find((item) => item.value === scenario)?.description}</p>
            </>
          )}
          <button className="button primary" disabled={busy || routesBusy} type="submit"><ArrowsClockwise size={18} />{busy ? '正在逐项检测…' : editingId ? '保存并重新检测' : '连接并检测'}</button>
        </form>
      </section>

      <section className="connections-section">
        <div className="section-heading"><div><p className="eyebrow">SEPARATE RESULTS</p><h2>连接与三项结果</h2></div><span>{connections.length} 个连接</span></div>
        {loading && <div className="journal-skeleton" />}
        {!loading && error && <div className="retry-row"><p className="form-error" role="alert">{error}</p><button className="button secondary" onClick={() => void load()}>重试</button></div>}
        {!loading && !connections.length && <div className="empty-inline"><Camera size={25} /><p>尚未配置。你仍可以导入图书、记录进度、阅读情境和写笔记。</p></div>}
        {connections.map((connection) => (
          <article className="connection-entry" key={connection.id} data-testid={`connection-${connection.id}`}>
            <header><div><h3>{connection.alias}</h3><p>{connection.model_id} · {providerLabel(connection)}{connection.provider_type === 'openai_compatible' ? ` · ${connection.has_saved_key ? 'Key 已加密保存' : '未保存 Key'}` : ''}</p></div>
              <div className="button-row"><button className="button secondary" disabled={verifyId === connection.id} onClick={() => void verify(connection.id)}><ArrowsClockwise size={16} />{verifyId === connection.id ? '检测中…' : '重新检测'}</button><button className="button text-button" onClick={() => editConnection(connection)}>更换图片模型</button><button className="icon-button" aria-label={`移除 ${connection.alias}`} disabled={revokingId === connection.id} onClick={() => void revoke(connection)}><Trash size={17} /></button></div>
            </header>
            <CapabilityLedger capabilities={connection.capabilities} providerType={connection.provider_type} />
          </article>
        ))}
      </section>

      <section className="routes-section">
        <div className="section-heading"><div><p className="eyebrow">TASK ROUTES</p><h2>按任务选择 Provider</h2></div></div>
        <p className="muted">聊天、视觉、结构化和向量接口相互独立。私人照片只会发给“拍照识别”或“独立 OCR”当前选中的已验证连接，不会静默换供应商。</p>
        <div className="route-list">
          {Object.entries(taskLabels).map(([task, label]) => <label key={task}>{label}<select disabled={routesBusy || loading} value={routes[task] || ''} onChange={(e) => setRoutes((old) => ({ ...old, [task]: e.target.value }))}><option value="">不配置</option>{connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.alias} · {connection.model_id}</option>)}</select></label>)}
        </div>
        <button className="button secondary" disabled={routesBusy || loading} onClick={() => void saveRoutes()}><FloppyDisk size={17} />{routesBusy ? '保存中…' : '保存任务路由'}</button>
      </section>
    </main>
  );
}
