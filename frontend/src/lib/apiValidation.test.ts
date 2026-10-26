import { describe, expect, it } from 'vitest';
import { humanizeValidationMessage } from './api';

describe('humanizeValidationMessage', () => {
  it('把长度类错误翻译成中文', () => {
    expect(humanizeValidationMessage('String should have at least 10 characters', ['body', 'password'])).toBe('密码至少需要 10 个字符');
    expect(humanizeValidationMessage('String should have at most 128 characters', ['body', 'password'])).toBe('密码最多 128 个字符');
  });

  it('同时有上下限时给出区间', () => {
    expect(humanizeValidationMessage('String should have at least 2 characters', ['body', 'username'])).toBe('用户名至少需要 2 个字符');
  });

  it('把格式类错误翻译成中文', () => {
    expect(humanizeValidationMessage('String should match pattern', ['body', 'username'])).toContain('用户名含有不允许的字符');
    expect(humanizeValidationMessage('Invalid or missing URL scheme', ['body', 'base_url'])).toContain('链接格式不正确');
    expect(humanizeValidationMessage('value is not a valid email address', ['body', 'email'])).toBe('邮箱格式不正确');
  });

  it('拿不到字段名时不抛出未知原文', () => {
    const message = humanizeValidationMessage('Something went totally custom');
    expect(message).toBe('Something went totally custom');
  });
});
