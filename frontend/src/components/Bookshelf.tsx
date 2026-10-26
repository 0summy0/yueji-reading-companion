import { useMemo, useState, type CSSProperties } from 'react';
import { BookOpen, MagnifyingGlass, PencilSimple, Plus, SlidersHorizontal, Trash } from '@phosphor-icons/react';
import type { Book, SpineStyle } from '../types';
import { filterAndSortBooks, shortHash, type BookSort } from '../lib/books';
import { formatDate } from '../lib/format';
import { api } from '../lib/api';
import { ImportDialog } from './ImportDialog';

interface Props {
  books: Book[];
  loading: boolean;
  onOpen: (id: string) => void;
  onChanged: (message?: string) => void;
  notify: (message: string, tone?: 'success' | 'error') => void;
}

function Spine({ book, selected, onSelect }: { book: Book; selected: boolean; onSelect: () => void }) {
  const style = {
    '--spine-color': book.spine_style.color,
    '--spine-accent': book.spine_style.accent,
    height: `${book.spine_style.height}px`,
    width: `${book.spine_style.width}px`,
  } as CSSProperties;
  return (
    <button
      type="button"
      className={`book-spine material-${book.spine_style.material} ${selected ? 'is-drawn' : ''}`}
      style={style}
      aria-label={`书脊：${book.title}，${book.author}`}
      aria-pressed={selected}
      data-testid={`book-spine-${book.id}`}
      onClick={onSelect}
    >
      <span className="spine-rule" />
      <span className={`spine-title layout-${book.spine_style.title_layout}`}>{book.title}</span>
      <span className="spine-author">{book.author}</span>
      <span className="spine-pressmark">阅迹</span>
      {book.progress.current_anchor && <span className="spine-bookmark" role="img" aria-label="有阅读位置" />}
    </button>
  );
}

function StyleEditor({ book, onSaved, notify }: { book: Book; onSaved: (book: Book) => void; notify: Props['notify'] }) {
  const [style, setStyle] = useState<SpineStyle>(book.spine_style);
  const [busy, setBusy] = useState(false);
  const update = <K extends keyof SpineStyle>(key: K, value: SpineStyle[K]) => setStyle((old) => ({ ...old, [key]: value }));

  async function save() {
    setBusy(true);
    try {
      const updated = await api.updateSpine(book.id, style);
      onSaved(updated);
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="style-editor">
      <summary><SlidersHorizontal size={17} />调整书脊</summary>
      <div className="style-controls">
        <label>主色<input type="color" value={style.color} onChange={(e) => update('color', e.target.value)} /></label>
        <label>字色<input type="color" value={style.accent} onChange={(e) => update('accent', e.target.value)} /></label>
        <label>材质
          <select value={style.material} onChange={(e) => update('material', e.target.value as SpineStyle['material'])}>
            <option value="cloth">布面</option><option value="paper">纸面</option><option value="leather">皮革</option><option value="linen">亚麻</option>
          </select>
        </label>
        <label>标题排版
          <select value={style.title_layout} onChange={(e) => update('title_layout', e.target.value as SpineStyle['title_layout'])}>
            <option value="vertical">竖排</option><option value="horizontal">横排</option>
          </select>
        </label>
        <label>高度 {style.height} px<input type="range" min="160" max="270" value={style.height} onChange={(e) => update('height', Number(e.target.value))} /></label>
        <label>宽度 {style.width} px<input type="range" min="42" max="96" value={style.width} onChange={(e) => update('width', Number(e.target.value))} /></label>
        <button className="button secondary" type="button" disabled={busy} onClick={() => save().catch((error: unknown) => notify(error instanceof Error ? error.message : '书脊样式保存失败', 'error'))}>{busy ? '保存中…' : '保存样式'}</button>
      </div>
    </details>
  );
}

function CoverCard({ book, onOpen, onChanged, onDeleted, notify }: { book: Book; onOpen: () => void; onChanged: () => void; onDeleted: () => void; notify: Props['notify'] }) {
  const coverStyle = { '--cover-color': book.spine_style.color, '--cover-accent': book.spine_style.accent } as CSSProperties;
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(book.title);
  const [actionBusy, setActionBusy] = useState(false);

  async function saveTitle() {
    const title = titleDraft.trim();
    if (!title) return notify('书名不能为空', 'error');
    if (title.length > 200) return notify('书名不能超过 200 个字符', 'error');
    setActionBusy(true);
    try {
      const updated = await api.updateBookTitle(book.id, title);
      setTitleDraft(updated.title);
      setEditingTitle(false);
      onChanged();
      notify(`已将书名改为《${updated.title}》`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '书名保存失败', 'error');
    } finally {
      setActionBusy(false);
    }
  }

  async function deleteBook() {
    const confirmed = window.confirm(`确定删除《${book.title}》吗？\n\n这会永久删除整本书、阅读记录、笔记、定位照片和定位尝试，且不可恢复。`);
    if (!confirmed) return;
    setActionBusy(true);
    try {
      await api.deleteBook(book.id);
      onDeleted();
      notify(`已删除《${book.title}》`);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '删除图书失败', 'error');
    } finally {
      setActionBusy(false);
    }
  }

  return (
    <section className="drawn-book" aria-live="polite" aria-label={`已抽出 ${book.title}`}>
      <div className="cover-card" style={coverStyle} data-testid="cover-card">
        <span className="cover-kicker">YUEJI · PRIVATE LIBRARY</span>
        <h2>{book.title}</h2>
        <p>{book.author}</p>
        <span className="cover-foot">纸书阅读 · 电子锚点</span>
      </div>
      <div className="drawn-meta">
        <p className="eyebrow">已从书架抽出</p>
        {editingTitle ? (
          <div className="book-title-edit">
            <label className="sr-only" htmlFor={`book-title-${book.id}`}>书名</label>
            <input id={`book-title-${book.id}`} value={titleDraft} maxLength={200} autoFocus onChange={(event) => setTitleDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void saveTitle(); if (event.key === 'Escape') { setTitleDraft(book.title); setEditingTitle(false); } }} />
            <div className="button-row">
              <button className="button primary" type="button" disabled={actionBusy} onClick={() => void saveTitle()}>保存书名</button>
              <button className="button secondary" type="button" disabled={actionBusy} onClick={() => { setTitleDraft(book.title); setEditingTitle(false); }}>取消</button>
            </div>
          </div>
        ) : <h3>{book.title}</h3>}
        <dl className="book-facts">
          <div><dt>当前位置</dt><dd>{book.progress.current_chapter || '尚未设置'} {book.progress.current_position !== null ? `· 段落 #${book.progress.current_position + 1}` : ''}</dd></div>
          <div><dt>已确认范围</dt><dd>{book.progress.confirmed_passages} 个段落，不用页数百分比代替</dd></div>
          <div><dt>最近阅读</dt><dd>{formatDate(book.progress.last_read_at)}</dd></div>
          <div><dt>导入版本</dt><dd>{book.format.toUpperCase()} · {shortHash(book.source_hash)} · {book.source_name}</dd></div>
        </dl>
        <div className="button-row">
          <button className="button primary" onClick={onOpen}><BookOpen size={18} />进入手账</button>
          {!editingTitle && <button className="button secondary" type="button" disabled={actionBusy} onClick={() => setEditingTitle(true)}><PencilSimple size={17} />修改书名</button>}
          <button className="button secondary" type="button" disabled={actionBusy} onClick={() => void deleteBook()}><Trash size={17} />删除整本书</button>
        </div>
        <StyleEditor book={book} onSaved={(updated) => { onChanged(); notify(`已保存《${updated.title}》的书脊样式`); }} notify={notify} />
      </div>
    </section>
  );
}

export function Bookshelf({ books, loading, onOpen, onChanged, notify }: Props) {
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<BookSort>('imported');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const visible = useMemo(() => filterAndSortBooks(books, query, sort), [books, query, sort]);
  const selected = books.find((book) => book.id === selectedId);

  return (
    <main className="library-page page-shell">
      <div className="library-heading">
        <div>
          <p className="eyebrow">纸书在手中，记忆有归处</p>
          <h1>我的书房</h1>
          <p className="lede">从书脊抽出一本书，记下今天读到的地方。原文、你的原话与未来的 AI 归纳，始终分开保存。</p>
        </div>
        <button className="button primary add-book" onClick={() => setImporting(true)}><Plus size={19} />添加一本书</button>
      </div>

      <div className="shelf-toolbar" aria-label="书架检索与排序">
        <label className="search-field">
          <MagnifyingGlass size={18} aria-hidden="true" />
          <span className="sr-only">搜索书名或作者</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="找书名或作者…" type="search" />
        </label>
        <label className="sort-field">排列
          <select value={sort} onChange={(event) => setSort(event.target.value as BookSort)}>
            <option value="imported">上架顺序</option><option value="title">书名 A—Z</option><option value="-title">书名 Z—A</option>
            <option value="author">作者</option><option value="recent">最近阅读</option>
          </select>
        </label>
        <span className="book-count">{visible.length} / {books.length} 本</span>
      </div>

      <section className="shelf-case" aria-label="实体书脊式书架">
        <div className="shelf-topline"><span>阅迹书房</span><span>LOCAL COLLECTION</span></div>
        {loading ? (
          <div className="shelf-loading" aria-label="正在打开书房"><span /><span /><span /></div>
        ) : visible.length ? (
          <div className="shelf-scroll">
            <div className="shelf-books">
              {visible.map((book) => <Spine key={book.id} book={book} selected={selectedId === book.id} onSelect={() => setSelectedId(book.id)} />)}
            </div>
          </div>
        ) : (
          <div className="empty-state">
            <BookOpen size={30} />
            <h2>{books.length ? '没有找到这本书' : '书架还空着'}</h2>
            <p>{books.length ? '换一个书名或作者关键词。' : '导入你拥有使用权的 EPUB 或 UTF-8 TXT。'}</p>
          </div>
        )}
        <div className="wood-plank"><span /><span /><span /></div>
      </section>
      <p className="shelf-instruction">点击书脊抽书；键盘 Tab 选择、Enter 抽出。手机可沿书架横向滑动。</p>

      {selected && <CoverCard key={selected.id} book={selected} onOpen={() => onOpen(selected.id)} onChanged={onChanged} onDeleted={() => { setSelectedId(null); onChanged(); }} notify={notify} />}
      {importing && <ImportDialog onClose={() => setImporting(false)} onImported={(message) => onChanged(message)} />}
    </main>
  );
}
