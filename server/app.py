"""Sentiment playground: FastAPI server + static frontend.

Run:  uv run uvicorn server.app:app --reload --port 8000
"""

import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .backends import JevBackend, LayaBackend
from .presets import emotion_questions, public_presets

WEB = Path(__file__).resolve().parent.parent / "web"
MAX_CHARS = 2000
LAYA_MODELS = {"auto": None, "english": "english", "multilingual": "multilingual"}

laya = LayaBackend(device=os.environ.get("LAYA_DEVICE") or None)
jev = JevBackend(key) if (key := os.environ.get("TYPESAFE_API_KEY")) else None

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load the checkpoint in the background so the first request doesn't wait ~10 s.
    if os.environ.get("LAYA_PRELOAD", "1") != "0":
        threading.Thread(target=laya.warm_up, daemon=True).start()
    yield


app = FastAPI(title="Sentiment playground", lifespan=lifespan)


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CHARS)
    questions: dict | None = None  # defaults to the emotion preset
    backend: str = "laya"
    model: str = "auto"


@app.get("/api/config")
def config() -> dict:
    return {
        "backends": ["laya"] + (["jev"] if jev else []),
        "laya_models": list(LAYA_MODELS),
        "presets": public_presets(),
    }


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest) -> dict:
    questions = req.questions or emotion_questions()
    for qid, q in questions.items():
        if not isinstance(q, dict) or q.get("type") not in ("score", "noul", "choice"):
            raise HTTPException(400, f"question {qid!r} needs type score, noul or choice")
        if q["type"] != "noul" and not q.get("criteria"):
            raise HTTPException(400, f"question {qid!r} needs criteria")

    if req.backend == "jev":
        if not jev:
            raise HTTPException(400, "Jev is not configured (set TYPESAFE_API_KEY)")
        backend, model = jev, None
    elif req.backend == "laya":
        if req.model not in LAYA_MODELS:
            raise HTTPException(400, f"unknown Laya model {req.model!r}")
        backend, model = laya, LAYA_MODELS[req.model]
    else:
        raise HTTPException(400, f"unknown backend {req.backend!r}")

    try:
        result = await run_in_threadpool(backend.predict, req.text, questions, model)
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e
    return {"backend": req.backend, **result}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
