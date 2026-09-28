"""Boar-Emotion-Radar REST API: the tools LLM agents use (also exposed over MCP by
boar_emotion_radar/mcp_server.py), plus ingestion. It owns the DuckDB file and runs the
scoring worker in-process, since DuckDB allows one writing process per file.

The Mood Lab server mounts it at /radar (server/app.py), which is the normal way to run it.
Standalone, without the Playground (Mood Lab must be up at MOODLAB_URL):
    uv run uvicorn boar_emotion_radar.api:app --port 8001
"""

import asyncio
import contextlib
import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Query, Request

from . import scraper, store
from .config import Settings
from .db import connect
from .moodlab import MoodLab, MoodLabError
from .questions import BOAR_QUESTIONS
from .schemas import (AnalyzeTextRequest, Emotion, EmotionQuery, IngestRequest, IngestResult,
                      PostDashboard, PostSummary, ProfileOverview, ReplyMood, TextSentiment)
from .worker import run_forever

logging.basicConfig(level=logging.INFO)


def create_app(settings: Settings | None = None, moodlab: MoodLab | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.con = connect(settings.db_path)
        # A client passed in belongs to the caller (server/app.py reuses it across restarts).
        app.state.moodlab = moodlab or MoodLab(settings)
        app.state.wake = asyncio.Event()
        worker = None
        if settings.worker:
            worker = asyncio.create_task(run_forever(
                app.state.con, app.state.moodlab, settings.batch_size, app.state.wake))
        yield
        if worker:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        if moodlab is None:
            await app.state.moodlab.aclose()
        app.state.con.close()

    app = FastAPI(title="Boar-Emotion-Radar",
                  summary="Mood of the replies to X posts, for agents and the team",
                  lifespan=lifespan)

    def cursor(request: Request) -> Iterator[duckdb.DuckDBPyConnection]:
        cur = request.app.state.con.cursor()
        try:
            yield cur
        finally:
            cur.close()

    Cursor = Annotated[duckdb.DuckDBPyConnection, Depends(cursor)]

    @app.get("/api/profiles/{username}/overview")
    def get_profile_overview(username: str, cur: Cursor) -> ProfileOverview:
        """Reach (likes, views), average emotions and BOAR signal counts over a profile's replies."""
        return store.profile_overview(cur, username)

    @app.get("/api/profiles/{username}/replies")
    def query_replies_by_emotion(
        username: str, emotion: Emotion, cur: Cursor,
        min_score: Annotated[float, Query(ge=0.0, le=1.0)] = 0.8,
        limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    ) -> list[ReplyMood]:
        """Replies whose `emotion` is at least `min_score`, strongest first."""
        q = EmotionQuery(username=username, emotion=emotion, min_score=min_score, limit=limit)
        return store.replies_by_emotion(cur, q)

    @app.post("/api/analyze")
    async def analyze_text_sentiment(req: AnalyzeTextRequest, request: Request) -> TextSentiment:
        """Emotions and BOAR signals for one text; nothing is stored."""
        try:
            return await request.app.state.moodlab.analyze(req.text)
        except MoodLabError as e:
            raise HTTPException(502, str(e)) from e

    @app.post("/api/ingest")
    async def ingest(req: IngestRequest, request: Request) -> IngestResult:
        """Store a post's replies (scraped, or `items` from an actor export) and queue them."""
        try:
            profile, post_id = scraper.parse_post_url(req.post_url, settings.profile)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        items = req.items
        if items is None:
            if not settings.apify_token:
                raise HTTPException(400, "scraping needs APIFY_TOKEN; or send the replies as `items`")
            try:
                items = await scraper.fetch_items(store.post_url(profile, post_id),
                                                  settings.apify_token, req.max_items)
            except scraper.ScraperError as e:
                raise HTTPException(502, str(e)) from e
        replies, skipped = scraper.to_replies(items, profile, post_id)

        def write() -> int:
            with contextlib.closing(request.app.state.con.cursor()) as cur:
                return store.upsert_replies(cur, replies)

        stored = await asyncio.to_thread(write)
        request.app.state.wake.set()
        return IngestResult(post_id=post_id, profile_username=profile, stored=stored,
                            skipped=skipped)

    @app.get("/api/config")
    def config() -> dict:
        """What the Playground's Boar X-Radar tab needs to render."""
        return {"profile": settings.profile, "scraping": bool(settings.apify_token),
                "signals": {qid: label for qid, (label, _) in BOAR_QUESTIONS.items()},
                "threshold": store.YES}

    @app.get("/api/posts")
    def list_posts(cur: Cursor, username: str | None = None) -> list[PostSummary]:
        """Posts with stored replies, most recently scraped first."""
        return store.posts(cur, username)

    @app.get("/api/posts/{post_id}")
    def post_dashboard(post_id: str, cur: Cursor) -> PostDashboard:
        """KPIs, emotion mix, BOAR signals and per-reply scores for one post."""
        dashboard = store.post_dashboard(cur, post_id)
        if dashboard is None:
            raise HTTPException(404, f"no replies stored for post {post_id}")
        return dashboard

    @app.get("/api/status")
    def status(cur: Cursor) -> dict:
        return {"pending": store.pending_count(cur), "worker": settings.worker,
                "backend": settings.moodlab_backend, "batch_size": settings.batch_size}

    return app


app = create_app()
