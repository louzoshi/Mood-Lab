"""Reads and writes on the DuckDB tables (boar_emotion_radar/migrations).

`replies` doubles as the work queue: a reply without a `reply_emotions` row is pending.
Functions take a connection; callers on other threads pass `con.cursor()`.
"""

from dataclasses import dataclass

import duckdb

from .schemas import EmotionQuery, EmotionScores, ProfileOverview, Reply, ReplyMood, username

EMOTIONS = list(EmotionScores.model_fields)
YES = 0.5  # P(yes) at which a signal counts as answered yes

_REPLY_COLS = list(Reply.model_fields)
_DOMINANT = "CASE greatest({}) {} END".format(
    ", ".join(f"e.{e}" for e in EMOTIONS), " ".join(f"WHEN e.{e} THEN '{e}'" for e in EMOTIONS))


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
