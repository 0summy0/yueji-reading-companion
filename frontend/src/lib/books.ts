import type { Book } from '../types';

export type BookSort = 'imported' | 'title' | '-title' | 'author' | 'recent';

export function filterAndSortBooks(books: Book[], query: string, sort: BookSort): Book[] {
  const needle = query.trim().toLocaleLowerCase('zh-CN');
  const filtered = books.filter((book) => !needle || `${book.title} ${book.author}`.toLocaleLowerCase('zh-CN').includes(needle));
  return [...filtered].sort((a, b) => {
    if (sort === 'title') return a.title.localeCompare(b.title, 'zh-CN');
    if (sort === '-title') return b.title.localeCompare(a.title, 'zh-CN');
    if (sort === 'author') return a.author.localeCompare(b.author, 'zh-CN') || a.title.localeCompare(b.title, 'zh-CN');
    if (sort === 'recent') return (b.progress.last_read_at || '').localeCompare(a.progress.last_read_at || '');
    return a.sort_order - b.sort_order;
  });
}

export function shortHash(hash: string): string {
  return hash.slice(0, 10).toUpperCase();
}
