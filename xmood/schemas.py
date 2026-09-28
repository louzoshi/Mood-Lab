"""Pydantic schemas shared by ingestion, the LLM-facing API/MCP tools and the dashboard.

Scraper output is camelCase (`commentId`, `replyContent`, ...); models accept either that or
the snake_case field names, and serialize as snake_case.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# Same ids as server/presets.EMOTIONS; tests/test_schemas.py keeps the two in sync.
Emotion = Literal["joy", "sadness", "anger", "fear", "surprise", "disgust", "bluff"]
MAX_TEXT_CHARS = 2000  # Mood Lab's /api/analyze limit (server/app.py)


class Reply(BaseModel):
    """One scraped reply plus the post/profile it was scraped from."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True,
                              str_strip_whitespace=True)

    comment_id: str = Field(min_length=1)
    post_id: str = Field(min_length=1)
    profile_username: str = Field(min_length=1)
    twitter_username: str = Field(min_length=1)
    reply_content: str = Field(min_length=1)
    like_count: int = Field(default=0, ge=0)
    view_count: int = Field(default=0, ge=0)
    reply_count: int = Field(default=0, ge=0)
    created_at: datetime


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
    """A reply with its emotion vector (a row of replies JOIN reply_emotions)."""

    reply: Reply
    emotions: EmotionScores
    dominant_emotion: Emotion
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


class EmotionQuery(BaseModel):
    """`query_replies_by_emotion(username, emotion, min_score)`."""

    username: str = Field(min_length=1)
    emotion: Emotion
    min_score: float = Field(default=0.8, ge=0.0, le=1.0)
    limit: int = Field(default=50, ge=1, le=1000)


class AnalyzeTextRequest(BaseModel):
    """`analyze_text_sentiment(text)`."""

    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


class TextSentiment(BaseModel):
    emotions: EmotionScores
    dominant_emotion: Emotion
    backend: Literal["laya", "jev"]
    model: str
    latency_ms: int
