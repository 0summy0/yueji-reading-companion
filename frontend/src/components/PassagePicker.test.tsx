import { describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { fireEvent, render } from '@testing-library/react';

import { PassagePicker } from './PassagePicker';
import type { Passage } from '../types';

function makePassages(chapters: number, perChapter: number): Passage[] {
  const items: Passage[] = [];
  let position = 0;
  for (let chapter = 0; chapter < chapters; chapter += 1) {
    for (let index = 0; index < perChapter; index += 1) {
      items.push({
        id: `pa_${chapter}_${index}`,
        chapter_order: chapter,
        chapter_title: `第 ${chapter + 1} 章`,
        passage_order: index,
        position,
        start_char: position * 10,
        end_char: position * 10 + 9,
        hash: `h${position}`,
        text: `第 ${position + 1} 段原文，用来模拟真实书页里的较长句子内容。`,
      });
      position += 1;
    }
  }
  return items;
}

describe('PassagePicker 分层选择', () => {
  it('只渲染当前章节的段落选项，避免整本书一次性铺开', () => {
    const passages = makePassages(3, 200);
    const { container } = render(
      <PassagePicker title="本次读到的段落" passages={passages} value={passages[0].id} onChange={() => {}} />,
    );
    const selects = container.querySelectorAll('.passage-picker select');
    expect(selects).toHaveLength(2);
    const chapterOptions = (selects[0] as HTMLSelectElement).options.length;
    const passageOptions = (selects[1] as HTMLSelectElement).options.length;
    expect(chapterOptions).toBe(3);
    expect(passageOptions).toBe(201); // 200 段 + 占位项
    expect(container.querySelectorAll('option').length).toBeLessThan(210); // 全书 600 段也只渲染一章
  });

  it('切换章节后未选段落时通知清空，选中后回传段落 ID', () => {
    const passages = makePassages(2, 5);
    const onChange = vi.fn();
    function Harness() {
      const [value, setValue] = useState(passages[0].id);
      return (
        <PassagePicker
          title="开始段落"
          passages={passages}
          value={value}
          onChange={(id) => { setValue(id); onChange(id); }}
          allowEmpty
          emptyLabel="不指定"
        />
      );
    }
    const { container } = render(<Harness />);
    const chapterSelect = container.querySelectorAll('.passage-picker select')[0];
    fireEvent.change(chapterSelect, { target: { value: '1' } });
    expect(onChange).toHaveBeenCalledWith('');
    const passageSelect = container.querySelectorAll('.passage-picker select')[1] as HTMLSelectElement;
    expect(passageSelect.options).toHaveLength(6); // 占位 + 第二章 5 段
    fireEvent.change(passageSelect, { target: { value: passages[7].id } });
    expect(onChange).toHaveBeenLastCalledWith(passages[7].id);
  });
});
