import pytest

from xmood.db import connect, migrate


@pytest.fixture
def con():
    con = connect(":memory:")
    yield con
    con.close()


def tables(con):
    return {t for (t,) in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}


def test_migrations_create_tables(con):
    assert {"replies", "reply_emotions", "schema_migrations"} <= tables(con)
    assert con.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]


def test_migrate_is_idempotent(con):
    assert migrate(con) == []


def test_reply_upsert_and_emotion_join(con):
    con.execute("""INSERT INTO replies (comment_id, post_id, profile_username, twitter_username,
                                        reply_content, like_count, created_at)
                   VALUES ('c1', 'p1', 'prof', 'u1', 'hi', 1, '2026-09-28 12:00:00+00')""")
    con.execute("""INSERT INTO reply_emotions VALUES
                   ('c1', 0.9, 0, 0.85, 0, 0, 0, 0, 'laya', 'laya/english on cpu', DEFAULT)""")
    # Re-scraping refreshes engagement counts in place.
    con.execute("""INSERT INTO replies (comment_id, post_id, profile_username, twitter_username,
                                        reply_content, like_count, created_at)
                   VALUES ('c1', 'p1', 'prof', 'u1', 'hi', 7, '2026-09-28 12:00:00+00')
                   ON CONFLICT (comment_id) DO UPDATE SET like_count = excluded.like_count""")
    rows = con.execute("""SELECT r.like_count, e.anger FROM replies r
                          JOIN reply_emotions e USING (comment_id)
                          WHERE r.profile_username = 'prof' AND e.anger > 0.8""").fetchall()
    assert rows == [(7, 0.85)]


def test_connect_creates_parent_dir(tmp_path):
    path = tmp_path / "sub" / "x.duckdb"
    connect(str(path)).close()
    assert path.exists()
