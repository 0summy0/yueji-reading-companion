import { useEffect, useState } from 'react';
import { Clock, Notebook } from '@phosphor-icons/react';
import type { ContextPhoto, Note, ReadingSession, TimelineEvent } from '../types';
import { formatDate, sessionTypeLabel } from '../lib/format';
import { createPhotoSignedUrl } from '../cloud/cloudService';

/** 情境照片：本地照片直接用后端文件地址，云端照片按需生成短期签名链接。 */
function ContextPhotoThumb({ photo }: { photo: ContextPhoto }) {
  const [src, setSrc] = useState<string | null>(photo.url ?? null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (photo.url || !photo.cloud_path) return;
    let cancelled = false;
    createPhotoSignedUrl(photo.cloud_path)
      .then((url) => { if (!cancelled) setSrc(url); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [photo.url, photo.cloud_path]);

  if (failed) return <span className="timeline-photo-fallback">照片在云端，登录云服务后可查看</span>;
  if (!src) return <span className="timeline-photo-loading">照片加载中…</span>;
  return <img src={src} alt="当时的阅读环境" loading="lazy" />;
}

export function TimelineList({ events, showBook = false, filtered = false }: { events: TimelineEvent[]; showBook?: boolean; filtered?: boolean }) {
  if (!events.length) {
    return filtered
      ? <div className="empty-inline"><Clock size={24} /><p>当前筛选没有匹配的记录。把「图书」「事件」改回「全部」即可看到全部时间线。</p></div>
      : <div className="empty-inline"><Clock size={24} /><p>还没有阅读事件。第一段记录会从这里开始。</p></div>;
  }
  return (
    <ol className="timeline-list">
      {events.map((event) => {
        const isNote = event.kind === 'note';
        const note = isNote ? event.data as Note : null;
        const session = !isNote ? event.data as ReadingSession : null;
        return (
          <li key={`${event.kind}-${event.data.id}`} className={`timeline-event event-${event.kind}`}>
            <span className="timeline-icon" aria-hidden="true">{isNote ? <Notebook size={17} /> : <Clock size={17} />}</span>
            <div className="timeline-body">
              <div className="timeline-meta">
                <span>{isNote ? '我的原话' : `阅读记录 · ${sessionTypeLabel[session!.session_type]}`}</span>
                <time dateTime={event.occurred_at}>{formatDate(event.occurred_at)}</time>
              </div>
              {showBook && <p className="timeline-book">《{event.book_title}》</p>}
              {note ? (
                <>
                  <p className="timeline-text">{note.text}</p>
                  <p className="timeline-sub">版本 v{note.version}{note.evidence ? ` · ${note.evidence.chapter_title} · 段落 #${note.evidence.position + 1}` : ' · 待定位笔记'}</p>
                </>
              ) : session ? (
                <>
                  <p className="timeline-text">{session.chapter_title} · 段落 #{session.position + 1}</p>
                  {session.reading_context && <p className="timeline-context">阅读情境：{session.reading_context}</p>}
                  {!!session.context_photos?.length && <div className="timeline-photos" aria-label="当时的阅读环境照片">{session.context_photos.map((photo) => <ContextPhotoThumb key={photo.id} photo={photo} />)}</div>}
                  <p className="timeline-sub">{formatDate(session.started_at)}—{formatDate(session.ended_at)} · 原文：{session.excerpt}</p>
                </>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
