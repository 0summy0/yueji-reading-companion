from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SpineStyle(StrictModel):
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    accent: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    material: Literal["cloth", "paper", "leather", "linen"] = "cloth"
    title_layout: Literal["vertical", "horizontal"] = "vertical"
    height: int = Field(ge=160, le=270)
    width: int = Field(ge=42, le=96)


class BookTitleUpdate(StrictModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("书名不能为空")
        return value.strip()


class SessionCreate(StrictModel):
    started_at: datetime
    ended_at: datetime
    timezone: str = Field(min_length=1, max_length=80)
    start_anchor: str | None = None
    current_anchor: str
    session_type: Literal["sequential", "skip", "reread"]
    sequential_confirmed: bool = False
    anchor_read_confirmed: bool = True
    reading_context: str | None = Field(default=None, max_length=1000)
    client_request_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_time(self):
        if self.started_at.tzinfo is None or self.ended_at.tzinfo is None:
            raise ValueError("时间必须包含时区")
        if self.ended_at < self.started_at:
            raise ValueError("结束时间不能早于开始时间")
        if self.sequential_confirmed and self.session_type != "sequential":
            raise ValueError("只有顺读会话可以确认连续范围")
        if self.session_type == "sequential" and self.sequential_confirmed and not self.start_anchor:
            raise ValueError("确认顺读范围时必须提供开始段落")
        return self


class NoteCreate(StrictModel):
    book_id: str
    session_id: str | None = None
    passage_id: str | None = None
    text: str = Field(min_length=1, max_length=5000)
    client_request_id: str | None = Field(default=None, max_length=100)

    @field_validator("text")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("笔记不能为空")
        return value.strip()


class NoteUpdate(StrictModel):
    text: str = Field(min_length=1, max_length=5000)
    passage_id: str | None = None

    @field_validator("text")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("笔记不能为空")
        return value.strip()


MockScenario = Literal[
    "success",
    "unsupported",
    "hallucinated",
    "partial",
    "auth_error",
    "rate_limited",
    "timeout",
]


class AIConnectionCreate(StrictModel):
    connection_id: str | None = None
    alias: str = Field(min_length=1, max_length=60)
    provider_type: Literal["mock", "openai_compatible"] = "openai_compatible"
    model_id: str = Field(default="deepseek-flash", min_length=1, max_length=120)
    base_url: str = Field(default="https://api.deepseek.com", min_length=1, max_length=300)
    scenario: MockScenario | None = None
    enabled: bool = True
    api_key: str | None = Field(default=None, exclude=True, max_length=4096)

    @model_validator(mode="after")
    def validate_provider(self):
        if self.provider_type == "mock":
            if not self.base_url.startswith("mock://"):
                raise ValueError("Mock Provider 必须使用 mock:// 地址")
            if self.scenario is None:
                self.scenario = "success"
        else:
            self.scenario = None
        return self


class TaskRoutesUpdate(StrictModel):
    routes: dict[
        Literal["generate_text", "analyze_image", "extract_structured", "embed_text", "ocr_page"],
        str,
    ]


class NoteExtractionCard(StrictModel):
    type: str = Field(max_length=60)
    speaker: Literal["author", "user", "ai"]
    epistemic_type: Literal["fact", "opinion", "question", "hypothesis", "feeling", "summary"]
    text: str = Field(max_length=2000)
    topics: list[str] = Field(default_factory=list, max_length=12)
    evidence_ids: list[str] = Field(max_length=30)
    confidence: Literal["low", "medium", "high"]
    review_status: Literal["suggested"] = "suggested"


class NoteExtractionResult(StrictModel):
    summary: str = Field(max_length=2000)
    cards: list[NoteExtractionCard] = Field(default_factory=list)
    candidate_links: list[dict] = Field(default_factory=list)


class EvidenceAnswer(StrictModel):
    answer: str
    citations: list[str]
    uncertainty: str
    follow_up_question: str | None = None
    spoiler_risk: Literal["low", "medium", "high"]


class AuthRegister(StrictModel):
    invite_code: str = Field(min_length=4, max_length=120)
    username: str = Field(min_length=2, max_length=30)
    password: str = Field(min_length=10, max_length=128)


class AuthLogin(StrictModel):
    username: str = Field(min_length=1, max_length=30)
    password: str = Field(min_length=1, max_length=128)


class AskRequest(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    book_id: str | None = None
    mode: Literal["book", "cross_book", "history"] = "book"


SocraticKind = Literal["fact", "causal", "judgment"]


class SocraticStart(StrictModel):
    book_id: str
    rounds: int = Field(default=3, ge=3, le=5)
    engine: Literal["byok", "cloud"] = "byok"
    client_request_id: str | None = Field(default=None, max_length=100)


class SocraticAnswer(StrictModel):
    turn_index: int = Field(ge=1, le=5)
    answer: str = Field(min_length=1, max_length=4000)

    @field_validator("answer")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("回答不能为空")
        return value.strip()


class SocraticGenerate(StrictModel):
    """BYOK 缺省 raw 由服务端调模型；云端免密钥模式把云模型原始 JSON 输出回传服务端校验。"""
    raw: str | None = Field(default=None, max_length=40000)


class SocraticQuestion(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    kind: SocraticKind
    focus_evidence_ids: list[str] = Field(default_factory=list, max_length=14)
    guidance: str | None = Field(default=None, max_length=400)


class SocraticFeedback(StrictModel):
    feedback: str = Field(min_length=1, max_length=2000)
    citations: list[str] = Field(default_factory=list, max_length=14)
    uncertainty: Literal["low", "medium", "high"]
    next_question: str | None = Field(default=None, max_length=1000)
    next_kind: SocraticKind | None = None


class SocraticRecommendation(StrictModel):
    book_id: str
    title: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=400)
    related_theme: str = Field(min_length=1, max_length=200)
    difficulty: Literal["轻松", "适中", "有挑战"]
    timing: str = Field(min_length=1, max_length=200)


class SocraticReport(StrictModel):
    clear_points: list[str] = Field(default_factory=list, max_length=10)
    vague_points: list[str] = Field(default_factory=list, max_length=10)
    user_viewpoints: list[str] = Field(default_factory=list, max_length=10)
    revisit_evidence_ids: list[str] = Field(default_factory=list, max_length=14)
    follow_up_suggestions: list[str] = Field(default_factory=list, max_length=6)
    recommendations: list[SocraticRecommendation] = Field(default_factory=list, max_length=3)


class LocationConfirm(StrictModel):
    chosen_anchor: str
    started_at: datetime
    ended_at: datetime
    timezone: str = Field(min_length=1, max_length=80)
    session_type: Literal["sequential", "skip", "reread"] = "skip"
    sequential_confirmed: bool = False
    anchor_read_confirmed: bool = True
    reading_context: str | None = Field(default=None, max_length=1000)
    client_request_id: str | None = Field(default=None, max_length=100)
