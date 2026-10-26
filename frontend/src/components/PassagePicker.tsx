import { memo, useEffect, useMemo, useState } from 'react';

import type { Passage } from '../types';
import { chapterIndexForPassage, groupPassagesByChapter } from '../lib/passages';

interface Props {
  title: string;
  passages: Passage[];
  value: string;
  onChange: (passageId: string) => void;
  allowEmpty?: boolean;
  emptyLabel?: string;
}

/**
 * 分层段落选择：先选章节，再选本章内的具体段落。
 * 只渲染当前章节的选项，避免几百上千段一次性塞进原生下拉造成页面卡顿。
 */
export const PassagePicker = memo(function PassagePicker({ title, passages, value, onChange, allowEmpty = false, emptyLabel }: Props) {
  const chapters = useMemo(() => groupPassagesByChapter(passages), [passages]);
  const [chapterIndex, setChapterIndex] = useState(() => Math.max(0, chapterIndexForPassage(chapters, value)));

  // 外部选中值变化（如载入当前进度）时，把章节切到对应位置。
  useEffect(() => {
    const index = chapterIndexForPassage(chapters, value);
    if (index >= 0 && index !== chapterIndex) setChapterIndex(index);
  }, [chapters, value, chapterIndex]);

  const chapter = chapters[chapterIndex];
  const chapterOptions = useMemo(
    () => chapters.map((group, index) => ({ index, label: `${index + 1}. ${group.title}（${group.items.length} 段）` })),
    [chapters],
  );

  if (!chapters.length) return null;

  return (
    <fieldset className="passage-picker">
      <legend>{title}</legend>
      <div className="passage-picker-row">
        <label>章节
          <select
            value={chapterIndex}
            onChange={(event) => {
              const next = Number(event.target.value);
              setChapterIndex(next);
              const stillInChapter = chapters[next]?.items.some((item) => item.id === value);
              if (!stillInChapter) onChange('');
            }}
          >
            {chapterOptions.map((option) => <option key={option.index} value={option.index}>{option.label}</option>)}
          </select>
        </label>
        <label>段落
          <select required={!allowEmpty} value={value} onChange={(event) => onChange(event.target.value)}>
            <option value="" disabled={!allowEmpty}>{emptyLabel ?? '请选择本章的具体段落'}</option>
            {chapter?.items.map((item) => <option key={item.id} value={item.id}>#{item.position + 1} · {item.text.slice(0, 42)}</option>)}
          </select>
        </label>
      </div>
      <p className="passage-picker-hint">
        第 {chapterIndex + 1} 章 · 共 {chapter?.items.length ?? 0} 段
        {value && chapter?.items.some((item) => item.id === value)
          ? ` · 已选 #${(chapter.items.find((item) => item.id === value)?.position ?? 0) + 1}`
          : ' · 尚未选择段落'}
      </p>
    </fieldset>
  );
});
