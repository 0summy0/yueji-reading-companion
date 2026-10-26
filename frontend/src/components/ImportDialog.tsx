import { useEffect, useRef, useState } from 'react';
import { UploadSimple, X } from '@phosphor-icons/react';
import { api } from '../lib/api';

interface Props {
  onClose: () => void;
  onImported: (message: string) => void;
}

export function ImportDialog({ onClose, onImported }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [author, setAuthor] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
      ));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || !dialogRef.current.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => {
      window.removeEventListener('keydown', handleKey);
      previousFocus?.focus();
    };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return setError('请选择 EPUB 或 UTF-8 TXT 文件');
    setBusy(true);
    setError('');
    try {
      const form = new FormData();
      form.append('file', file);
      if (title.trim()) form.append('title', title.trim());
      if (author.trim()) form.append('author', author.trim());
      const result = await api.importBook(form);
      onImported(result.message);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '导入失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => !busy && event.target === event.currentTarget && onClose()}>
      <section ref={dialogRef} className="import-dialog" role="dialog" aria-modal="true" aria-labelledby="import-title">
        <button className="icon-button dialog-close" aria-label="关闭导入" onClick={onClose}><X size={20} /></button>
        <p className="eyebrow">本地解析 · 不上传书稿</p>
        <h2 id="import-title">把一本书放上书架</h2>
        <p className="muted">支持 EPUB 和 UTF-8 编码的 TXT。重复文件不会重复导入。</p>
        <form onSubmit={submit} className="stack-form">
          <label className="field-label" htmlFor="book-file">电子书文件</label>
          <input
            ref={inputRef}
            id="book-file"
            className="file-input"
            type="file"
            accept=".epub,.txt,application/epub+zip,text/plain"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
          <div className="field-hint">文件最大 20 MiB，将在本地完成安全检查与解析。</div>
          <label className="field-label" htmlFor="import-book-title">书名（留空则读取元数据或文件名）</label>
          <input id="import-book-title" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} />
          <label className="field-label" htmlFor="import-author">作者（可选）</label>
          <input id="import-author" value={author} onChange={(event) => setAuthor(event.target.value)} maxLength={120} />
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="button primary" disabled={busy} type="submit">
            <UploadSimple size={18} />{busy ? '正在安全解析…' : '导入并放上书架'}
          </button>
        </form>
      </section>
    </div>
  );
}
