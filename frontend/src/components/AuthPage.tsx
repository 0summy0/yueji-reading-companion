import { useState } from 'react';
import { Eye, EyeSlash, Key, Leaf, UserPlus } from '@phosphor-icons/react';
import type { User } from '../types';
import { api } from '../lib/api';

export function AuthPage({ onAuth }: { onAuth: (user: User) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [inviteCode, setInviteCode] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  function switchMode(next: 'login' | 'register') {
    setMode(next);
    setError('');
    setPassword('');
    setShowPassword(false);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const cleanUsername = username.trim();
      const cleanInvite = inviteCode.trim();
      const result = mode === 'login'
        ? await api.login({ username: cleanUsername, password })
        : await api.register({ invite_code: cleanInvite, username: cleanUsername, password });
      onAuth(result.user);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="auth-brand"><span><Leaf size={24} /></span><div><strong>阅迹</strong><small>同学试用版</small></div></div>
        <h1>{mode === 'login' ? '回到书房' : '用邀请码开始'}</h1>
        <p className="muted">{mode === 'login' ? '每个账号都有独立书架、手账和 AI 连接。' : '只接受邀请注册；你的数据不会进入其他同学的账号。'}</p>
        <div className="auth-tabs" role="tablist" aria-label="登录或注册">
          <button role="tab" aria-selected={mode === 'login'} onClick={() => switchMode('login')}>登录</button>
          <button role="tab" aria-selected={mode === 'register'} onClick={() => switchMode('register')}>邀请注册</button>
        </div>
        <form onSubmit={submit} className="stack-form">
          {mode === 'register' && (
            <>
              <label className="field-label" htmlFor="invite-code">邀请码</label>
              <input
                id="invite-code"
                required
                maxLength={120}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                placeholder="向试用管理员索取"
              />
              <p className="field-hint">区分大小写，通常是大写，例如 YJ-CLASS；粘贴或输入时不要带空格。</p>
            </>
          )}
          <label className="field-label" htmlFor="auth-username">用户名</label>
          <input
            id="auth-username"
            required
            maxLength={30}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="2-30 位中文、字母、数字、下划线或短横线"
          />
          <label className="field-label" htmlFor="auth-password">密码</label>
          <div className="password-field">
            <input
              id="auth-password"
              required
              type={showPassword ? 'text' : 'password'}
              maxLength={128}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              autoCapitalize="none"
              spellCheck={false}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === 'register' ? '10-128 位，不要使用常见密码' : '输入密码'}
            />
            <button
              type="button"
              className="reveal-button"
              aria-label={showPassword ? '隐藏密码' : '显示密码'}
              aria-pressed={showPassword}
              onClick={() => setShowPassword((value) => !value)}
            >
              {showPassword ? <EyeSlash size={18} /> : <Eye size={18} />}
            </button>
          </div>
          {mode === 'register' && (
            <p className="field-hint">点击右侧眼睛可以随时核对输入的密码。</p>
          )}
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="button primary" disabled={busy} type="submit">{busy ? '正在验证…' : mode === 'login' ? '登录书房' : '创建试用账号'}</button>
        </form>
        <p className="auth-note"><Key size={15} /> 忘记密码或需要邀请码，请联系试用管理员；系统不会公开注册。<UserPlus size={15} className="auth-note-second" /></p>
      </section>
    </main>
  );
}
