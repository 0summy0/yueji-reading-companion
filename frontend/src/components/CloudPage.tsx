import { useCallback, useEffect, useState } from 'react';
import type { CloudSession } from '@tencent-ai/workbuddy-cloud-sdk';
import { CloudArrowUp, CloudCheck, Database, EnvelopeSimple, Images, Leaf, ShieldCheck, SignOut, Trash } from '@phosphor-icons/react';

import type { Book } from '../types';
import { api } from '../lib/api';
import {
  createBackup,
  deleteBackup,
  getBackup,
  getCloudSession,
  listBackups,
  listCloudModels,
  listCloudPhotos,
  probeCloudStorage,
  sendEmailCode,
  signOutCloud,
  verifyEmailCode,
  type CloudBackupMeta,
} from '../cloud/cloudService';

export function CloudPage({ books, notify }: { books: Book[]; notify: (message: string, tone?: 'success' | 'error') => void }) {
  const [session, setSession] = useState<CloudSession | null>(null);
  const [sessionLoading, setSessionLoading] = useState(true);

  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [pending, setPending] = useState<{ verificationId: string; isExistingUser: boolean; email: string } | null>(null);
  const [codeSent, setCodeSent] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState('');

  const [modelCount, setModelCount] = useState<number | null>(null);
  const [photoCount, setPhotoCount] = useState<number | null>(null);
  const [probeState, setProbeState] = useState<'idle' | 'running' | 'ok' | 'failed'>('idle');

  const [backupLabel, setBackupLabel] = useState('');
  const [backups, setBackups] = useState<CloudBackupMeta[]>([]);
  const [backupBusy, setBackupBusy] = useState(false);

  const refreshBackups = useCallback(async () => {
    try {
      setBackups(await listBackups());
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '读取云备份失败', 'error');
    }
  }, [notify]);

  useEffect(() => {
    getCloudSession()
      .then((current) => setSession(current))
      .catch(() => setSession(null))
      .finally(() => setSessionLoading(false));
  }, []);

  useEffect(() => {
    if (!session) return;
    void refreshBackups();
    listCloudModels().then((models) => setModelCount(models.length)).catch(() => setModelCount(null));
    listCloudPhotos(session.user.id).then((photos) => setPhotoCount(photos.length)).catch(() => setPhotoCount(null));
  }, [session, refreshBackups]);

  useEffect(() => {
    if (!countdown) return;
    const timer = window.setTimeout(() => setCountdown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [countdown]);

  async function handleSendCode() {
    const trimmed = email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
      setAuthError('请输入正确的邮箱地址');
      return;
    }
    setAuthBusy(true);
    setAuthError('');
    try {
      const challenge = await sendEmailCode(trimmed);
      setPending({ verificationId: challenge.verificationId, isExistingUser: challenge.isExistingUser, email: trimmed });
      setCodeSent(true);
      setCountdown(60);
    } catch (reason) {
      setAuthError(reason instanceof Error ? reason.message : '验证码发送失败');
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleVerify() {
    if (!pending) {
      setAuthError('请先获取邮箱验证码');
      return;
    }
    if (!code.trim()) {
      setAuthError('请输入收到的验证码');
      return;
    }
    setAuthBusy(true);
    setAuthError('');
    try {
      const next = await verifyEmailCode({ ...pending, token: code.trim() });
      setSession(next);
      setPending(null);
      setCode('');
      setCodeSent(false);
      notify('云端身份已登录');
    } catch (reason) {
      setAuthError(reason instanceof Error ? reason.message : '验证码校验失败');
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleSignOut() {
    try {
      await signOutCloud();
      setSession(null);
      setBackups([]);
      setModelCount(null);
      setPhotoCount(null);
      notify('已退出云端身份');
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '退出失败', 'error');
    }
  }

  async function handleProbe() {
    if (!session) return;
    setProbeState('running');
    try {
      await probeCloudStorage(session.user.id);
      setProbeState('ok');
    } catch (reason) {
      setProbeState('failed');
      notify(reason instanceof Error ? reason.message : '云存储自检失败', 'error');
    }
  }

  async function handleBackup() {
    if (!session) return;
    const label = backupLabel.trim() || `书房备份 ${new Date().toLocaleString('zh-CN')}`;
    setBackupBusy(true);
    try {
      const [notes, sessions] = await Promise.all([
        Promise.all(books.map((book) => api.listNotes(book.id).catch(() => []))),
        Promise.all(books.map((book) => api.listSessions(book.id).catch(() => []))),
      ]);
      const payload = {
        version: 1,
        app: '阅迹同学试用版',
        exported_at: new Date().toISOString(),
        books: books.map((book, index) => ({
          id: book.id,
          title: book.title,
          author: book.author,
          format: book.format,
          spine_style: book.spine_style,
          progress: book.progress,
          notes: notes[index],
          sessions: sessions[index],
        })),
      };
      await createBackup(label, payload, session.user.name ?? null);
      setBackupLabel('');
      notify('书房已备份到云端');
      await refreshBackups();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '备份失败', 'error');
    } finally {
      setBackupBusy(false);
    }
  }

  async function handleDownload(backup: CloudBackupMeta) {
    try {
      const row = await getBackup(backup.id);
      const blob = new Blob([JSON.stringify(row.payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `yueji-backup-${backup.id}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '下载备份失败', 'error');
    }
  }

  async function handleDelete(backup: CloudBackupMeta) {
    try {
      await deleteBackup(backup.id);
      notify('云备份已删除');
      await refreshBackups();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '删除备份失败', 'error');
    }
  }

  if (sessionLoading) {
    return <main className="page-shell"><div className="app-loading" aria-label="正在连接云服务"><span /><span /><span /></div></main>;
  }

  if (!session) {
    return (
      <main className="cloud-page page-shell">
        <div className="settings-heading">
          <p className="eyebrow">WORKBUDDY CLOUD</p>
          <h1>云服务</h1>
          <p className="lede">用邮箱登录一个云端身份，即可使用云备份、云相册与免密钥云端问答。云端身份与书房账号相互独立，只用于云服务，不影响你的阅读数据归属。</p>
        </div>
        <section className="journal-paper cloud-auth-card">
          <div className="cloud-auth-intro"><ShieldCheck size={30} /><div><h2>邮箱验证码登录</h2><p>不需要密码；新邮箱首次验证通过即自动创建云端账号。验证码将发送到该邮箱。</p></div></div>
          <form
            className="record-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (authBusy) return;
              // 未发送验证码时回车先发码，已发送则回车直接登录，符合「回车就是继续」的直觉。
              void (codeSent ? handleVerify() : handleSendCode());
            }}
          >
            <label>邮箱地址
              <input type="email" value={email} maxLength={120} autoComplete="email" autoCapitalize="none" spellCheck={false} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
            </label>
            <div className="button-row">
              <button type="button" className="button secondary" disabled={authBusy || countdown > 0} onClick={() => void handleSendCode()}>
                <EnvelopeSimple size={16} />{countdown > 0 ? `重新发送（${countdown}s）` : codeSent ? '重新发送验证码' : '获取验证码'}
              </button>
            </div>
            {codeSent && (
              <label>验证码
                <input type="text" inputMode="numeric" value={code} maxLength={6} autoComplete="one-time-code" pattern="[0-9]*" onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))} placeholder="6 位数字" />
              </label>
            )}
            {authError && <p className="form-error" role="alert">{authError}</p>}
            <button type="button" className="button primary" disabled={authBusy || !codeSent} onClick={() => void handleVerify()}>
              <CloudCheck size={17} />登录云端身份
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="cloud-page page-shell">
      <div className="settings-heading">
        <p className="eyebrow">WORKBUDDY CLOUD</p>
        <h1>云服务</h1>
        <p className="lede">数据保存在本应用独立的云端环境中；只有你的云端身份可以读写，其他试用同学无法看到。</p>
      </div>
      <div className="cloud-grid">
        <section className="journal-paper cloud-card">
          <div className="cloud-card-head"><Leaf size={20} /><h2>云端身份</h2></div>
          <p>已登录：<strong>{session.user.email ?? session.user.name ?? '云端用户'}</strong></p>
          <p className="muted">身份 ID：{session.user.id.slice(0, 6)}…{session.user.id.slice(-4)}（仅用于云端数据隔离）</p>
          <button type="button" className="button text-button" onClick={() => void handleSignOut()}><SignOut size={15} />退出云端身份</button>
        </section>

        <section className="journal-paper cloud-card">
          <div className="cloud-card-head"><Database size={20} /><h2>云备份</h2></div>
          <p>把书房的书架、笔记与会话打包保存到云端数据库，换设备或重新部署后可取回 JSON 快照。</p>
          <div className="backup-create">
            <input type="text" value={backupLabel} maxLength={60} aria-label="备份名称" onChange={(event) => setBackupLabel(event.target.value)} placeholder={`书房备份 ${new Date().toLocaleDateString('zh-CN')}`} />
            <button type="button" className="button primary" disabled={backupBusy || !books.length} onClick={() => void handleBackup()}>
              <CloudArrowUp size={16} />{backupBusy ? '正在打包上传…' : '立即备份书房'}
            </button>
          </div>
          {!books.length && <p className="muted">书房还没有书，先去「书房」导入或阅读一本。</p>}
          <ul className="backup-list">
            {backups.map((backup) => (
              <li key={backup.id}>
                <div><strong>{backup.label}</strong><small>{new Date(backup.created_at).toLocaleString('zh-CN')}</small></div>
                <div className="button-row">
                  <button type="button" className="button text-button" onClick={() => void handleDownload(backup)}>下载 JSON</button>
                  <button type="button" className="icon-button" aria-label={`删除备份 ${backup.label}`} onClick={() => void handleDelete(backup)}><Trash size={15} /></button>
                </div>
              </li>
            ))}
            {!backups.length && <li className="muted">还没有云备份。</li>}
          </ul>
        </section>

        <section className="journal-paper cloud-card">
          <div className="cloud-card-head"><Images size={20} /><h2>云相册与免密钥问答</h2></div>
          <p>云端照片：<strong>{photoCount === null ? '未知' : `${photoCount} 张`}</strong>（手账照片定位时自动直传，已去 EXIF）</p>
          <p>可用云端模型：<strong>{modelCount === null ? '未知' : `${modelCount} 个`}</strong>（用于「提问」页的免密钥云端问答）</p>
          <div className="button-row">
            <button type="button" className="button secondary" disabled={probeState === 'running'} onClick={() => void handleProbe()}>
              {probeState === 'running' ? '正在自检…' : '运行云存储自检'}
            </button>
            {probeState === 'ok' && <span className="cloud-ok"><CloudCheck size={15} />上传、签名下载、删除全部正常</span>}
            {probeState === 'failed' && <span className="form-error">自检未通过，请查看提示或稍后重试</span>}
          </div>
        </section>
      </div>
    </main>
  );
}
