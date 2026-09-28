import json
import os
from dataclasses import replace

# server.app mounts the radar at import time with settings from the environment: keep tests off
# the real database and don't load Laya checkpoints in the lifespan.
os.environ["BOAR_EMOTION_RADAR_DB"] = ":memory:"
os.environ["LAYA_PRELOAD"] = "0"

import httpx
import pytest

from boar_emotion_radar.config import Settings
from boar_emotion_radar.moodlab import MoodLab

# Fake Mood Lab: a word in the text sets that emotion or signal to 0.9, everything else 0.05.
KEYWORDS = {"angry": "anger", "happy": "joy", "crash": "bug_report", "iphone": "platform_request"}


def answers(text: str, questions: dict) -> dict:
    hits = {qid for word, qid in KEYWORDS.items() if word in text.lower()}
    return {qid: {"type": "noul", "value": 0.9 if qid in hits else 0.05} for qid in questions}


class FakeMoodLab:
    """httpx transport standing in for server/app.py; records every request body."""

    def __init__(self, fail: int = 0):
        self.bodies: list[dict] = []
        self.fail = fail  # answer this many requests with a 502 first

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        if self.fail:
            self.fail -= 1
            return httpx.Response(502, text="CUDA out of memory")
        model = "laya/english on cuda"
        if request.url.path == "/api/analyze_batch":
            return httpx.Response(200, json={"backend": "laya", "latency_ms": 10, "results": [
                {"answers": answers(t, body["questions"]), "model": model} for t in body["texts"]]})
        return httpx.Response(200, json={"backend": "laya", "model": model, "latency_ms": 5,
                                          "answers": answers(body["text"], body["questions"])})


@pytest.fixture
def settings() -> Settings:
    return replace(Settings.from_env(), db_path=":memory:", batch_size=4, worker=False,
                   moodlab_url="http://moodlab.test", apify_token=None)


@pytest.fixture
def fake() -> FakeMoodLab:
    return FakeMoodLab()


@pytest.fixture
def moodlab(settings, fake) -> MoodLab:
    return MoodLab(settings, httpx.AsyncClient(transport=httpx.MockTransport(fake)))

