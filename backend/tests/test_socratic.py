from __future__ import annotations

import json
from typing import Any

import pytest

from app import ai
from conftest import import_txt


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """书格拉底测试请求量大，重置进程级限流窗口，避免跨用例误判 429。"""
    from app import auth

    auth.rate_limiter._hits.clear()
    yield
    auth.rate_limiter._hits.clear()


class FakeSocraticProvider:
    """按调用顺序回放预设输出，记录提示词供断言；绝不发起网络请求。"""

    def __init__(self, outputs: list[dict[str, Any]]):
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    def extract_structured(self, prompt: str, schema_name: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        assert self.outputs, "意外的模型调用"
        return self.outputs.pop(0)

    def close(self):
        return None


class ExplodingProvider(FakeSocraticProvider):
    def extract_structured(self, prompt: str, schema_name: str) -> dict[str, Any]:
        from app.providers.base import ProviderError

        raise ProviderError("timeout", "模拟请求超时")


BOOK_CONTENT = "# 第一章 已读\n阿尔法段落讲灯塔的看守人。\n\n贝塔段落讲守灯人给船写信。\n\n# 第二章 未读\n未来章节的秘密结局。"


def question_output(kind: str = "fact", focus: list[str] | None = None) -> dict[str, Any]:
    return {
        "question": "看守人在第一章里做了什么？请只用你读过的内容回答。",
        "kind": kind,
        "focus_evidence_ids": focus or [],
        "guidance": "想想信这个物件出现了几次。",
    }


def feedback_output(citations: list[str] | None = None, next_question: str | None = None, next_kind: str | None = None) -> dict[str, Any]:
    return {
        "feedback": "你记住了写信的细节；灯塔的动机还需要回到原文。",
        "citations": citations or [],
        "uncertainty": "medium",
        "next_question": next_question,
        "next_kind": next_kind,
    }


def report_output(revisit: list[str] | None = None, recommendations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "clear_points": ["记住了看守人写信的事实。"],
        "vague_points": ["看守人写信的动机证据不足。"],
        "user_viewpoints": ["你认为写信是一种守望。"],
        "revisit_evidence_ids": revisit or [],
        "follow_up_suggestions": ["重读后问自己：信为什么没有被寄出。"],
        "recommendations": recommendations or [],
    }


@pytest.fixture
def socratic_setup(client):
    book = import_txt(client, BOOK_CONTENT, filename="socratic.txt", title="书格拉底测试书")
    items = client.get(f"/api/books/{book['id']}/passages").json()["items"]
    session = client.post(f"/api/books/{book['id']}/sessions", json={
        "started_at": "2026-10-25T03:00:00+08:00", "ended_at": "2026-10-25T03:10:00+08:00",
        "timezone": "Asia/Shanghai", "start_anchor": items[0]["id"], "current_anchor": items[1]["id"],
        "session_type": "sequential", "sequential_confirmed": True, "anchor_read_confirmed": True,
    })
    assert session.status_code == 201
    note = client.post("/api/notes", json={"book_id": book["id"], "passage_id": items[0]["id"], "text": "我认为写信是看守人表达守望的方式。"})
    assert note.status_code == 201
    connection = client.post("/api/ai/connections", json={"alias": "书格拉底", "provider_type": "mock", "model_id": "mock-reader-v1", "base_url": "mock://local", "scenario": "success"}).json()
    assert client.put("/api/ai/task-routes", json={"routes": {"generate_text": connection["id"]}}).status_code == 200
    return client, book, items, note.json()


def start_session(client, book_id: str, rounds: int = 3, **extra) -> Any:
    return client.post("/api/socratic/start", json={"book_id": book_id, "rounds": rounds, **extra})


def test_socratic_snapshot_only_read_evidence_and_notes(socratic_setup):
    """证据快照只含已读段落与最新笔记；未读章节绝不进入。"""
    client, book, items, note = socratic_setup
    response = start_session(client, book["id"])
    assert response.status_code == 201, response.text
    body = response.json()
    ids = {item["id"] for item in body["evidence"]}
    assert f"pa:{items[0]['id']}" in ids and f"pa:{items[1]['id']}" in ids
    assert f"nv:{note['current_version_id']}" in ids
    assert f"pa:{items[2]['id']}" not in ids
    for item in body["evidence"]:
        assert "未来章节" not in item["excerpt"]


def test_socratic_requires_evidence_before_start(socratic_setup):
    client, _, _, _ = socratic_setup
    empty_book = import_txt(client, "没有阅读记录的段落。", filename="no-evidence.txt", title="无证据书")
    response = start_session(client, empty_book["id"])
    assert response.status_code == 400
    assert "已读范围" in response.json()["detail"]
    assert client.get("/api/socratic").json()["items"] == []


def test_socratic_byok_requires_verified_connection(socratic_setup):
    client, book, _, _ = socratic_setup
    assert client.put("/api/ai/task-routes", json={"routes": {}}).status_code == 200
    response = start_session(client, book["id"])
    assert response.status_code == 400
    assert "文字检测" in response.json()["detail"]
    # 安全降级：不产生半成品会话。
    assert client.get("/api/socratic").json()["items"] == []


def test_socratic_rounds_must_be_3_to_5(socratic_setup):
    client, book, _, _ = socratic_setup
    assert start_session(client, book["id"], rounds=2).status_code == 422
    assert start_session(client, book["id"], rounds=6).status_code == 422
    assert start_session(client, book["id"], rounds=3).status_code == 201
    assert start_session(client, book["id"], rounds=5).status_code == 201


def test_socratic_full_flow_persists_turns_and_report(socratic_setup, monkeypatch):
    client, book, items, note = socratic_setup
    first_pa = f"pa:{items[0]['id']}"
    provider = FakeSocraticProvider([
        question_output("fact", [first_pa]),
        feedback_output([first_pa], "看守人为什么坚持给船写信？", "causal"),
        feedback_output([first_pa], "你自己如何评价这种守望？", "judgment"),
        feedback_output([first_pa], None, None),
        report_output([first_pa]),
    ])
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: provider)
    session = start_session(client, book["id"]).json()

    gen = client.post(f"/api/socratic/{session['id']}/generate", json={})
    assert gen.status_code == 200, gen.text
    turn1 = gen.json()["turns"][0]
    assert turn1["kind"] == "fact" and turn1["question_evidence_ids"] == [first_pa]

    ans = client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "他每天记录天气并给船写信。"})
    assert ans.status_code == 200, ans.text

    gen = client.post(f"/api/socratic/{session['id']}/generate", json={})
    assert gen.status_code == 200
    assert gen.json()["turns"][0]["feedback"] is not None
    assert gen.json()["turns"][1]["kind"] == "causal"

    client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 2, "answer": "我觉得是他害怕被忘记。"})
    client.post(f"/api/socratic/{session['id']}/generate", json={})
    client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 3, "answer": "守望是主动的选择。"})
    gen = client.post(f"/api/socratic/{session['id']}/generate", json={})
    assert gen.status_code == 200
    assert gen.json()["state"] == "need_report"

    done = client.post(f"/api/socratic/{session['id']}/finish", json={})
    assert done.status_code == 200, done.text
    report = done.json()["report"]
    assert report["clear_points"] and report["user_viewpoints"] and report["follow_up_suggestions"]
    assert report["revisit_evidence"][0]["id"] == first_pa

    # 作者原文、用户回答、AI 反馈分开保存。
    detail = client.get(f"/api/socratic/{session['id']}").json()
    assert len(detail["turns"]) == 3
    assert detail["turns"][0]["answer"] == "他每天记录天气并给船写信。"
    assert detail["turns"][0]["feedback"] and detail["turns"][2]["feedback"]
    assert detail["status"] == "finished" and detail["report"] is not None
    # 提示词里从未出现未读章节。
    joined = "\n".join(provider.prompts)
    assert "未来章节" not in joined


def test_socratic_kind_plan_is_enforced(socratic_setup, monkeypatch):
    client, book, _, _ = socratic_setup
    provider = FakeSocraticProvider([question_output("judgment")])  # 计划要求第 1 轮 fact
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: provider)
    session = start_session(client, book["id"]).json()
    response = client.post(f"/api/socratic/{session['id']}/generate", json={})
    assert response.status_code == 502
    assert "层次" in response.json()["detail"]


def test_socratic_question_focus_outside_snapshot_rejected(socratic_setup, monkeypatch):
    client, book, _, _ = socratic_setup
    provider = FakeSocraticProvider([question_output("fact", ["pa:not-in-snapshot"])])
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: provider)
    session = start_session(client, book["id"]).json()
    response = client.post(f"/api/socratic/{session['id']}/generate", json={})
    assert response.status_code == 502
    assert "不存在的证据" in response.json()["detail"]


def test_socratic_feedback_citations_outside_snapshot_rejected(socratic_setup, monkeypatch):
    client, book, _, _ = socratic_setup
    provider = FakeSocraticProvider([
        question_output("fact"),
        feedback_output(["pa:future-fake"], "为什么写信？", "causal"),
    ])
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: provider)
    session = start_session(client, book["id"]).json()
    client.post(f"/api/socratic/{session['id']}/generate", json={})
    client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "他给船写信。"})
    response = client.post(f"/api/socratic/{session['id']}/generate", json={})
    assert response.status_code == 502
    assert "不存在的证据" in response.json()["detail"]


def test_socratic_answer_idempotency_and_conflict(socratic_setup, monkeypatch):
    client, book, _, _ = socratic_setup
    provider = FakeSocraticProvider([question_output("fact")])
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: provider)
    session = start_session(client, book["id"]).json()
    client.post(f"/api/socratic/{session['id']}/generate", json={})
    first = client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "他给船写信。"})
    assert first.status_code == 200
    replay = client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "他给船写信。"})
    assert replay.status_code == 200 and replay.json()["duplicate"] is True
    conflict = client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "改一个说法。"})
    assert conflict.status_code == 409


def test_socratic_start_is_idempotent_per_client_request_id(socratic_setup):
    client, book, _, _ = socratic_setup
    first = client.post("/api/socratic/start", json={"book_id": book["id"], "rounds": 3, "client_request_id": "socratic-req-1"})
    assert first.status_code == 201
    replay = client.post("/api/socratic/start", json={"book_id": book["id"], "rounds": 3, "client_request_id": "socratic-req-1"})
    assert replay.status_code == 201 and replay.json()["id"] == first.json()["id"] and replay.json()["duplicate"] is True
    mismatch = client.post("/api/socratic/start", json={"book_id": book["id"], "rounds": 4, "client_request_id": "socratic-req-1"})
    assert mismatch.status_code == 409
    assert client.get("/api/socratic").json()["items"] and len(client.get("/api/socratic").json()["items"]) == 1


def test_socratic_early_finish_generates_report(socratic_setup, monkeypatch):
    client, book, items, _ = socratic_setup
    provider = FakeSocraticProvider([
        question_output("fact"),
        report_output([f"pa:{items[0]['id']}"]),
    ])
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: provider)
    session = start_session(client, book["id"]).json()
    client.post(f"/api/socratic/{session['id']}/generate", json={})
    client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "他给船写信。"})
    # 已回答但未生成反馈时提前结束：报告仍要覆盖已答内容。
    done = client.post(f"/api/socratic/{session['id']}/finish", json={})
    assert done.status_code == 200, done.text
    assert done.json()["report"]["follow_up_suggestions"]
    # finish 幂等：重复调用返回同一份报告。
    again = client.post(f"/api/socratic/{session['id']}/finish", json={})
    assert again.status_code == 200 and again.json()["duplicate"] is True


def test_socratic_report_rejects_note_id_as_revisit(socratic_setup, monkeypatch):
    client, book, items, note = socratic_setup
    provider = FakeSocraticProvider([
        question_output("fact"),
        report_output([f"nv:{note['current_version_id']}"]),  # 回看位置必须是原文段落
    ])
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: provider)
    session = start_session(client, book["id"]).json()
    client.post(f"/api/socratic/{session['id']}/generate", json={})
    client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "他给船写信。"})
    response = client.post(f"/api/socratic/{session['id']}/finish", json={})
    assert response.status_code == 502
    assert "原文段落" in response.json()["detail"]


def test_socratic_recommendations_only_from_shelf(socratic_setup, monkeypatch):
    client, book, items, _ = socratic_setup
    other = import_txt(client, "另一本书的内容。\n\n第二段。", filename="shelf-book.txt", title="书架上的另一本书")
    other_items = client.get(f"/api/books/{other['id']}/passages").json()["items"]
    session_other = client.post(f"/api/books/{other['id']}/sessions", json={
        "started_at": "2026-10-25T04:00:00+08:00", "ended_at": "2026-10-25T04:10:00+08:00",
        "timezone": "Asia/Shanghai", "start_anchor": other_items[0]["id"], "current_anchor": other_items[0]["id"],
        "session_type": "skip", "sequential_confirmed": False, "anchor_read_confirmed": True,
    })
    assert session_other.status_code == 201
    provider = FakeSocraticProvider([
        question_output("fact"),
        report_output([f"pa:{items[0]['id']}"], [{
            "book_id": other["id"], "title": "书架上的另一本书", "reason": "同样关注守望主题。",
            "related_theme": "守望与等待", "difficulty": "适中", "timing": "读完当前章后",
        }]),
    ])
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: provider)
    session = start_session(client, book["id"]).json()
    client.post(f"/api/socratic/{session['id']}/generate", json={})
    client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "他给船写信。"})
    done = client.post(f"/api/socratic/{session['id']}/finish", json={})
    assert done.status_code == 200, done.text
    recommendations = done.json()["report"]["recommendations"]
    assert len(recommendations) == 1 and recommendations[0]["book_id"] == other["id"]


def test_socratic_no_shelf_candidates_yields_honest_note(socratic_setup, monkeypatch):
    """书架没有其他书时：推荐必须为空并明确说明需要补充书目来源，不得编造。"""
    client, book, items, _ = socratic_setup
    provider = FakeSocraticProvider([
        question_output("fact"),
        report_output([f"pa:{items[0]['id']}"]),
    ])
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: provider)
    session = start_session(client, book["id"]).json()
    client.post(f"/api/socratic/{session['id']}/generate", json={})
    client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "他给船写信。"})
    done = client.post(f"/api/socratic/{session['id']}/finish", json={})
    assert done.status_code == 200
    report = done.json()["report"]
    assert report["recommendations"] == []
    assert report["recommendations_note"] and "补充书目" in report["recommendations_note"]


def test_socratic_report_rejects_fabricated_book(socratic_setup, monkeypatch):
    client, book, items, _ = socratic_setup
    provider = FakeSocraticProvider([
        question_output("fact"),
        report_output([f"pa:{items[0]['id']}"], [{
            "book_id": "bk_fabricated", "title": "不存在的书", "reason": "编造", "related_theme": "无",
            "difficulty": "轻松", "timing": "随时",
        }]),
    ])
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: provider)
    session = start_session(client, book["id"]).json()
    client.post(f"/api/socratic/{session['id']}/generate", json={})
    client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "他给船写信。"})
    response = client.post(f"/api/socratic/{session['id']}/finish", json={})
    assert response.status_code == 502
    assert "书架之外" in response.json()["detail"]


def test_socratic_provider_error_fails_openly(socratic_setup, monkeypatch):
    """模型调用失败时明确 502，不落库、不假装成功。"""
    client, book, _, _ = socratic_setup
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: ExplodingProvider([]))
    session = start_session(client, book["id"]).json()
    response = client.post(f"/api/socratic/{session['id']}/generate", json={})
    assert response.status_code == 502
    detail = client.get(f"/api/socratic/{session['id']}").json()
    assert detail["state"] == "need_question" and not detail["turns"]


def test_socratic_cloud_engine_roundtrip_via_raw(socratic_setup):
    """云端免密钥：服务端出提示词与校验，模型输出以 raw 回传，证据约束仍在服务端。"""
    client, book, items, _ = socratic_setup
    first_pa = f"pa:{items[0]['id']}"
    session = start_session(client, book["id"], engine="cloud").json()
    assert session["engine"] == "cloud"
    task = session["task"]
    assert task["stage"] == "question" and task["prompt"]["messages"][0]["role"] == "system"

    cloud_question = question_output("fact", [first_pa])
    gen = client.post(f"/api/socratic/{session['id']}/generate", json={"raw": json.dumps(cloud_question, ensure_ascii=False)})
    assert gen.status_code == 200, gen.text
    assert gen.json()["turns"][0]["question"] == cloud_question["question"]

    client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "他给船写信。"})

    cloud_feedback = feedback_output([first_pa], "为什么写信对看守人这么重要？", "causal")
    gen = client.post(f"/api/socratic/{session['id']}/generate", json={"raw": json.dumps(cloud_feedback, ensure_ascii=False)})
    assert gen.status_code == 200, gen.text
    assert gen.json()["state"] == "awaiting_answer" and gen.json()["turns"][1]["kind"] == "causal"

    client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 2, "answer": "写信是他唯一的表达方式。"})
    cloud_feedback2 = feedback_output([first_pa], "你怎么评价这种唯一的表达方式？", "judgment")
    gen = client.post(f"/api/socratic/{session['id']}/generate", json={"raw": json.dumps(cloud_feedback2, ensure_ascii=False)})
    assert gen.status_code == 200, gen.text
    assert gen.json()["state"] == "awaiting_answer" and gen.json()["turns"][2]["kind"] == "judgment"

    client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 3, "answer": "守望是主动的选择。"})
    cloud_feedback3 = feedback_output([first_pa], None, None)
    gen = client.post(f"/api/socratic/{session['id']}/generate", json={"raw": json.dumps(cloud_feedback3, ensure_ascii=False)})
    assert gen.status_code == 200, gen.text
    assert gen.json()["state"] == "need_report"

    # finish 无 raw：返回报告提示词供云模型生成。
    pre = client.post(f"/api/socratic/{session['id']}/finish", json={})
    assert pre.status_code == 200 and pre.json()["task"]["stage"] == "report"

    cloud_report = report_output([first_pa])
    done = client.post(f"/api/socratic/{session['id']}/finish", json={"raw": json.dumps(cloud_report, ensure_ascii=False)})
    assert done.status_code == 200, done.text
    assert done.json()["report"]["clear_points"] == cloud_report["clear_points"]


def test_socratic_cloud_raw_with_invalid_json_rejected(socratic_setup):
    client, book, _, _ = socratic_setup
    session = start_session(client, book["id"], engine="cloud").json()
    response = client.post(f"/api/socratic/{session['id']}/generate", json={"raw": "不是 JSON"})
    assert response.status_code == 502
    assert "有效 JSON" in response.json()["detail"]


def test_socratic_delete_book_cascades_sessions(socratic_setup, monkeypatch):
    client, book, items, _ = socratic_setup
    provider = FakeSocraticProvider([
        question_output("fact"),
        feedback_output([], None, None),
        report_output([f"pa:{items[0]['id']}"]),
    ])
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: provider)
    session = start_session(client, book["id"]).json()
    client.post(f"/api/socratic/{session['id']}/generate", json={})
    client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "他给船写信。"})
    client.post(f"/api/socratic/{session['id']}/generate", json={})
    client.post(f"/api/socratic/{session['id']}/finish", json={})
    assert client.get(f"/api/socratic/{session['id']}").json()["report"]

    response = client.delete(f"/api/books/{book['id']}")
    assert response.status_code == 200, response.text
    assert client.get("/api/socratic").json()["items"] == []
    assert client.get(f"/api/socratic/{session['id']}").status_code == 404
    # 普通书架与阅读数据不受影响。
    assert client.get("/api/books").json()["items"] == []


def test_socratic_answer_before_question_rejected(socratic_setup):
    client, book, _, _ = socratic_setup
    session = start_session(client, book["id"]).json()
    response = client.post(f"/api/socratic/{session['id']}/answer", json={"turn_index": 1, "answer": "还没有问题。"})
    assert response.status_code == 409


def test_socratic_generate_is_idempotent_after_success(socratic_setup, monkeypatch):
    client, book, _, _ = socratic_setup
    provider = FakeSocraticProvider([question_output("fact")])
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: provider)
    session = start_session(client, book["id"]).json()
    first = client.post(f"/api/socratic/{session['id']}/generate", json={})
    assert first.status_code == 200
    # 生成成功后响应丢失，客户端重试：返回现状，不再调用模型。
    replay = client.post(f"/api/socratic/{session['id']}/generate", json={})
    assert replay.status_code == 200 and replay.json()["duplicate"] is True
    assert len(provider.prompts) == 1
