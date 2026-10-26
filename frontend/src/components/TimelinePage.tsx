import { useEffect, useMemo, useState } from 'react';
import type { Book, TimelineEvent } from '../types';
import { api } from '../lib/api';
import { TimelineList } from './Timeline';

export function TimelinePage({ books, notify }: { books: Book[]; notify: (message: string, tone?: 'success' | 'error') => void }) {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [bookId, setBookId] = useState('');
  const [kind, setKind] = useState('');
  const [direction, setDirection] = useState<'newest' | 'oldest'>('newest');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.timeline().then(setEvents).catch((reason) => notify(reason instanceof Error ? reason.message : '时间线读取失败', 'error')).finally(() => setLoading(false));
  }, [notify]);

  const visible = useMemo(() => {
    const filtered = events.filter((event) => (!bookId || event.book_id === bookId) && (!kind || event.kind === kind));
    return direction === 'newest' ? filtered : [...filtered].reverse();
  }, [events, bookId, kind, direction]);

  return (
    <main className="page-shell timeline-page">
      <p className="eyebrow">FACTS BEFORE INTERPRETATION</p><h1>阅读时间线</h1>
      <p className="lede">这里只展示你亲自保存的会话与原话。未来 AI 卡片会另标来源，不会伪装成你的经历。</p>
      <div className="timeline-filters">
        <label>图书<select value={bookId} onChange={(e) => setBookId(e.target.value)}><option value="">全部图书</option>{books.map((book) => <option key={book.id} value={book.id}>{book.title}</option>)}</select></label>
        <label>事件<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">全部事件</option><option value="session">阅读会话</option><option value="note">原话笔记</option></select></label>
        <label>顺序<select value={direction} onChange={(e) => setDirection(e.target.value as 'newest' | 'oldest')}><option value="newest">最近在前</option><option value="oldest">最早在前</option></select></label>
        <span>{visible.length} 条记录</span>
      </div>
      {loading ? <div className="journal-skeleton" /> : <TimelineList events={visible} showBook filtered={Boolean(bookId || kind)} />}
    </main>
  );
}
