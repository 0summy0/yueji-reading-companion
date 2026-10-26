import { useCallback, useEffect, useState } from 'react';
import { Books, ChatCircle, ClockCounterClockwise, CloudArrowUp, GearSix, Leaf, SignOut } from '@phosphor-icons/react';
import type { Book, User } from './types';
import { api, ApiError } from './lib/api';
import { AskPage } from './components/AskPage';
import { AuthPage } from './components/AuthPage';
import { Bookshelf } from './components/Bookshelf';
import { CloudPage } from './components/CloudPage';
import { Journal } from './components/Journal';
import { Settings } from './components/Settings';
import { TimelinePage } from './components/TimelinePage';

type View = { name: 'library' } | { name: 'journal'; bookId: string } | { name: 'timeline' } | { name: 'ask' } | { name: 'cloud' } | { name: 'settings' };

function viewFromHash(): View {
  const hash = window.location.hash;
  if (hash.startsWith('#book/')) return { name: 'journal', bookId: hash.slice(6) };
  if (hash === '#timeline') return { name: 'timeline' };
  if (hash === '#ask') return { name: 'ask' };
  if (hash === '#cloud') return { name: 'cloud' };
  if (hash === '#settings') return { name: 'settings' };
  return { name: 'library' };
}

export default function App() {
  const [view, setView] = useState<View>(viewFromHash);
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);
  const [authUser, setAuthUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [toast, setToast] = useState<{ message: string; tone: 'success' | 'error' } | null>(null);

  const notify = useCallback((message: string, tone: 'success' | 'error' = 'success') => {
    setToast({ message, tone });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 4200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    api.me().then((result) => setAuthUser(result.user)).catch(() => setAuthUser(null)).finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    const change = () => setView(viewFromHash());
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);

  const refreshBooks = useCallback(async (message?: string) => {
    try {
      const result = await api.listBooks();
      setBooks(result.items);
      if (message) notify(message);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) setAuthUser(null);
      notify(reason instanceof Error ? reason.message : '书房连接失败', 'error');
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    if (authChecked && authUser) void refreshBooks();
  }, [authChecked, authUser, refreshBooks]);

  function navigate(next: View) {
    setView(next);
    const hash = next.name === 'journal' ? `#book/${next.bookId}` : next.name === 'library' ? '' : `#${next.name}`;
    if (window.location.hash !== hash) window.location.hash = hash;
    window.scrollTo({ top: 0, behavior: 'auto' });
  }

  async function logout() {
    try {
      await api.logout();
    } finally {
      setAuthUser(null);
      setBooks([]);
      navigate({ name: 'library' });
    }
  }

  if (!authChecked) {
    return <main className="app-loading" aria-label="正在打开阅迹"><span /><span /><span /></main>;
  }
  if (!authUser) {
    return <AuthPage onAuth={setAuthUser} />;
  }

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content" onClick={(event) => {
        event.preventDefault();
        document.getElementById('main-content')?.focus();
      }}>跳到主要内容</a>
      <header className="site-header">
        <button className="brand" onClick={() => navigate({ name: 'library' })} aria-label="阅迹首页">
          <span className="brand-mark"><Leaf size={21} /></span><span><strong>阅迹</strong><small>持续性纸质书阅读伴侣</small></span>
        </button>
        <nav aria-label="主导航">
          <button className={view.name === 'library' || view.name === 'journal' ? 'active' : ''} onClick={() => navigate({ name: 'library' })}><Books size={18} />书房</button>
          <button className={view.name === 'timeline' ? 'active' : ''} onClick={() => navigate({ name: 'timeline' })}><ClockCounterClockwise size={18} />时间线</button>
          <button className={view.name === 'ask' ? 'active' : ''} onClick={() => navigate({ name: 'ask' })}><ChatCircle size={18} />提问</button>
          <button className={view.name === 'cloud' ? 'active' : ''} onClick={() => navigate({ name: 'cloud' })}><CloudArrowUp size={18} />云服务</button>
          <button className={view.name === 'settings' ? 'active' : ''} onClick={() => navigate({ name: 'settings' })}><GearSix size={18} />AI 设置</button>
        </nav>
        <div className="account-status"><div><strong>{authUser.display_name || authUser.username}</strong><small>邀请制试用账号</small></div><button className="icon-button" aria-label="退出登录" onClick={() => void logout()}><SignOut size={17} /></button></div>
      </header>
      <div id="main-content" tabIndex={-1} key={authUser.id}>
        {view.name === 'library' && <Bookshelf books={books} loading={loading} onOpen={(bookId) => navigate({ name: 'journal', bookId })} onChanged={(message) => void refreshBooks(message)} notify={notify} />}
        {view.name === 'journal' && <Journal key={view.bookId} bookId={view.bookId} onBack={() => navigate({ name: 'library' })} onLibraryChanged={() => void refreshBooks()} notify={notify} />}
        {view.name === 'timeline' && <TimelinePage books={books} notify={notify} />}
        {view.name === 'ask' && <AskPage books={books} notify={notify} />}
        {view.name === 'cloud' && <CloudPage books={books} notify={notify} />}
        {view.name === 'settings' && <Settings notify={notify} />}
      </div>
      <footer className="site-footer"><span>阅迹 · 真实 API 试用版</span><span>原文是证据，原话属于你，AI 只作可审核的解释。</span></footer>
      {toast && <div className={`toast toast-${toast.tone}`} role="status" aria-live="polite">{toast.message}<button aria-label="关闭提示" onClick={() => setToast(null)}>×</button></div>}
    </div>
  );
}
