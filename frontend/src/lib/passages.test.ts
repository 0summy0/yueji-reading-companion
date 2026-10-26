import { describe, expect, it } from 'vitest';

import type { Passage } from '../types';
import { chapterIndexForPassage, groupPassagesByChapter } from './passages';

function passage(id: string, chapter: string, position: number): Passage {
  return {
    id, chapter_order: 0, chapter_title: chapter, passage_order: position, position,
    start_char: position * 10, end_char: position * 10 + 9, hash: id, text: `第 ${position + 1} 段原文`,
  };
}

describe('groupPassagesByChapter', () => {
  it('按出现顺序分组，并把同名且相邻的章节合并', () => {
    const groups = groupPassagesByChapter([
      passage('a', '第一章', 0),
      passage('b', '第一章', 1),
      passage('c', '第二章', 2),
      passage('d', '第一章', 3),
    ]);
    expect(groups.map((group) => [group.title, group.items.length])).toEqual([
      ['第一章', 2],
      ['第二章', 1],
      ['第一章', 1],
    ]);
    expect(groups[2].firstPosition).toBe(3);
  });

  it('定位段落所在章节，未命中返回 -1', () => {
    const groups = groupPassagesByChapter([passage('a', '一', 0), passage('b', '二', 1), passage('c', '三', 2)]);
    expect(chapterIndexForPassage(groups, 'b')).toBe(1);
    expect(chapterIndexForPassage(groups, 'missing')).toBe(-1);
    expect(chapterIndexForPassage(groups, null)).toBe(-1);
  });
});
