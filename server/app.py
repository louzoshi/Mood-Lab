"""Sentiment playground: FastAPI server + static frontend, with Boar-Emotion-Radar mounted at
/radar (its API, scoring worker and DuckDB file run in this process).

Run:  uv run uvicorn server.app:app --reload --port 8000
"""

import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from boar_emotion_radar.api import create_app as create_radar
from boar_emotion_radar.config import Settings as RadarSettings
from boar_emotion_radar.moodlab import TIMEOUT, MoodLab

from .backends import JevBackend, LayaBackend
from .presets import emotion_questions, public_presets

WEB = Path(__file__).resolve().parent.parent / "web"
MAX_CHARS = 2000
MAX_BATCH = 64
LAYA_MODELS = {"auto": None, "english": "english", "multilingual": "multilingual"}

laya = LayaBackend(device=os.environ.get("LAYA_DEVICE") or None)
jev = JevBackend(key) if (key := os.environ.get("TYPESAFE_API_KEY")) else None

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load the checkpoint in the background so the first request doesn't wait ~10 s.
    if os.environ.get("LAYA_PRELOAD", "1") != "0":
        threading.Thread(target=laya.warm_up, daemon=True).start()
    # Mounted apps don't get lifespan events, so run the radar's (DB + worker) from here.
    async with radar.router.lifespan_context(radar):
        yield


app = FastAPI(title="Sentiment playground", lifespan=lifespan)

# The radar scores replies through this app's /api/analyze_batch, called in-process.
_radar_settings = replace(RadarSettings.from_env(), moodlab_url="http://moodlab")
radar = create_radar(_radar_settings, MoodLab(_radar_settings, httpx.AsyncClient(
    transport=httpx.ASGITransport(app=app), timeout=TIMEOUT)))


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CHARS)
    questions: dict | None = None  # defaults to the emotion preset
    backend: str = "laya"
    model: str = "auto"


class AnalyzeBatchRequest(BaseModel):
    texts: list[Annotated[str, Field(min_length=1, max_length=MAX_CHARS)]] = Field(
        min_length=1, max_length=MAX_BATCH)
    questions: dict | None = None  # one question set for every text
    backend: str = "laya"
    model: str = "auto"
    batch_size: int = Field(default=32, ge=1, le=MAX_BATCH)


@app.get("/api/config")
def config() -> dict:
    return {
        "backends": ["laya"] + (["jev"] if jev else []),
        "laya_models": list(LAYA_MODELS),
        "presets": public_presets(),
    }


def _resolve(req: AnalyzeRequest | AnalyzeBatchRequest) -> tuple[dict, object, str | None]:
    """Validated (questions, backend, model) for a request."""
    questions = req.questions or emotion_questions()
    for qid, q in questions.items():
        if not isinstance(q, dict) or q.get("type") not in ("score", "noul", "choice"):
            raise HTTPException(400, f"question {qid!r} needs type score, noul or choice")
        if q["type"] != "noul" and not q.get("criteria"):
            raise HTTPException(400, f"question {qid!r} needs criteria")

    if req.backend == "jev":
        if not jev:
            raise HTTPException(400, "Jev is not configured (set TYPESAFE_API_KEY)")
        return questions, jev, None
    if req.backend == "laya":
        if req.model not in LAYA_MODELS:
            raise HTTPException(400, f"unknown Laya model {req.model!r}")
        return questions, laya, LAYA_MODELS[req.model]
    raise HTTPException(400, f"unknown backend {req.backend!r}")


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest) -> dict:
    questions, backend, model = _resolve(req)
    try:
        result = await run_in_threadpool(backend.predict, req.text, questions, model)
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e
    return {"backend": req.backend, **result}


@app.post("/api/analyze_batch")
async def analyze_batch(req: AnalyzeBatchRequest) -> dict:
    """Same as /api/analyze for many texts; `results` is in `texts` order."""
    questions, backend, model = _resolve(req)
    start = time.perf_counter()
    try:
        results = await run_in_threadpool(backend.predict_batch, req.texts, questions, model,
                                          req.batch_size)
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e
    latency = (time.perf_counter() - start) * 1000
    return {"backend": req.backend, "latency_ms": round(latency), "results": results}


app.mount("/radar", radar)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
