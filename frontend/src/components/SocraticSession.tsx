import { useCallback, useEffect, useRef, useState } from 'react';
import type { CloudSession } from '@tencent-ai/workbuddy-cloud-sdk';
import { BookOpenText, ChatTeardropText, GraduationCap, MagnifyingGlass, Warning } from '@phosphor-icons/react';

import type { Book, SocraticEvidence, SocraticSessionSummary, SocraticSessionView, SocraticTask, SocraticTurn } from '../types';
import { api } from '../lib/api';
import { cloud } from '../cloud/config';
import type { CloudModelInfo } from '../cloud/cloudService';
import { loadAiPrefs, saveAiPrefs, type AiPrefs } from '../lib/aiPrefs';
import { formatDate } from '../lib/format';

const STATE_LABEL: Record<SocraticSessionView['state'], string> = {
  need_question: '正在出第一问',
  awaiting_answer: '等待你的回答',
  need_feedback: '正在检查你的回答',
  need_report: '等待生成理解报告',
  done: '已完成',
};

function extractJsonText(text: string): string {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = fenced ? fenced[1] : text;
  const start = body.indexOf('{');
  const end = body.lastIndexOf('}');
  if (start === -1 || end <= start) throw new Error('云端模型没有返回有效 JSON，已放弃本次结果');
  return body.slice(start, end + 1);
}

interface Props {
  books: Book[];
  notify: (message: string, tone?: 'success' | 'error') => void;
  cloudSession: CloudSession | null;
  cloudModels: CloudModelInfo[];
  cloudModelId: string;
  onCloudModelChange: (id: string) => void;
}

export function SocraticSession({ books, notify, cloudSession, cloudModels, cloudModelId, onCloudModelChange }: Props) {
  const [phase, setPhase] = useState<'config' | 'active' | 'history'>('config');
  const [bookId, setBookId] = useState('');
  const [rounds, setRounds] = useState(3);
  const [engine, setEngine] = useState<AiPrefs['engine']>(() => loadAiPrefs().engine);
  const [session, setSession] = useState<SocraticSessionView | null>(null);
  const [answerDraft, setAnswerDraft] = useState('');
  const [busy, setBusy] = useState<'idle' | 'starting' | 'generating' | 'answering' | 'finishing'>('idle');
  const [error, setError] = useState('');
  const [history, setHistory] = useState<SocraticSessionSummary[] | null>(null);
  const [viewSession, setViewSession] = useState<SocraticSessionView | null>(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!bookId && books.length) setBookId(books[0].id);
  }, [books, bookId]);

  const callCloudModel = useCallback(async (task: SocraticTask): Promise<string> => {
    // 调用云端模型本身不需要登录；只有用户把开关关掉时才要求登录。
    if (!cloudSession && !loadAiPrefs().allowAnonymousCloud) throw new Error('按你的设置，使用云端 AI 前需要先到「云服务」页登录云端身份');
    if (!cloudModelId) throw new Error('云端暂无可用的模型，请稍后再试');
    const messages = task.prompt?.messages;
    if (!messages?.length) throw new Error('缺少生成任务的提示词，请刷新会话后重试');
    let text = '';
    for await (const chunk of cloud.llm.chat.completions.create({
      model: cloudModelId,
      messages: messages as never,
      stream: true,
      temperature: 0.4,
    })) {
      const delta = chunk.choices?.[0]?.delta;
      if (delta?.content) text += delta.content;
    }
    if (!text.trim()) throw new Error('云端模型没有返回内容，请稍后再试');
    return extractJsonText(text);
  }, [cloudSession, cloudModelId]);

  const advance = useCallback(async (current: SocraticSessionView) => {
    const requestId = ++requestIdRef.current;
    setError('');
    setBusy('generating');
    try {
      let next: SocraticSessionView;
      if (current.state === 'need_report') {
        const pre = await api.socraticFinish(current.id);
        if (pre.report) {
          next = pre;
        } else {
          const task = pre.task ?? current.task;
          if (!task) throw new Error('缺少报告生成任务，请刷新会话后重试');
          const raw = await callCloudModel(task);
          next = await api.socraticFinish(current.id, raw);
        }
      } else if (current.engine === 'cloud') {
        if (!current.task) throw new Error('当前没有待生成的步骤，请刷新会话后重试');
        const raw = await callCloudModel(current.task);
        next = await api.socraticGenerate(current.id, raw);
      } else {
        next = await api.socraticGenerate(current.id);
      }
      if (requestIdRef.current !== requestId) return;
      setSession(next);
      if (next.report) notify('理解报告已生成');
    } catch (reason) {
      if (requestIdRef.current !== requestId) return;
      setError(reason instanceof Error ? reason.message : '生成失败，请重试');
    } finally {
      if (requestIdRef.current === requestId) setBusy('idle');
    }
  }, [callCloudModel, notify]);

  async function begin() {
    if (!bookId) return notify('先选择一本书', 'error');
    setError('');
    setBusy('starting');
    try {
      const clientRequestId = `socratic-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const started = await api.socraticStart({ book_id: bookId, rounds, engine, client_request_id: clientRequestId });
      setSession(started);
      setPhase('active');
      setAnswerDraft('');
      await advance(started);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '开始失败，请重试');
    } finally {
      setBusy('idle');
    }
  }

  async function submitAnswer() {
    if (!session) return;
    const draft = answerDraft.trim();
    if (!draft) return notify('先写下你的回答', 'error');
    const turn = session.turns.find((item) => item.turn_index === session.current_turn);
    if (!turn) return;
    setError('');
    setBusy('answering');
    try {
      const next = await api.socraticAnswer(session.id, session.current_turn, draft);
      setSession(next);
      setAnswerDraft('');
      await advance(next);
    } catch (reason) {
      // 失败保留输入：草稿不清空，用户可直接重试。
      setError(reason instanceof Error ? reason.message : '提交失败，请重试');
    } finally {
      setBusy('idle');
    }
  }

  async function finishEarly() {
    if (!session) return;
    if (session.turns.some((turn) => turn.turn_index === session.current_turn && session.state === 'awaiting_answer')
      && !answerDraft.trim() && !session.turns.some((t) => t.answer)) {
      return notify('至少回答一轮后再结束，书格拉底需要你的答案才能写报告', 'error');
    }
    setError('');
    setBusy('finishing');
    const requestId = ++requestIdRef.current;
    try {
      const pre = await api.socraticFinish(session.id);
      if (pre.report) {
        if (requestIdRef.current === requestId) setSession(pre);
        notify('已提前结束并生成理解报告');
        return;
      }
      const task = pre.task ?? session.task;
      if (!task) throw new Error('缺少报告生成任务，请稍后重试');
      const raw = await callCloudModel(task);
      const next = await api.socraticFinish(session.id, raw);
      if (requestIdRef.current === requestId) setSession(next);
      notify('已提前结束并生成理解报告');
    } catch (reason) {
      if (requestIdRef.current === requestId) setError(reason instanceof Error ? reason.message : '结束失败，请重试');
    } finally {
      if (requestIdRef.current === requestId) setBusy('idle');
    }
  }

  async function openHistory() {
    setPhase('history');
    setViewSession(null);
    try {
      setHistory(await api.socraticList());
    } catch (reason) {
      setHistory([]);
      notify(reason instanceof Error ? reason.message : '读取书格拉底记录失败', 'error');
    }
  }

  async function openSession(summaryId: string) {
    try {
      const detail = await api.socraticDetail(summaryId);
      setViewSession(detail);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '读取会话详情失败', 'error');
    }
  }

  function resumeSession(detail: SocraticSessionView) {
    setSession(detail);
    setPhase('active');
    setAnswerDraft('');
    setError('');
    void advance(detail);
  }

  if (phase === 'history') {
    return (
      <section className="socratic-paper" aria-label="书格拉底记录">
        <header className="socratic-history-heading">
          <div>
            <p className="eyebrow">SOCRATIC LOG</p>
            <h2>书格拉底记录</h2>
            <p className="muted">回看历次追问与理解报告；原始阅读笔记不会被改写。</p>
          </div>
          <button className="button" onClick={() => setPhase('config')}><GraduationCap size={17} />再开一局</button>
        </header>
        {viewSession ? (
          <div className="socratic-history-detail">
            <button className="button" onClick={() => setViewSession(null)}><MagnifyingGlass size={16} />返回记录列表</button>
            {viewSession.status === 'active'
              ? <button className="button primary" onClick={() => resumeSession(viewSession)}><ChatTeardropText size={16} />继续这个会话</button>
              : null}
            <SocraticTranscript session={viewSession} />
          </div>
        ) : (
          <div className="socratic-history-list">
            {history === null && <p className="muted">正在读取记录…</p>}
            {history?.length === 0 && <div className="empty-inline"><GraduationCap size={26} /><p>还没有书格拉底会话；开始一局，让追问帮你检查理解。</p></div>}
            {history?.map((item) => (
              <button key={item.id} className="socratic-history-item" onClick={() => void openSession(item.id)}>
                <strong>《{item.book_title}》</strong>
                <span>{item.rounds_planned} 轮 · 已答 {item.answered_turns} 轮 · {item.engine === 'cloud' ? '云端免密钥' : '我的 AI 连接'}</span>
                <span>{item.has_report ? '已生成理解报告' : item.status === 'active' ? '进行中' : '已结束'} · {formatDate(item.created_at)}</span>
              </button>
            ))}
          </div>
        )}
      </section>
    );
  }

  if (phase === 'active' && session) {
    const currentTurn = session.turns.find((item) => item.turn_index === session.current_turn) ?? null;
    const finished = session.status === 'finished' && session.report;
    return (
      <section className="socratic-paper" aria-label="书格拉底会话">
        <header className="socratic-session-heading">
          <div>
            <p className="eyebrow">SOCRATIC · {session.engine === 'cloud' ? '云端免密钥' : '我的 AI 连接'}</p>
            <h2>《{session.book_title}》</h2>
            <p className="muted">
              {finished ? `${session.rounds_planned} 轮追问完成` : `第 ${session.current_turn} / ${session.rounds_planned} 轮 · ${STATE_LABEL[session.state]}`}
              {' · '}证据固定为开始时已读的 {session.evidence.length} 条原文与笔记
            </p>
          </div>
          <button className="button" onClick={() => void openHistory()}><MagnifyingGlass size={16} />看记录</button>
        </header>

        {error && <div className="form-error" role="alert">{error}
          {(session.state === 'need_question' || session.state === 'need_feedback' || session.state === 'need_report') && (
            <button className="button socratic-retry" onClick={() => void advance(session)} disabled={busy !== 'idle'}>重试生成</button>
          )}
        </div>}

        <SocraticTranscript session={session} />

        {!finished && (
          <div className="socratic-current">
            {session.state === 'awaiting_answer' && currentTurn && (
              <form className="record-form" onSubmit={(event) => { event.preventDefault(); void submitAnswer(); }}>
                <div className="socratic-question-card">
                  <span className="socratic-kind-chip">{currentTurn.kind_label}</span>
                  <p className="socratic-question-text">{currentTurn.question}</p>
                  <small className="muted">只依据你读过的原文与自己的笔记作答；答不出来说“记不清”也可以，书格拉底会据此追问。</small>
                </div>
                <label>你的回答
                  <textarea rows={4} maxLength={4000} value={answerDraft} onChange={(event) => setAnswerDraft(event.target.value)} placeholder="用自己的话回答；不确定的地方直接写不确定。" disabled={busy !== 'idle'} />
                </label>
                <div className="socratic-actions">
                  <button className="button primary" type="submit" disabled={busy !== 'idle'}>
                    <ChatTeardropText size={17} />{busy === 'answering' ? '正在提交…' : busy === 'generating' ? '书格拉底正在思考…' : '提交回答'}
                  </button>
                  <button className="button" type="button" onClick={() => void finishEarly()} disabled={busy !== 'idle' || session.turns.every((turn) => !turn.answer)}>
                    提前结束并出报告
                  </button>
                </div>
              </form>
            )}
            {(session.state === 'need_question' || session.state === 'need_feedback' || session.state === 'need_report') && busy === 'idle' && !error && (
              <div className="socratic-waiting">
                <span className="socratic-thinking" aria-hidden="true" />
                <p>{session.state === 'need_report' ? '书格拉底正在整理理解报告…' : '书格拉底正在出下一问…'}</p>
                <button className="button" onClick={() => void advance(session)}>继续生成</button>
              </div>
            )}
            {busy !== 'idle' && session.state !== 'awaiting_answer' && (
              <div className="socratic-waiting" aria-live="polite">
                <span className="socratic-thinking" aria-hidden="true" />
                <p>{session.state === 'need_report' ? '正在生成理解报告…' : '书格拉底正在思考下一问…'}</p>
              </div>
            )}
          </div>
        )}

        {finished && (
          <div className="socratic-actions socratic-finished">
            <button className="button primary" onClick={() => { setPhase('config'); setSession(null); }}><GraduationCap size={17} />再开一局</button>
            <button className="button" onClick={() => void openHistory()}>查看全部记录</button>
          </div>
        )}
      </section>
    );
  }

  // config 阶段
  return (
    <section className="socratic-paper" aria-label="书格拉底设置">
      <form className="record-form socratic-config" onSubmit={(event) => { event.preventDefault(); void begin(); }}>
        <div className="socratic-intro">
          <GraduationCap size={30} />
          <div>
            <h2>书格拉底 · 苏格拉底式理解检查</h2>
            <p>书童负责解释书本；书格拉底反过来追问你：一轮一个开放式问题，检查你是否真的读懂了当前读的内容，最后给出理解报告和下一步书单。</p>
            <p className="muted">问题只基于<b>你已读的原文范围</b>与<b>你自己的笔记</b>，不会泄露未读内容，也不会替你回答。</p>
          </div>
        </div>
        <div className="time-fields">
          <label>图书
            <select value={bookId} onChange={(event) => setBookId(event.target.value)}>
              {books.map((book) => <option key={book.id} value={book.id}>{book.title}</option>)}
              {!books.length && <option value="">书房还没有书</option>}
            </select>
          </label>
          <label>追问轮数
            <select value={rounds} onChange={(event) => setRounds(Number(event.target.value))}>
              <option value={3}>3 轮（默认）</option>
              <option value={4}>4 轮</option>
              <option value={5}>5 轮</option>
            </select>
          </label>
        </div>
        <div className="time-fields">
          <label>回答方式
            <select value={engine} onChange={(event) => { const value = event.target.value as AiPrefs['engine']; setEngine(value); saveAiPrefs({ engine: value }); }}>
              <option value="byok">我的 AI 连接（自带 Key）</option>
              <option value="cloud">云端 AI（免密钥）</option>
            </select>
          </label>
          {engine === 'cloud' && (
            <label>云端模型
              <select value={cloudModelId} onChange={(event) => onCloudModelChange(event.target.value)}>
                {cloudModels.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}
                {!cloudModels.length && <option value="">暂无可用模型</option>}
              </select>
            </label>
          )}
        </div>
        {engine === 'cloud' && !cloudSession && !loadAiPrefs().allowAnonymousCloud && (
          <p className="form-error" role="alert">按你在「AI 设置」里的设置，使用云端 AI 前需要先到「云服务」页登录云端身份。</p>
        )}
        <p className="socratic-scope-hint">证据范围 = 当前已读范围：已确认的 read_ranges 原文段落 + 你的最新笔记。服务端会在开始时固化证据快照并校验每一轮引用。</p>
        <div className="socratic-actions">
          <button className="button primary" type="submit" disabled={busy !== 'idle' || !books.length || (engine === 'cloud' && (!cloudModelId || (!cloudSession && !loadAiPrefs().allowAnonymousCloud)))}>
            <GraduationCap size={18} />{busy === 'starting' ? '正在开局…' : '开始书格拉底'}
          </button>
          <button className="button" type="button" onClick={() => void openHistory()}>看历史记录</button>
        </div>
        {error && <div className="form-error" role="alert">{error}</div>}
        {!books.length && <p className="muted">先在书房导入或选择一本书，并至少记录一次阅读会话。</p>}
      </form>
    </section>
  );
}

function SocraticTranscript({ session }: { session: SocraticSessionView }) {
  const evidenceById = new Map(session.evidence.map((item) => [item.id, item]));
  // 等待回答时当前轮只在作答区显示一次；其余状态（含回看）完整展示。
  const transcriptTurns = session.state === 'awaiting_answer'
    ? session.turns.filter((turn) => turn.turn_index !== session.current_turn)
    : session.turns;
  return (
    <div className="socratic-transcript">
      {transcriptTurns.map((turn) => <SocraticTurnCard key={turn.turn_index} turn={turn} evidenceById={evidenceById} />)}
      {session.report && <SocraticReportCard session={session} />}
    </div>
  );
}

function SocraticTurnCard({ turn, evidenceById }: { turn: SocraticTurn; evidenceById: Map<string, SocraticEvidence> }) {
  return (
    <article className="socratic-turn">
      <header className="socratic-turn-head">
        <span className="socratic-turn-no">第 {turn.turn_index} 轮</span>
        <span className="socratic-kind-chip">{turn.kind_label}</span>
      </header>
      <p className="socratic-question-text">{turn.question}</p>
      {turn.question_evidence_ids.length > 0 && (
        <ul className="socratic-focus-list">
          {turn.question_evidence_ids.map((eid) => evidenceById.get(eid) && (
            <li key={eid}><BookOpenText size={13} /> {evidenceLabel(evidenceById.get(eid)!)}</li>
          ))}
        </ul>
      )}
      {turn.answer && <div className="socratic-answer"><span>我的回答</span><p>{turn.answer}</p></div>}
      {turn.feedback && (
        <div className="socratic-feedback">
          <span>书格拉底的反馈</span>
          <p>{turn.feedback}</p>
          {turn.feedback_evidence_ids.length > 0 && (
            <ul className="socratic-focus-list">
              {turn.feedback_evidence_ids.map((eid) => evidenceById.get(eid) && (
                <li key={eid}><BookOpenText size={13} /> {evidenceLabel(evidenceById.get(eid)!)}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </article>
  );
}

function SocraticReportCard({ session }: { session: SocraticSessionView }) {
  const report = session.report!;
  return (
    <article className="socratic-report" aria-label="理解报告">
      <header className="socratic-report-head">
        <div>
          <p className="eyebrow">COMPREHENSION REPORT</p>
          <h3>理解报告 · 《{session.book_title}》</h3>
        </div>
        <span>{formatDate(report.created_at)}</span>
      </header>
      <div className="socratic-report-grid">
        <section><h4>理解清楚的点</h4><ul>{report.clear_points.map((point, index) => <li key={index}>{point}</li>)}
          {!report.clear_points.length && <li className="muted">这一局还没有足够证据判定。</li>}</ul></section>
        <section><h4>模糊或证据不足的点</h4><ul>{report.vague_points.map((point, index) => <li key={index}>{point}</li>)}
          {!report.vague_points.length && <li className="muted">没有明显缺口。</li>}</ul></section>
        <section><h4>你自己的观点</h4><ul>{report.user_viewpoints.map((point, index) => <li key={index}>{point}</li>)}
          {!report.user_viewpoints.length && <li className="muted">这一局还没有形成明确观点。</li>}</ul></section>
        <section><h4>下一步追问建议</h4><ul>{report.follow_up_suggestions.map((point, index) => <li key={index}>{point}</li>)}
          {!report.follow_up_suggestions.length && <li className="muted">继续读下一章后再来一局。</li>}</ul></section>
      </div>
      {report.revisit_evidence.length > 0 && (
        <section className="socratic-revisit">
          <h4>建议回看的原文位置</h4>
          <div className="source-list">
            {report.revisit_evidence.map((item) => (
              <button key={item.id} className="source-entry" onClick={() => { window.location.hash = `#book/${item.book_id}`; }}>
                <span className={`source-kind ${item.kind === 'note' ? 'source-user' : 'source-author'}`}>{item.kind === 'note' ? '我的原话' : '书中内容'}</span>
                <strong>《{item.book_title}》{item.chapter_title ? ` · ${item.chapter_title}` : ''}{item.position !== null ? ` · 段落 #${item.position + 1}` : ''}</strong>
                <p>{item.excerpt}</p>
                <small><BookOpenText size={13} /> 点击回到书籍手账</small>
              </button>
            ))}
          </div>
        </section>
      )}
      <section className="socratic-recommendations">
        <h4>下一步书单{report.recommendations.length ? `（${report.recommendations.length} 本）` : ''}</h4>
        {report.recommendations.map((item) => (
          <div key={item.book_id} className="socratic-recommendation">
            <strong>《{item.title}》</strong>
            <span className="socratic-difficulty">{item.difficulty}</span>
            <p>{item.reason}</p>
            <small>关联：{item.related_theme} · 适合：{item.timing}</small>
          </div>
        ))}
        {report.recommendations.length === 0 && (
          <p className="muted socratic-no-recommendation"><Warning size={15} /> {report.recommendations_note ?? '暂无可推荐的书目；需要补充书目来源后再试。'}</p>
        )}
      </section>
    </article>
  );
}

function evidenceLabel(item: SocraticEvidence): string {
  const source = item.kind === 'note' ? '我的原话' : '书中内容';
  const position = item.position !== null ? ` · 段落 #${item.position + 1}` : '';
  const chapter = item.chapter_title ? ` · ${item.chapter_title}` : '';
  return `${source}${chapter}${position}`;
}
