"""The radar mounted in the Mood Lab server: the Playground tab's whole round trip, scored
in-process through /api/analyze_batch (with a stand-in Laya backend)."""

import time

import pytest
from fastapi.testclient import TestClient

from server import app as moodlab
from tests.conftest import answers
from tests.test_api import ITEMS


class KeywordBackend:
    def predict_batch(self, texts, questions, model, batch_size):
        return [{"answers": answers(t, questions), "model": "fake on cuda"} for t in texts]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(moodlab, "laya", KeywordBackend())
    with TestClient(moodlab.app) as client:
        yield client


def test_playground_serves_the_radar_tab(client):
    page = client.get("/").text
    assert 'data-tab="radar"' in page and "/radar.js" in page
    assert client.get("/radar.js").status_code == 200


def test_ingest_scores_in_process_and_dashboard_loads(client):
    r = client.post("/radar/api/ingest", json={"post_url": "https://x.com/boar_app/status/42", "items": ITEMS})
    assert r.json()["stored"] == 2
    deadline = time.monotonic() + 5
    while (d := client.get("/radar/api/posts/42").json())["pending"]:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert d["analyzed_total"] == 2
    assert d["replies"][0]["emotions"]["joy"] == 0.9  # "happy with the offline mode", 9 likes
    assert d["signal_counts"]["bug_report"] == 1
    assert [p["post_id"] for p in client.get("/radar/api/posts").json()] == ["42"]
