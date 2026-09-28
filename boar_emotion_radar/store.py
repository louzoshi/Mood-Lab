"""Reads and writes on the DuckDB tables (boar_emotion_radar/migrations).

`replies` doubles as the work queue: a reply without a `reply_emotions` row is pending.
Functions take a connection; callers on other threads pass `con.cursor()`.
"""

from dataclasses import dataclass

import duckdb

from .schemas import (DashboardReply, EmotionQuery, EmotionScores, PostDashboard, PostSummary,
                      ProfileOverview, Reply, ReplyMood, username)

EMOTIONS = list(EmotionScores.model_fields)
YES = 0.5  # P(yes) at which a signal counts as answered yes, or an emotion as present
CRITICAL = ("anger", "disgust", "bug_report")  # what makes a reply an alert for the team
MAX_DASHBOARD_REPLIES = 1000
TOP_N = 5

_REPLY_COLS = list(Reply.model_fields)
_GREATEST = "greatest({})".format(", ".join(f"e.{e}" for e in EMOTIONS))
_DOMINANT = "CASE WHEN {g} < {yes} THEN 'neutral' {whens} END".format(
    g=_GREATEST, yes=YES, whens=" ".join(f"WHEN {_GREATEST} = e.{e} THEN '{e}'" for e in EMOTIONS))


@dataclass
class Scored:
    comment_id: str
    emotions: EmotionScores
    signals: dict[str, float]
    backend: str
    model: str


def _dicts(cur: duckdb.DuckDBPyConnection) -> list[dict]:
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def upsert_replies(con: duckdb.DuckDBPyConnection, replies: list[Reply]) -> int:
    """Insert new replies; for ones already stored, refresh only the engagement counts."""
    if not replies:
        return 0
    con.executemany(f"""
        INSERT INTO replies ({", ".join(_REPLY_COLS)}) VALUES ({", ".join("?" * len(_REPLY_COLS))})
        ON CONFLICT (comment_id) DO UPDATE SET
            like_count = excluded.like_count, view_count = excluded.view_count,
            reply_count = excluded.reply_count, scraped_at = now()
    """, [[getattr(r, c) for c in _REPLY_COLS] for r in replies])
    return len(replies)


def pending(con: duckdb.DuckDBPyConnection, limit: int) -> list[tuple[str, str]]:
    """(comment_id, text) of the oldest replies with no emotion scores yet."""
    return con.execute("""
        SELECT r.comment_id, r.reply_content FROM replies r
        LEFT JOIN reply_emotions e USING (comment_id)
        WHERE e.comment_id IS NULL
        ORDER BY r.created_at, r.comment_id
        LIMIT ?
    """, [limit]).fetchall()


def pending_count(con: duckdb.DuckDBPyConnection) -> int:
    return con.execute("""
        SELECT count(*) FROM replies r LEFT JOIN reply_emotions e USING (comment_id)
        WHERE e.comment_id IS NULL
    """).fetchone()[0]


def save_scores(con: duckdb.DuckDBPyConnection, scored: list[Scored]) -> None:
    """Write a batch's emotions and signals in one transaction."""
    if not scored:
        return
    con.execute("BEGIN")
    try:
        con.executemany(f"""
            INSERT OR REPLACE INTO reply_emotions (comment_id, {", ".join(EMOTIONS)}, backend, model)
            VALUES (?, {", ".join("?" * len(EMOTIONS))}, ?, ?)
        """, [[s.comment_id, *(getattr(s.emotions, e) for e in EMOTIONS), s.backend, s.model]
              for s in scored])
        signals = [[s.comment_id, qid, v] for s in scored for qid, v in s.signals.items()]
        if signals:
            con.executemany("INSERT OR REPLACE INTO reply_signals VALUES (?, ?, ?)", signals)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def profile_overview(con: duckdb.DuckDBPyConnection, name: str) -> ProfileOverview:
    name = username(name)
    row = _dicts(con.execute(f"""
        SELECT count(*) AS reply_total, count(e.comment_id) AS analyzed_total,
               min(r.created_at) AS first_reply_at, max(r.created_at) AS last_reply_at,
               coalesce(sum(r.like_count), 0) AS like_total,
               coalesce(sum(r.view_count), 0) AS view_total,
               {", ".join(f"avg(e.{e}) AS {e}" for e in EMOTIONS)}
        FROM replies r LEFT JOIN reply_emotions e USING (comment_id)
        WHERE r.profile_username = ?
    """, [name]))[0]
    means = {e: row.pop(e) for e in EMOTIONS}
    mean = EmotionScores(**means) if row["analyzed_total"] else None

    dominant_counts = dict(con.execute(f"""
        SELECT {_DOMINANT} AS emotion, count(*) FROM replies r
        JOIN reply_emotions e USING (comment_id)
        WHERE r.profile_username = ? GROUP BY emotion ORDER BY emotion
    """, [name]).fetchall())
    signal_counts = dict(con.execute("""
        SELECT s.question_id, count(*) FILTER (WHERE s.value >= ?) FROM reply_signals s
        JOIN replies r USING (comment_id)
        WHERE r.profile_username = ? GROUP BY s.question_id ORDER BY s.question_id
    """, [YES, name]).fetchall())
    return ProfileOverview(username=name, **row, mean_emotions=mean,
                           dominant_emotion=mean.dominant() if mean else None,
                           dominant_counts=dominant_counts, signal_counts=signal_counts)


def replies_by_emotion(con: duckdb.DuckDBPyConnection, q: EmotionQuery) -> list[ReplyMood]:
    """Replies at or above `min_score` for one emotion, strongest (then most liked) first."""
    assert q.emotion in EMOTIONS  # validated by the schema; it is interpolated below
    rows = _dicts(con.execute(f"""
        SELECT {", ".join(f"r.{c}" for c in _REPLY_COLS)},
               {", ".join(f"e.{e}" for e in EMOTIONS)}, e.backend, e.model, e.analyzed_at
        FROM replies r JOIN reply_emotions e USING (comment_id)
        WHERE r.profile_username = ? AND e.{q.emotion} >= ?
        ORDER BY e.{q.emotion} DESC, r.like_count DESC, r.comment_id
        LIMIT ?
    """, [q.username, q.min_score, q.limit]))
    signals: dict[str, dict[str, float]] = {}
    if rows:
        for cid, qid, v in con.execute(
                "SELECT comment_id, question_id, value FROM reply_signals WHERE comment_id IN "
                f"({', '.join('?' * len(rows))})", [r["comment_id"] for r in rows]).fetchall():
            signals.setdefault(cid, {})[qid] = v
    out = []
    for row in rows:
        emotions = EmotionScores(**{e: row[e] for e in EMOTIONS})
        out.append(ReplyMood(
            reply=Reply(**{c: row[c] for c in _REPLY_COLS}),
            emotions=emotions, dominant_emotion=emotions.dominant(),
            signals=signals.get(row["comment_id"], {}),
            backend=row["backend"], model=row["model"], analyzed_at=row["analyzed_at"]))
    return out


def post_url(profile: str, post_id: str) -> str:
    return f"https://x.com/{profile}/status/{post_id}"


def posts(con: duckdb.DuckDBPyConnection, name: str | None = None) -> list[PostSummary]:
    """Posts with stored replies, most recently scraped first."""
    rows = _dicts(con.execute("""
        SELECT r.post_id, any_value(r.profile_username) AS profile_username,
               count(*) AS reply_total, count(e.comment_id) AS analyzed_total,
               max(r.scraped_at) AS last_scraped_at
        FROM replies r LEFT JOIN reply_emotions e USING (comment_id)
        WHERE ? IS NULL OR r.profile_username = ?
        GROUP BY r.post_id ORDER BY last_scraped_at DESC, r.post_id
    """, [name and username(name)] * 2))
    return [PostSummary(url=post_url(r["profile_username"], r["post_id"]), **r) for r in rows]


def post_dashboard(con: duckdb.DuckDBPyConnection, post_id: str) -> PostDashboard | None:
    totals = _dicts(con.execute("""
        SELECT any_value(r.profile_username) AS profile_username, count(*) AS reply_total,
               count(e.comment_id) AS analyzed_total,
               coalesce(sum(r.like_count), 0) AS like_total,
               coalesce(sum(r.view_count), 0) AS view_total, max(r.scraped_at) AS last_scraped_at
        FROM replies r LEFT JOIN reply_emotions e USING (comment_id)
        WHERE r.post_id = ?
    """, [post_id]))[0]
    if not totals["reply_total"]:
        return None

    rows = _dicts(con.execute(f"""
        SELECT r.comment_id, r.twitter_username, r.reply_content, r.like_count, r.view_count,
               r.created_at, {", ".join(f"e.{e}" for e in EMOTIONS)}
        FROM replies r JOIN reply_emotions e USING (comment_id)
        WHERE r.post_id = ?
        ORDER BY r.like_count DESC, r.view_count DESC, r.comment_id
    """, [post_id]))
    signals: dict[str, dict[str, float]] = {}
    for cid, qid, v in con.execute("""
            SELECT s.comment_id, s.question_id, s.value FROM reply_signals s
            JOIN replies r USING (comment_id) WHERE r.post_id = ?""", [post_id]).fetchall():
        signals.setdefault(cid, {})[qid] = v

    replies = []
    for row in rows:
        emotions = EmotionScores(**{e: row.pop(e) for e in EMOTIONS})
        sig = signals.get(row["comment_id"], {})
        crit = {"anger": emotions.anger, "disgust": emotions.disgust,
                "bug_report": sig.get("bug_report", 0.0)}
        reason = max(CRITICAL, key=crit.__getitem__)
        dominant = emotions.dominant()
        replies.append(DashboardReply(
            **row, emotions=emotions, signals=sig,
            dominant_emotion=dominant if getattr(emotions, dominant) >= YES else None,
            critical_score=crit[reason], critical_reason=reason))

    dominant_counts: dict[str, int] = {}
    for r in replies:
        key = r.dominant_emotion or "neutral"
        dominant_counts[key] = dominant_counts.get(key, 0) + 1
    signal_counts: dict[str, int] = {}
    for r in replies:
        for qid, v in r.signals.items():
            signal_counts[qid] = signal_counts.get(qid, 0) + (v >= YES)
    mean = None
    if replies:
        mean = EmotionScores(**{e: sum(getattr(r.emotions, e) for r in replies) / len(replies)
                                for e in EMOTIONS})

    positive = sorted((r for r in replies if r.emotions.joy >= YES),
                      key=lambda r: (-r.emotions.joy, -r.like_count))
    critical = sorted((r for r in replies if r.critical_score >= YES),
                      key=lambda r: (-r.critical_score, -r.like_count))
    profile = totals.pop("profile_username")
    return PostDashboard(
        post_id=post_id, profile_username=profile, url=post_url(profile, post_id), **totals,
        pending=totals["reply_total"] - totals["analyzed_total"], mean_emotions=mean,
        dominant_counts=dominant_counts, signal_counts=signal_counts,
        replies=replies[:MAX_DASHBOARD_REPLIES], top_positive=positive[:TOP_N],
        top_critical=critical[:TOP_N])
