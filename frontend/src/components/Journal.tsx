import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, Camera, Notebook, PencilSimple, ReadCvLogo, Trash } from '@phosphor-icons/react';
import type { CloudSession } from '@tencent-ai/workbuddy-cloud-sdk';
import type { Book, Note, Passage, PhotoAttempt, PhotoPath, TimelineEvent } from '../types';
import { api } from '../lib/api';
import { capabilityStatusLabel, formatDate, toLocalInput } from '../lib/format';
import { getCloudSession, sanitizePhotoInBrowser, uploadPhotoToCloud } from '../cloud/cloudService';
import { PassagePicker } from './PassagePicker';
import { TimelineList } from './Timeline';

interface Props {
  bookId: string;
  onBack: () => void;
  onLibraryChanged: () => void;
  notify: (message: string, tone?: 'success' | 'error') => void;
}

export function Journal({ bookId, onBack, onLibraryChanged, notify }: Props) {
  const [book, setBook] = useState<Book | null>(null);
  const [passages, setPassages] = useState<Passage[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [photoPath, setPhotoPath] = useState<PhotoPath | null>(null);
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoAttempt, setPhotoAttempt] = useState<PhotoAttempt | null>(null);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [cloudSession, setCloudSession] = useState<CloudSession | null>(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [manageBusy, setManageBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'session' | 'note'>('session');
  const [photoOpen, setPhotoOpen] = useState(false);
  const [startedAt, setStartedAt] = useState(() => toLocalInput(new Date(Date.now() - 45 * 60_000)));
  const [endedAt, setEndedAt] = useState(() => toLocalInput(new Date()));
  const [sessionType, setSessionType] = useState<'sequential' | 'skip' | 'reread'>('sequential');
  const [startAnchor, setStartAnchor] = useState('');
  const [currentAnchor, setCurrentAnchor] = useState('');
  const [sequentialConfirmed, setSequentialConfirmed] = useState(false);
  const [pointConfirmed, setPointConfirmed] = useState(true);
  const [readingContext, setReadingContext] = useState('');
  const [contextPhotoFile, setContextPhotoFile] = useState<File | null>(null);
  const [noteText, setNoteText] = useState('');
  const [notePassage, setNotePassage] = useState('');
  const [noteSession, setNoteSession] = useState('');
  const [busy, setBusy] = useState(false);
  const [slowLoad, setSlowLoad] = useState(false);
  const [sessionRequestId, setSessionRequestId] = useState(() => crypto.randomUUID());
  const [noteRequestId, setNoteRequestId] = useState(() => crypto.randomUUID());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  // 记住服务端上一次返回的书名：只有当用户没改过草稿时才用新书名覆盖，避免保存会话时把正在编辑的书名冲掉。
  const loadedTitleRef = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError('');
      const [bookData, passageData, noteData, timelineData, photoData] = await Promise.all([
        api.getBook(bookId), api.getPassages(bookId), api.listNotes(bookId), api.timeline(bookId), api.photoPath(),
      ]);
      setBook(bookData);
      setPassages(passageData);
      setNotes(noteData);
      setEvents(timelineData);
      setPhotoPath(photoData);
      setTitleDraft((old) => (loadedTitleRef.current === null || old === loadedTitleRef.current ? bookData.title : old));
      loadedTitleRef.current = bookData.title;
      const anchor = bookData.progress.current_anchor || passageData[0]?.id || '';
      setCurrentAnchor((old) => old || anchor);
      setStartAnchor((old) => old || anchor);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '手账读取失败');
    } finally {
      setLoading(false);
    }
  }, [bookId]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!loading) return;
    const timer = window.setTimeout(() => setSlowLoad(true), 6000);
    return () => window.clearTimeout(timer);
  }, [loading]);

  useEffect(() => {
    getCloudSession().then(setCloudSession).catch(() => setCloudSession(null));
  }, []);

  async function saveSession(event: React.FormEvent) {
    event.preventDefault();
    if (!currentAnchor) return notify('请选择本次读到的原文段落', 'error');
    setBusy(true);
    try {
      const createdSession = await api.createSession(bookId, {
        started_at: new Date(startedAt).toISOString(), ended_at: new Date(endedAt).toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai',
        start_anchor: startAnchor || null, current_anchor: currentAnchor, session_type: sessionType,
        sequential_confirmed: sessionType === 'sequential' && sequentialConfirmed,
        anchor_read_confirmed: pointConfirmed, reading_context: readingContext.trim() || null,
        client_request_id: sessionRequestId,
      });
      if (contextPhotoFile) {
        try {
          if (cloudSession) {
            const sanitized = await sanitizePhotoInBrowser(contextPhotoFile);
            const uploaded = await uploadPhotoToCloud(cloudSession.user.id, sanitized);
            await api.attachContextPhotoCloud(createdSession.id, { photo_url: uploaded.signedUrl, cloud_path: uploaded.path });
          } else {
            await api.uploadContextPhoto(createdSession.id, contextPhotoFile);
          }
        } catch (reason) {
          notify(`阅读会话已保存，但环境照片未上传：${reason instanceof Error ? reason.message : '请稍后重试'}`, 'error');
        }
      }
      setSessionRequestId(crypto.randomUUID());
      setReadingContext('');
      setContextPhotoFile(null);
      notify('阅读会话已保存；已读范围按你的确认更新');
      await load();
      onLibraryChanged();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '会话保存失败', 'error');
    } finally {
      setBusy(false);
    }
  }

  async function saveNote(event: React.FormEvent) {
    event.preventDefault();
    if (!noteText.trim()) return notify('先写下你的原话', 'error');
    setBusy(true);
    try {
      await api.createNote({ book_id: bookId, passage_id: notePassage || null, session_id: noteSession || null,
        text: noteText.trim(), client_request_id: noteRequestId });
      setNoteText('');
      setNoteRequestId(crypto.randomUUID());
      notify('原话已保存，AI 不可用也不会丢失');
      await load();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '笔记保存失败', 'error');
    } finally {
      setBusy(false);
    }
  }

  async function uploadPhoto(event: React.FormEvent) {
    event.preventDefault();
    if (!photoFile) return notify('请选择书页照片', 'error');
    setPhotoBusy(true);
    try {
      let result;
      if (cloudSession) {
        const sanitized = await sanitizePhotoInBrowser(photoFile);
        const uploaded = await uploadPhotoToCloud(cloudSession.user.id, sanitized);
        result = await api.uploadPhotoCloud(bookId, { photo_url: uploaded.signedUrl, cloud_path: uploaded.path });
      } else {
        result = await api.uploadPhoto(bookId, photoFile);
      }
      setPhotoAttempt(result.attempt);
      notify(result.attempt.state === 'candidates' ? '已识别并生成 Top 3 候选，请确认' : '未能可靠识别，可补拍或手动定位', result.attempt.state === 'candidates' ? 'success' : 'error');
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '照片上传失败', 'error');
    } finally {
      setPhotoBusy(false);
    }
  }

  async function confirmCandidate(candidateId: string) {
    setPhotoBusy(true);
    try {
      const now = new Date();
      await api.confirmPhoto(photoAttempt!.id, {
        chosen_anchor: candidateId,
        started_at: new Date(now.getTime() - 10 * 60_000).toISOString(),
        ended_at: now.toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai',
        session_type: 'skip',
        sequential_confirmed: false,
        anchor_read_confirmed: true,
        reading_context: null,
        client_request_id: crypto.randomUUID(),
      });
      setPhotoAttempt(null);
      setPhotoFile(null);
      notify('已确认照片位置并保存阅读会话');
      await load();
      onLibraryChanged();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '确认失败', 'error');
    } finally {
      setPhotoBusy(false);
    }
  }

  async function saveEdit(note: Note) {
    if (!editText.trim()) return notify('修订内容不能为空', 'error');
    setBusy(true);
    try {
      const result = await api.updateNote(note.id, editText.trim(), note.evidence?.passage_id || null);
      setEditingId(null);
      notify(`已保存 v${result.version}，旧版本仍保留；相关派生卡片已标记失效`);
      await load();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '修订失败', 'error');
    } finally {
      setBusy(false);
    }
  }

  async function saveTitle() {
    const next = titleDraft.trim();
    if (!next) return notify('书名不能为空', 'error');
    setManageBusy(true);
    try {
      await api.updateBookTitle(bookId, next);
      setEditingTitle(false);
      notify('书名已更新');
      await load();
      onLibraryChanged();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '改书名失败', 'error');
    } finally {
      setManageBusy(false);
    }
  }

  async function removeBook() {
    if (!book) return;
    const confirmed = window.confirm(`确定删除《${book.title}》吗？\n\n这会永久删除整本书、阅读记录、原话、情境照片和定位尝试，且不可恢复。`);
    if (!confirmed) return;
    setManageBusy(true);
    try {
      await api.deleteBook(bookId);
      notify(`已删除《${book.title}》`);
      onLibraryChanged();
      onBack();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '删除图书失败', 'error');
    } finally {
      setManageBusy(false);
    }
  }

  if (loading) {
    return (
      <main className="page-shell journal-loading" aria-busy="true" aria-live="polite">
        <span className="loading-ring" aria-hidden="true" />
        <p className="loading-title">正在翻动手账…</p>
        <p className="loading-hint">正在读取原文段落、原话与时间线{slowLoad ? '；书本较大时会多花几秒，请继续稍候' : ''}</p>
        <div className="journal-skeleton" aria-hidden="true" />
      </main>
    );
  }
  if (error || !book) return <main className="page-shell"><div className="error-state" role="alert">{error || '图书不存在'}<div className="button-row"><button className="button secondary" onClick={() => void load()}>重试</button><button className="button secondary" onClick={onBack}>返回书架</button></div></div></main>;

  return (
    <main className="journal-page page-shell">
      <button className="back-button" onClick={onBack}><ArrowLeft size={18} />返回书架</button>
      <header className="journal-heading">
        <div>
          <p className="eyebrow">书籍手账 · {book.author}</p>
          {editingTitle ? (
            <div className="book-title-edit">
              <label className="sr-only" htmlFor={`journal-title-${book.id}`}>书名</label>
              <input id={`journal-title-${book.id}`} value={titleDraft} maxLength={200} autoFocus onChange={(event) => setTitleDraft(event.target.value)} onKeyDown={(event) => {
                if (event.key === 'Enter') void saveTitle();
                if (event.key === 'Escape') { setTitleDraft(book.title); setEditingTitle(false); }
              }} />
              <div className="button-row">
                <button className="button primary" type="button" disabled={manageBusy} onClick={() => void saveTitle()}>保存书名</button>
                <button className="button secondary" type="button" disabled={manageBusy} onClick={() => { setTitleDraft(book.title); setEditingTitle(false); }}>取消</button>
              </div>
            </div>
          ) : <h1>{book.title}</h1>}
          <p>{book.progress.passage_count} 个稳定原文锚点 · 当前 {book.progress.current_chapter || '尚未设置位置'}</p>
        </div>
        <div className="journal-heading-actions">
          <button className="button photo-button" onClick={() => setPhotoOpen((open) => !open)} aria-expanded={photoOpen}>
            <Camera size={19} />照片定位<span>{photoPath?.automatic_location_available ? `AI ${photoPath.selected_task === 'ocr_page' ? 'OCR' : '视觉'} 待确认` : '当前手动兜底'}</span>
          </button>
          <div className="journal-manage">
            {!editingTitle && <button type="button" className="button text-button" disabled={manageBusy} onClick={() => { setTitleDraft(book.title); setEditingTitle(true); }}><PencilSimple size={15} />改书名</button>}
            <button type="button" className="button text-button danger-text" disabled={manageBusy} onClick={() => void removeBook()}><Trash size={15} />删除这本书</button>
          </div>
        </div>
      </header>

      {photoOpen && (
        <section className="photo-fallback" aria-label="照片入口能力状态">
          <div><p className="eyebrow">照片入口 · 不自动推进度</p><h2>{photoPath?.automatic_location_available ? '拍一页，核对候选' : '现在请使用手动定位'}</h2></div>
          <p>{photoPath?.message}</p>
          <div className="photo-capabilities">
            <span>处理路径：{photoPath?.display_path === 'manual' ? '手动定位' : photoPath?.selected_task === 'ocr_page' ? '独立 OCR（已选路由）' : 'AI 视觉（已选路由）'}</span>
            <span>当前连接：{photoPath?.capabilities?.provider_alias ? `${photoPath.capabilities.provider_alias} · ${photoPath.capabilities.model_id}` : '未选择'}</span>
            <span>图片输入：{photoPath?.capabilities ? capabilityStatusLabel(photoPath.capabilities.vision_input.status, photoPath.capabilities.simulated) : '未检测'}</span>
            <span>中文读字：{photoPath?.capabilities ? capabilityStatusLabel(photoPath.capabilities.page_ocr.status, photoPath.capabilities.simulated) : '未检测'}</span>
            {photoPath?.capabilities?.simulated && <strong>模拟检测，不代表真实API能力</strong>}
          </div>
          {photoPath?.automatic_location_available ? (
            <div className="photo-workflow">
              <form onSubmit={uploadPhoto} className="photo-upload-form">
                <label className="file-drop">选择清晰书页照片<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => setPhotoFile(e.target.files?.[0] || null)} /></label>
                <button className="button primary" disabled={photoBusy || !photoFile} type="submit">{photoBusy ? '正在去 EXIF 并识别…' : '上传并识别'}</button>
                {cloudSession
                  ? <small>照片先在浏览器去 EXIF，再直传你的 WorkBuddy 云端空间长期保存；识别只发送当前照片到上方所选连接。</small>
                  : <small>只发送去 EXIF 后的当前照片到上方所选连接；不会静默换服务商。登录「云服务」后照片可长期云端保存。</small>}
              </form>
              {photoAttempt && (
                <div className="photo-attempt" aria-live="polite">
                  <p className="attempt-message">{photoAttempt.message}</p>
                  {photoAttempt.ocr_text && <p className="ocr-text">识别文字：{photoAttempt.ocr_text}</p>}
                  {photoAttempt.candidates.length > 0 && <div className="candidate-list">
                    {photoAttempt.candidates.map((candidate) => <article className="candidate-entry" key={candidate.passage_id}>
                      <div><span className="confidence">{candidate.confidence === 'high' ? '高置信' : candidate.confidence === 'medium' ? '中置信' : '低置信'}</span><strong>{candidate.chapter_title} · 段落 #{candidate.position + 1}</strong></div>
                      <p>{candidate.excerpt}</p>
                      <button className="button secondary" disabled={photoBusy} onClick={() => void confirmCandidate(candidate.passage_id)}>确认是这里</button>
                    </article>)}
                  </div>}
                  {photoAttempt.state === 'failed' && <div className="button-row"><button className="button secondary" onClick={() => { setTab('session'); setPhotoOpen(false); }}>改用手动定位</button><button className="button text-button" onClick={() => { setTab('note'); setNotePassage(''); setPhotoOpen(false); }}>保存待定位笔记</button></div>}
                </div>
              )}
            </div>
          ) : (
            <div className="button-row">
              <button className="button secondary" onClick={() => { setTab('session'); setPhotoOpen(false); }}>手动记录读到这里</button>
              <button className="button text-button" onClick={() => { setTab('note'); setNotePassage(''); setPhotoOpen(false); }}>保存待定位笔记</button>
            </div>
          )}
        </section>
      )}

      <div className="journal-layout">
        <div className="journal-main">
          <section className="journal-paper">
            <div className="action-tabs" role="tablist" aria-label="手账记录方式">
              <button role="tab" aria-selected={tab === 'session'} onClick={() => setTab('session')}><ReadCvLogo size={19} />今天读到这里</button>
              <button role="tab" aria-selected={tab === 'note'} onClick={() => setTab('note')}><Notebook size={19} />我有一个想法</button>
            </div>

            {tab === 'session' ? (
              <form className="record-form" onSubmit={saveSession}>
                <div className="form-intro"><h2>一次真实的阅读会话</h2><p>时间可补录；位置只引用当前电子版本的段落，不换算纸书页数百分比。</p></div>
                <div className="time-fields">
                  <label>开始时间<input type="datetime-local" required value={startedAt} onChange={(e) => setStartedAt(e.target.value)} /></label>
                  <label>结束时间<input type="datetime-local" required value={endedAt} onChange={(e) => setEndedAt(e.target.value)} /></label>
                </div>
                <fieldset className="reading-mode"><legend>这次怎么读的</legend>
                  {(['sequential', 'skip', 'reread'] as const).map((type) => <label key={type}><input type="radio" name="session-type" checked={sessionType === type} onChange={() => setSessionType(type)} />{{ sequential: '顺读', skip: '跳读', reread: '重读' }[type]}</label>)}
                </fieldset>
                <PassagePicker title="开始段落（用于顺读范围）" passages={passages} value={startAnchor} onChange={setStartAnchor} allowEmpty emptyLabel="不指定开始段落（只记录本次锚点）" />
                <PassagePicker title="本次读到的段落" passages={passages} value={currentAnchor} onChange={setCurrentAnchor} />
                <label className="context-field">阅读情境（可选）
                  <textarea rows={3} maxLength={1000} value={readingContext} onChange={(e) => setReadingContext(e.target.value)} placeholder="在宿舍窗边，外面下着雨，桌上有一杯温茶。" />
                  <small>地点、声音、光线都值得记，几句话就能帮未来的你找回这一刻。</small>
                </label>
                <label className="context-photo-field">当时的环境照片（可选）
                  <input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={(e) => setContextPhotoFile(e.target.files?.[0] || null)} />
                  <small>照片只作为你的回忆线索保存，不会送给书页识别或书童问答。</small>
                  {contextPhotoFile && <span className="context-photo-name">已选择：{contextPhotoFile.name}</span>}
                </label>
                {sessionType === 'sequential' && <label className="confirm-line"><input type="checkbox" checked={sequentialConfirmed} onChange={(e) => setSequentialConfirmed(e.target.checked)} />我确认从开始段落顺读到这里，可以扩展连续已读范围</label>}
                <label className="confirm-line"><input type="checkbox" checked={pointConfirmed} onChange={(e) => setPointConfirmed(e.target.checked)} />我确认实际读过所选结束段落（只记录这个锚点，不填满中间）</label>
                <button className="button primary" disabled={busy} type="submit">{busy ? '正在保存…' : '保存阅读会话'}</button>
              </form>
            ) : (
              <form className="record-form" onSubmit={saveNote}>
                <div className="form-intro"><h2>保留你的原话</h2><p>每次修订都会新增版本。作者原文、你的表达和未来的 AI 推测不会混写。</p></div>
                <label>我的想法<textarea required rows={6} maxLength={5000} value={noteText} onChange={(e) => setNoteText(e.target.value)} placeholder="不作总结也可以，先留下当时真正想说的话…" /></label>
                <PassagePicker title="关联原文（可选；不选即为待定位笔记）" passages={passages} value={notePassage} onChange={setNotePassage} allowEmpty emptyLabel="暂不定位，不推进阅读进度" />
                <label>关联阅读会话（可选）
                  <select value={noteSession} onChange={(e) => setNoteSession(e.target.value)}><option value="">不关联会话</option>
                    {events.filter((event) => event.kind === 'session').map((event) => <option key={event.data.id} value={event.data.id}>{formatDate(event.occurred_at)} · {event.book_title}</option>)}
                  </select>
                </label>
                <button className="button primary" disabled={busy} type="submit">{busy ? '正在保存…' : '保存我的原话'}</button>
              </form>
            )}
          </section>

          <section className="notes-section">
            <div className="section-heading"><div><p className="eyebrow">ORIGINAL WORDS</p><h2>原话与版本</h2></div><span>{notes.length} 条</span></div>
            {!notes.length && <div className="empty-inline"><Notebook size={25} /><p>还没有笔记。未配置 AI 也可以一直写。</p></div>}
            <div className="note-list">
              {notes.map((note) => (
                <article className="note-entry" key={note.id} data-testid={`note-${note.id}`}>
                  <div className="note-meta"><span>我的原话 · v{note.version}</span><time>{formatDate(note.updated_at)}</time></div>
                  {editingId === note.id ? (
                    <div className="note-edit"><textarea rows={4} value={editText} onChange={(e) => setEditText(e.target.value)} />
                      <div className="button-row"><button className="button primary" disabled={busy} onClick={() => void saveEdit(note)}>保存为新版本</button><button className="button text-button" onClick={() => setEditingId(null)}>取消</button></div>
                    </div>
                  ) : <p className="note-text">{note.text}</p>}
                  <p className="note-evidence">{note.evidence ? `${note.evidence.chapter_title} · 段落 #${note.evidence.position + 1} · 字符 ${note.evidence.start_char}—${note.evidence.end_char}` : '待定位笔记 · 未推动阅读进度'}</p>
                  <div className="note-actions">
                    <button className="inline-action" onClick={() => { setEditingId(note.id); setEditText(note.text); }}><PencilSimple size={16} />修订原话</button>
                    <details><summary>查看 {note.versions.length} 个版本</summary><ol className="version-list">
                      {note.versions.map((version) => <li key={version.id}><span>v{version.version} · {formatDate(version.created_at)}</span><p>{version.text}</p></li>)}
                    </ol></details>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>

        <aside className="journal-aside">
          <section className="range-ledger">
            <p className="eyebrow">CONFIRMED RANGES</p><h2>已确认读过的范围</h2>
            {book.read_ranges?.length ? <ul>{book.read_ranges.map((range) => <li key={range.id}><span>段落 #{range.start_position + 1}{range.end_position > range.start_position ? `—#${range.end_position + 1}` : ''}</span><small>{range.confirmation_method === 'manual_sequential' ? '用户确认顺读' : '单点确认'}</small></li>)}</ul> : <p>尚未确认任何范围。只记录当前位置，不代表中间都读过。</p>}
          </section>
          <section className="book-timeline"><p className="eyebrow">READING HISTORY</p><h2>本书时间线</h2><TimelineList events={events} /></section>
        </aside>
      </div>
    </main>
  );
}
