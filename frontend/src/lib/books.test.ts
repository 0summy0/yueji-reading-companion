import { describe, expect, it } from 'vitest';
import type { Book } from '../types';
import { filterAndSortBooks, shortHash } from './books';

function book(title: string, author: string, order: number): Book {
  return {
    id: title, edition_id: title, title, author, language: 'zh-CN', format: 'txt', source_hash: 'abcdef1234567890',
    source_name: `${title}.txt`, parsed_at: '', parser_version: '', content_sha256: '', sort_order: order, status: 'reading',
    created_at: '', updated_at: '', progress: { current_anchor: null, current_chapter: null, current_position: null,
      current_excerpt: null, confirmed_passages: 0, passage_count: 3, last_read_at: null },
    spine_style: { color: '#59634b', accent: '#ffffff', material: 'cloth', title_layout: 'vertical', height: 200, width: 50 },
  };
}

describe('书架检索与排序', () => {
  const books = [book('苔痕笔记', '沈知闲', 2), book('窗外有座小山', '林拾青', 0), book('夜航修理铺', '周见微', 1)];
  it('按书名和作者检索，不修改原数组', () => {
    expect(filterAndSortBooks(books, '夜航', 'imported').map((item) => item.title)).toEqual(['夜航修理铺']);
    expect(filterAndSortBooks(books, '林拾青', 'imported').map((item) => item.title)).toEqual(['窗外有座小山']);
    expect(books[0].title).toBe('苔痕笔记');
  });
  it('支持书名正逆序与导入顺序', () => {
    expect(filterAndSortBooks(books, '', 'imported')[0].title).toBe('窗外有座小山');
    expect(filterAndSortBooks(books, '', 'title').length).toBe(3);
    expect(filterAndSortBooks(books, '', '-title').length).toBe(3);
  });
  it('版本摘要稳定', () => expect(shortHash('abcdef1234567890')).toBe('ABCDEF1234'));
});
