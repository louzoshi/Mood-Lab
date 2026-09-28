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


def test_posts_by_profile(con):
    store.upsert_replies(con, [reply(1), reply(2)])
    store.save_scores(con, [score("c001")])
    (post,) = store.posts(con, "@BOAR_app")
    assert (post.post_id, post.reply_total, post.analyzed_total) == ("p1", 2, 1)
    assert post.url == "https://x.com/boar_app/status/p1"
    assert store.posts(con, "nobody") == []


def test_post_dashboard(con):
    store.upsert_replies(con, [reply(1, "love it", likes=30), reply(2, "broken", likes=5),
                               reply(3, "gm", likes=1), reply(4, "pending")])
    store.save_scores(con, [
        score("c001", {"offline_praise": 0.9, "bug_report": 0.0}, joy=0.95),
        score("c002", {"bug_report": 0.8}, anger=0.6),
        score("c003", {"bug_report": 0.1}, joy=0.2),  # nothing reaches 0.5: neutral
    ])
    d = store.post_dashboard(con, "p1")
    assert (d.reply_total, d.analyzed_total, d.pending, d.like_total) == (4, 3, 1, 36)
    assert d.dominant_counts == {"joy": 1, "anger": 1, "neutral": 1}
    assert d.signal_counts == {"offline_praise": 1, "bug_report": 1}
    assert [r.comment_id for r in d.replies] == ["c001", "c002", "c003"]  # most liked first
    assert d.replies[2].dominant_emotion is None
    assert [r.comment_id for r in d.top_positive] == ["c001"]
    (alert,) = d.top_critical
    assert (alert.comment_id, alert.critical_reason, alert.critical_score) == ("c002", "bug_report", 0.8)
    assert d.mean_emotions.joy == pytest.approx((0.95 + 0.2) / 3)
    assert d.url == "https://x.com/boar_app/status/p1"


def test_post_dashboard_unknown_post(con):
    assert store.post_dashboard(con, "nope") is None


def test_profile_overview_counts_neutral(con):
    store.upsert_replies(con, [reply(1), reply(2)])
    store.save_scores(con, [score("c001", anger=0.9), score("c002", joy=0.3)])
    assert store.profile_overview(con, "boar_app").dominant_counts == {"anger": 1, "neutral": 1}
