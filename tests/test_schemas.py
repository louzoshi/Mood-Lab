import typing

import pytest
from pydantic import ValidationError

from server.presets import EMOTIONS
from boar_emotion_radar.schemas import AnalyzeTextRequest, Emotion, EmotionQuery, EmotionScores, Reply

SCRAPED = {
    "commentId": "1790000000000000001",
    "postId": "1789999999999999999",
    "profileUsername": "someprofile",
    "twitterUsername": "replier",
    "replyContent": "  Isso é incrível!  ",
    "likeCount": 12,
    "viewCount": 340,
    "replyCount": 1,
    "createdAt": "2026-09-28T12:00:00Z",
}


def test_emotions_match_mood_lab_presets():
    assert set(typing.get_args(Emotion)) == set(EMOTIONS)
    assert set(EmotionScores.model_fields) == set(EMOTIONS)


def test_reply_accepts_scraper_camel_case_and_dumps_snake_case():
    reply = Reply.model_validate(SCRAPED)
    assert reply.reply_content == "Isso é incrível!"
    assert reply.created_at.tzinfo is not None
    assert reply.model_dump()["comment_id"] == SCRAPED["commentId"]


def test_reply_accepts_snake_case():
    snake = Reply.model_validate(SCRAPED).model_dump()
    assert Reply.model_validate(snake).like_count == 12


def test_reply_counts_default_to_zero():
    data = {k: v for k, v in SCRAPED.items() if not k.endswith("Count")}
    assert Reply.model_validate(data).view_count == 0


@pytest.mark.parametrize("field, value", [("likeCount", -1), ("replyContent", "   "), ("commentId", "")])
def test_reply_rejects_bad_values(field, value):
    with pytest.raises(ValidationError):
        Reply.model_validate({**SCRAPED, field: value})


def test_emotion_scores_from_analyze_answers():
    # Shape of Mood Lab's POST /api/analyze "answers".
    answers = {eid: {"type": "noul", "value": 0.1} for eid in EMOTIONS}
    answers["surprise"]["value"] = 0.93
    scores = EmotionScores.from_answers(answers)
    assert scores.surprise == 0.93
    assert scores.dominant() == "surprise"


def test_emotion_scores_are_probabilities():
    with pytest.raises(ValidationError):
        EmotionScores(**{eid: 1.5 for eid in EMOTIONS})


def test_emotion_query_validation():
    assert EmotionQuery(username="x", emotion="anger").min_score == 0.8
    with pytest.raises(ValidationError):
        EmotionQuery(username="x", emotion="sarcasm")
    with pytest.raises(ValidationError):
        EmotionQuery(username="x", emotion="anger", min_score=1.2)


def test_analyze_text_length_limit():
    with pytest.raises(ValidationError):
        AnalyzeTextRequest(text="a" * 2001)
