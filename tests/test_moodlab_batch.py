"""POST /api/analyze_batch on the Mood Lab server, with a stand-in backend."""

import pytest
from fastapi.testclient import TestClient

from server import app as moodlab
from server.presets import emotion_questions


class EchoBackend:
    def __init__(self):
        self.calls = []

    def predict_batch(self, texts, questions, model, batch_size):
        self.calls.append((texts, questions, model, batch_size))
        return [{"answers": {q: {"type": "noul", "value": i / 10} for q in questions}, "model": "echo"}
                for i, _ in enumerate(texts)]


@pytest.fixture
def backend(monkeypatch):
    backend = EchoBackend()
    monkeypatch.setattr(moodlab, "laya", backend)
    return backend


@pytest.fixture
def client():
    return TestClient(moodlab.app)  # no `with`: skips the lifespan's checkpoint preload


def test_batch_keeps_order_and_defaults_to_emotions(client, backend):
    r = client.post("/api/analyze_batch", json={"texts": ["a", "b", "c"], "model": "english",
                                                "batch_size": 16})
    assert r.status_code == 200
    assert [res["answers"]["joy"]["value"] for res in r.json()["results"]] == [0.0, 0.1, 0.2]
    ((texts, questions, model, batch_size),) = backend.calls
    assert (texts, questions, model, batch_size) == (["a", "b", "c"], emotion_questions(), "english", 16)


@pytest.mark.parametrize("body", [
    {"texts": []},
    {"texts": ["a"] * 65},
    {"texts": ["a" * 2001]},
    {"texts": [""]},
    {"texts": ["a"], "batch_size": 0},
])
def test_batch_validation(client, backend, body):
    assert client.post("/api/analyze_batch", json=body).status_code == 422
    assert backend.calls == []


def test_batch_rejects_bad_questions_and_backends(client, backend):
    assert client.post("/api/analyze_batch", json={
        "texts": ["a"], "questions": {"x": {"type": "score"}}}).status_code == 400
    assert client.post("/api/analyze_batch", json={"texts": ["a"], "backend": "gpt"}).status_code == 400
    assert client.post("/api/analyze_batch", json={"texts": ["a"], "model": "klingon"}).status_code == 400
