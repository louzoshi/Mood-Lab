import pytest

from tests.factories import reply
from boar_emotion_radar import store
from boar_emotion_radar.db import connect
from boar_emotion_radar.schemas import EmotionQuery, EmotionScores

ZERO = dict.fromkeys(store.EMOTIONS, 0.0)


@pytest.fixture
def con():
    con = connect(":memory:")
    yield con
    con.close()


def score(cid: str, signals: dict | None = None, **emotions) -> store.Scored:
    return store.Scored(cid, EmotionScores(**{**ZERO, **emotions}), signals or {}, "laya", "m")


def test_pending_is_oldest_first_and_shrinks_as_scored(con):
    store.upsert_replies(con, [reply(2), reply(1), reply(3)])
    assert [cid for cid, _ in store.pending(con, 2)] == ["c001", "c002"]
    store.save_scores(con, [score("c001")])
    assert [cid for cid, _ in store.pending(con, 5)] == ["c002", "c003"]
    assert store.pending_count(con) == 2


def test_upsert_refreshes_counts_without_losing_scores(con):
    store.upsert_replies(con, [reply(1, likes=1)])
    store.save_scores(con, [score("c001", joy=0.9)])
    store.upsert_replies(con, [reply(1, likes=50)])
    assert store.pending_count(con) == 0
    (mood,) = store.replies_by_emotion(con, EmotionQuery(username="boar_app", emotion="joy"))
    assert mood.reply.like_count == 50


def test_profile_overview(con):
    store.upsert_replies(con, [reply(1, likes=10), reply(2, likes=5), reply(3), reply(4, profile="other")])
    store.save_scores(con, [
        score("c001", {"bug_report": 0.9, "offline_praise": 0.1}, anger=0.8, joy=0.1),
        score("c002", {"bug_report": 0.2, "offline_praise": 0.7}, joy=0.9),
    ])
    o = store.profile_overview(con, "@BOAR_app")
    assert (o.username, o.reply_total, o.analyzed_total, o.like_total, o.view_total) == (
        "boar_app", 3, 2, 15, 150)
    assert o.mean_emotions.joy == pytest.approx(0.5)
    assert o.dominant_emotion == "joy"
    assert o.dominant_counts == {"anger": 1, "joy": 1}
    assert o.signal_counts == {"bug_report": 1, "offline_praise": 1}


def test_profile_overview_without_data(con):
    o = store.profile_overview(con, "nobody")
    assert (o.reply_total, o.mean_emotions, o.dominant_emotion, o.like_total) == (0, None, None, 0)


def test_replies_by_emotion_filters_and_orders(con):
    store.upsert_replies(con, [reply(i, likes=i) for i in range(1, 5)])
    store.save_scores(con, [score("c001", anger=0.95), score("c002", anger=0.85, joy=0.9),
                            score("c003", anger=0.85, signals={"bug_report": 0.9}),
                            score("c004", anger=0.2)])
    moods = store.replies_by_emotion(con, EmotionQuery(username="boar_app", emotion="anger",
                                                       min_score=0.8))
    assert [m.reply.comment_id for m in moods] == ["c001", "c003", "c002"]  # ties: most liked first
    assert moods[1].signals == {"bug_report": 0.9}
    assert moods[2].dominant_emotion == "joy"
    limited = store.replies_by_emotion(con, EmotionQuery(username="boar_app", emotion="anger",
                                                         min_score=0.8, limit=1))
    assert len(limited) == 1
