import { describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

vi.mock('../lib/api', () => ({
  api: {
    login: vi.fn(),
    register: vi.fn(),
  },
}));

import { AuthPage } from './AuthPage';

describe('AuthPage 密码可见性', () => {
  it('默认掩码，点击眼睛后明文，再点恢复掩码', () => {
    cleanup();
    render(<AuthPage onAuth={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: '邀请注册' }));

    const input = screen.getByLabelText('密码', { selector: 'input' });
    const toggle = screen.getByRole('button', { name: '显示密码' });
    expect((input as HTMLInputElement).type).toBe('password');

    fireEvent.click(toggle);
    expect((input as HTMLInputElement).type).toBe('text');
    expect(screen.getByRole('button', { name: '隐藏密码' }).getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(screen.getByRole('button', { name: '隐藏密码' }));
    expect((input as HTMLInputElement).type).toBe('password');
  });

  it('切换登录 / 注册时清掉上一次的报错与密码', () => {
    cleanup();
    render(<AuthPage onAuth={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: '邀请注册' }));
    fireEvent.change(screen.getByLabelText('密码', { selector: 'input' }), { target: { value: 'abc' } });

    fireEvent.click(screen.getByRole('tab', { name: '登录' }));
    expect((screen.getByLabelText('密码', { selector: 'input' }) as HTMLInputElement).value).toBe('');
    expect(screen.queryByLabelText('邀请码', { selector: 'input' })).toBeNull();
  });
});
