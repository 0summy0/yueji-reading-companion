import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import type { Book, SocraticSessionView } from '../types';

vi.mock('../lib/api', () => ({
  api: {
    socraticStart: vi.fn(),
    socraticList: vi.fn(),
    socraticDetail: vi.fn(),
    socraticAnswer: vi.fn(),
    socraticGenerate: vi.fn(),
    socraticFinish: vi.fn(),
  },
}));

vi.mock('../cloud/config', () => ({
  cloud: { llm: { chat: { completions: { create: vi.fn() } } } },
}));

import { api } from '../lib/api';
import { SocraticSession } from './SocraticSession';

const books: Book[] = [
  { id: 'bk_1', title: '灯塔看守人', author: '测试作者', progress: { passage_count: 10, current_chapter: '第一章', read_passages: 3 }, created_at: '2026-10-20T10:00:00Z' } as unknown as Book,
];

function makeView(overrides: Partial<SocraticSessionView> = {}): SocraticSessionView {
  return {
    id: 'soc_1',
    book_id: 'bk_1',
    book_title: '灯塔看守人',
    book_author: '测试作者',
    rounds_planned: 3,
    engine: 'byok',
    status: 'active',
    state: 'need_question',
    current_turn: 1,
    created_at: '2026-10-25T12:00:00Z',
    finished_at: null,
    evidence: [
      { id: 'pa:p1', kind: 'passage', speaker: 'author', book_id: 'bk_1', book_title: '灯塔看守人', note_id: null, passage_id: 'p1', chapter_title: '第一章', position: 0, excerpt: '看守人每天给船写信。' },
    ],
    turns: [],
    report: null,
    task: null,
    ...overrides,
  };
}

function viewWithQuestion(): SocraticSessionView {
  return makeView({
    state: 'awaiting_answer',
    turns: [
      { turn_index: 1, kind: 'fact', kind_label: '事实理解', question: '看守人在第一章做了什么？', question_evidence_ids: ['pa:p1'], answer: null, answered_at: null, feedback: null, feedback_evidence_ids: [], created_at: '2026-10-25T12:00:01Z' },
    ],
  });
}

function props() {
  return {
    books,
    notify: vi.fn(),
    cloudSession: null,
    cloudModels: [{ id: 'm1', label: '云端模型一' }],
    cloudModelId: 'm1',
    onCloudModelChange: vi.fn(),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe('SocraticSession', () => {
  it('配置阶段说明证据边界并给出轮数选择', () => {
    render(<SocraticSession {...props()} />);
    expect(screen.getByText(/你已读的原文范围/)).toBeTruthy();
    expect(screen.getByText(/你自己的笔记/)).toBeTruthy();
    const rounds = screen.getByLabelText(/追问轮数/) as HTMLSelectElement;
    expect(rounds.value).toBe('3');
    expect([...rounds.options].map((option) => option.value)).toEqual(['3', '4', '5']);
    expect(screen.getByRole('button', { name: /开始书格拉底/ })).toBeTruthy();
  });

  it('开始后展示第一问，提交回答成功后推进到反馈', async () => {
    const mockedApi = vi.mocked(api);
    mockedApi.socraticStart.mockResolvedValue(makeView());
    mockedApi.socraticGenerate
      .mockResolvedValueOnce(viewWithQuestion())
      .mockResolvedValueOnce(makeView({
        state: 'awaiting_answer',
        current_turn: 2,
        turns: [
          { turn_index: 1, kind: 'fact', kind_label: '事实理解', question: '看守人在第一章做了什么？', question_evidence_ids: ['pa:p1'], answer: '他给船写信。', answered_at: '2026-10-25T12:05:00Z', feedback: '你记住了写信的事实。', feedback_evidence_ids: ['pa:p1'], created_at: '2026-10-25T12:00:01Z' },
          { turn_index: 2, kind: 'causal', kind_label: '因果与人物动机', question: '他为什么坚持写信？', question_evidence_ids: [], answer: null, answered_at: null, feedback: null, feedback_evidence_ids: [], created_at: '2026-10-25T12:05:30Z' },
        ],
      }));
    mockedApi.socraticAnswer.mockResolvedValue(makeView({ state: 'need_feedback', turns: [
      { turn_index: 1, kind: 'fact', kind_label: '事实理解', question: '看守人在第一章做了什么？', question_evidence_ids: ['pa:p1'], answer: '他给船写信。', answered_at: '2026-10-25T12:05:00Z', feedback: null, feedback_evidence_ids: [], created_at: '2026-10-25T12:00:01Z' },
    ] }));

    render(<SocraticSession {...props()} />);
    fireEvent.click(screen.getByRole('button', { name: /开始书格拉底/ }));
    await waitFor(() => expect(screen.getByText('看守人在第一章做了什么？')).toBeTruthy());
    expect(mockedApi.socraticGenerate).toHaveBeenCalledWith('soc_1');

    fireEvent.change(screen.getByLabelText(/你的回答/), { target: { value: '他给船写信。' } });
    fireEvent.click(screen.getByRole('button', { name: /提交回答/ }));
    await waitFor(() => expect(mockedApi.socraticAnswer).toHaveBeenCalledWith('soc_1', 1, '他给船写信。'));
    await waitFor(() => expect(screen.getByText('他为什么坚持写信？')).toBeTruthy());
    expect(screen.getByText('你记住了写信的事实。')).toBeTruthy();
  });

  it('提交回答失败时保留输入内容', async () => {
    const mockedApi = vi.mocked(api);
    mockedApi.socraticStart.mockResolvedValue(makeView());
    mockedApi.socraticGenerate.mockResolvedValue(viewWithQuestion());
    mockedApi.socraticAnswer.mockRejectedValue(new Error('网络中断'));

    render(<SocraticSession {...props()} />);
    fireEvent.click(screen.getByRole('button', { name: /开始书格拉底/ }));
    await waitFor(() => expect(screen.getByText('看守人在第一章做了什么？')).toBeTruthy());

    const textarea = screen.getByLabelText(/你的回答/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '我写了一半的答案' } });
    fireEvent.click(screen.getByRole('button', { name: /提交回答/ }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(textarea.value).toBe('我写了一半的答案');
    expect(mockedApi.socraticAnswer).toHaveBeenCalledTimes(1);
  });

  it('报告阶段分块展示并如实提示无可推荐书目', async () => {
    const mockedApi = vi.mocked(api);
    mockedApi.socraticStart.mockResolvedValue(makeView());
    mockedApi.socraticGenerate.mockResolvedValue(makeView({
      state: 'need_report',
      status: 'active',
      turns: [
        { turn_index: 1, kind: 'fact', kind_label: '事实理解', question: '看守人在第一章做了什么？', question_evidence_ids: [], answer: '他给船写信。', answered_at: '2026-10-25T12:05:00Z', feedback: '记住了核心事实。', feedback_evidence_ids: [], created_at: '2026-10-25T12:00:01Z' },
      ],
    }));
    mockedApi.socraticFinish.mockResolvedValue(makeView({
      status: 'finished',
      state: 'done',
      turns: [
        { turn_index: 1, kind: 'fact', kind_label: '事实理解', question: '看守人在第一章做了什么？', question_evidence_ids: [], answer: '他给船写信。', answered_at: '2026-10-25T12:05:00Z', feedback: '记住了核心事实。', feedback_evidence_ids: [], created_at: '2026-10-25T12:00:01Z' },
      ],
      report: {
        clear_points: ['记住了写信的事实。'],
        vague_points: ['写信动机证据不足。'],
        user_viewpoints: ['写信是一种守望。'],
        revisit_evidence: [
          { id: 'pa:p1', kind: 'passage', speaker: 'author', book_id: 'bk_1', book_title: '灯塔看守人', note_id: null, passage_id: 'p1', chapter_title: '第一章', position: 0, excerpt: '看守人每天给船写信。' },
        ],
        follow_up_suggestions: ['重读后再问动机。'],
        recommendations: [],
        recommendations_note: '书架上暂无其他书籍，无法给出可靠推荐；需要补充书目来源后再试。',
        model_id: 'mock-reader-v1',
        created_at: '2026-10-25T12:10:00Z',
      },
    }));

    render(<SocraticSession {...props()} />);
    fireEvent.click(screen.getByRole('button', { name: /开始书格拉底/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: /继续生成/ })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /继续生成/ }));
    await waitFor(() => expect(screen.getByRole('heading', { level: 3, name: /理解报告/ })).toBeTruthy());
    expect(screen.getByText('记住了写信的事实。')).toBeTruthy();
    expect(screen.getByText('写信动机证据不足。')).toBeTruthy();
    expect(screen.getByText('写信是一种守望。')).toBeTruthy();
    expect(screen.getByText(/建议回看的原文位置/)).toBeTruthy();
    expect(screen.getByText(/需要补充书目来源/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /再开一局/ })).toBeTruthy();
  });

  it('无书时给出空状态提示且不能开始', () => {
    render(<SocraticSession {...props()} books={[]} />);
    const start = screen.getByRole('button', { name: /开始书格拉底/ }) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    expect(screen.getByText(/先在书房导入或选择一本书/)).toBeTruthy();
  });
});
