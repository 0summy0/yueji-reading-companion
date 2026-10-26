import type { Passage } from '../types';

export interface ChapterGroup {
  title: string;
  items: Passage[];
  firstPosition: number;
}

/** 按章节顺序分组；同一章节标题在原文中可能重复，按出现顺序合并相邻段。 */
export function groupPassagesByChapter(passages: Passage[]): ChapterGroup[] {
  const groups: ChapterGroup[] = [];
  for (const passage of passages) {
    const last = groups[groups.length - 1];
    if (last && last.title === passage.chapter_title) {
      last.items.push(passage);
    } else {
      groups.push({ title: passage.chapter_title, items: [passage], firstPosition: passage.position });
    }
  }
  return groups;
}

/** 找到某个段落所在的章节索引；找不到返回 -1。 */
export function chapterIndexForPassage(groups: ChapterGroup[], passageId: string | null): number {
  if (!passageId) return -1;
  return groups.findIndex((group) => group.items.some((item) => item.id === passageId));
}
