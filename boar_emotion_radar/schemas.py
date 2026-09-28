"""Pydantic schemas shared by ingestion, the LLM-facing API/MCP tools and the dashboard.

Scraper output is camelCase (`commentId`, `replyContent`, ...); models accept either that or
the snake_case field names, and serialize as snake_case.
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import AliasGenerator, BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

# Same ids as server/presets.EMOTIONS; tests/test_schemas.py keeps the two in sync.
Emotion = Literal["joy", "sadness", "anger", "fear", "surprise", "disgust", "bluff"]
MAX_TEXT_CHARS = 2000  # Mood Lab's /api/analyze limit (server/app.py)
TWITTER_TIME = "%a %b %d %H:%M:%S %z %Y"  # "Wed Oct 10 20:19:24 +0000 2018"
_SUFFIX = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def username(name: str) -> str:
    """X usernames are case-insensitive; store and query them as `boar_app`."""
    return name.strip().removeprefix("@").lower()


class Reply(BaseModel):
    """One scraped reply plus the post/profile it was scraped from."""

    # camelCase accepted on input only, so API responses stay snake_case.
    model_config = ConfigDict(alias_generator=AliasGenerator(validation_alias=to_camel),
                              validate_by_name=True, str_strip_whitespace=True)

    comment_id: str = Field(min_length=1)
    post_id: str = Field(min_length=1)
    profile_username: str = Field(min_length=1)
    twitter_username: str = Field(min_length=1)
    reply_content: str = Field(min_length=1)
    like_count: int = Field(default=0, ge=0)
    view_count: int = Field(default=0, ge=0)
    reply_count: int = Field(default=0, ge=0)
    created_at: datetime

    @field_validator("profile_username", "twitter_username")
    @classmethod
    def _username(cls, v: str) -> str:
        return username(v)

    @field_validator("like_count", "view_count", "reply_count", mode="before")
    @classmethod
    def _count(cls, v):
        """The scraper returns viewCount as text: "1,234", "1.2K", "3M", or null."""
        if v is None or v == "":
            return 0
        if isinstance(v, str):
            m = re.fullmatch(r"([\d.]+)\s*([KMB]?)", v.replace(",", "").strip().upper())
            if not m:
                raise ValueError(f"not a count: {v!r}")
            return round(float(m[1]) * _SUFFIX[m[2]])
        return v

    @field_validator("created_at", mode="before")
    @classmethod
    def _twitter_time(cls, v):
        if isinstance(v, str):
            try:
                return datetime.strptime(v, TWITTER_TIME)
            except ValueError:
                pass  # ISO 8601, handled by pydantic
        return v


class EmotionScores(BaseModel):
    """P(yes) per emotion, from Mood Lab's yes/no questions."""

    joy: float = Field(ge=0.0, le=1.0)
    sadness: float = Field(ge=0.0, le=1.0)
    anger: float = Field(ge=0.0, le=1.0)
    fear: float = Field(ge=0.0, le=1.0)
    surprise: float = Field(ge=0.0, le=1.0)
    disgust: float = Field(ge=0.0, le=1.0)
    bluff: float = Field(ge=0.0, le=1.0)

    @classmethod
    def from_answers(cls, answers: dict) -> "EmotionScores":
        """Build from a Mood Lab `/api/analyze` response's `answers`."""
        return cls(**{eid: answers[eid]["value"] for eid in cls.model_fields})

    def dominant(self) -> Emotion:
        return max(type(self).model_fields, key=lambda eid: getattr(self, eid))


class ReplyMood(BaseModel):
    """A reply with its emotion vector and BOAR signals (P(yes) per boar_emotion_radar/questions.py id)."""

    reply: Reply
    emotions: EmotionScores
    dominant_emotion: Emotion
    signals: dict[str, float] = {}
    backend: Literal["laya", "jev"]
    model: str
    analyzed_at: datetime


class ProfileOverview(BaseModel):
    """`get_profile_overview(username)`: engagement totals and emotional summary."""

    username: str
    reply_total: int = Field(ge=0)
    analyzed_total: int = Field(ge=0)
    first_reply_at: datetime | None = None
    last_reply_at: datetime | None = None
    like_total: int = Field(ge=0)
    view_total: int = Field(ge=0)
    mean_emotions: EmotionScores | None = None  # None until a reply has been analyzed
    dominant_emotion: Emotion | None = None
    dominant_counts: dict[Emotion, int] = {}  # replies whose top emotion is each one
    signal_counts: dict[str, int] = {}  # replies answering yes (>= 0.5) to each BOAR question


class EmotionQuery(BaseModel):
    """`query_replies_by_emotion(username, emotion, min_score)`."""

    username: str = Field(min_length=1)
    emotion: Emotion
    min_score: float = Field(default=0.8, ge=0.0, le=1.0)
    limit: int = Field(default=50, ge=1, le=1000)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return username(v)


class AnalyzeTextRequest(BaseModel):
    """`analyze_text_sentiment(text)`."""

    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


class TextSentiment(BaseModel):
    emotions: EmotionScores
    dominant_emotion: Emotion
    signals: dict[str, float] = {}
    backend: Literal["laya", "jev"]
    model: str
    latency_ms: int


class IngestRequest(BaseModel):
    """Store the replies to one post: scraped through Apify (`items` omitted) or imported from
    an actor dataset export (`items` given)."""

    post_url: str = Field(min_length=1)
    items: list[dict] | None = None
    max_items: int = Field(default=200, ge=1, le=5000)


class IngestResult(BaseModel):
    post_id: str
    profile_username: str
    stored: int
    skipped: int  # items without text or id, e.g. deleted replies
