import type { CapabilityStatus, Passage } from '../types';

export function formatDate(value?: string | null, withTime = true): string {
  if (!value) return '尚无记录';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    ...(withTime ? { hour: '2-digit', minute: '2-digit', hour12: false } : {}),
  }).format(new Date(value));
}

export function toLocalInput(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function passageLabel(passage: Passage): string {
  return `#${passage.position + 1} · ${passage.chapter_title} · ${passage.text.slice(0, 42)}`;
}

export const sessionTypeLabel = { sequential: '顺读', skip: '跳读', reread: '重读' } as const;

const capabilityStatusBaseLabel: Record<CapabilityStatus, string> = {
  verified: '已通过',
  unsupported: '明确不支持',
  inconclusive: '未能确认',
  vision_partial: '视觉部分通过',
  unverified_error: '暂无法验证',
  untested: '尚未检测',
  stale: '结果已失效',
};

/** Only append the simulation marker when the backend explicitly says it is a Mock connection. */
export function capabilityStatusLabel(status: CapabilityStatus, simulated?: boolean): string {
  const base = capabilityStatusBaseLabel[status];
  return simulated === true && base !== '尚未检测' && base !== '结果已失效' ? `${base}（模拟）` : base;
}
