import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from boar_emotion_radar.api import create_app

POST = "https://x.com/BOAR_app/status/1910363426972635455"
ITEMS = [
    {"commentId": "1", "twitterUsername": "a", "replyContent": "So angry, the app crashed",
     "likeCount": 4, "viewCount": "1.5K", "createdAt": "Sun Sep 27 18:04:11 +0000 2026"},
    {"commentId": "2", "twitterUsername": "b", "replyContent": "happy with the offline mode",
     "likeCount": 9, "viewCount": "300", "createdAt": "Sun Sep 27 18:05:00 +0000 2026"},
    {"commentId": "3", "twitterUsername": "c", "replyContent": "",
     "createdAt": "Sun Sep 27 18:06:00 +0000 2026"},
]


@pytest.fixture
def client(settings, moodlab):
    with TestClient(create_app(replace(settings, worker=True), moodlab)) as client:
        yield client


def wait_scored(client) -> None:
    deadline = time.monotonic() + 5
    while client.get("/api/status").json()["pending"]:
        assert time.monotonic() < deadline, "worker did not score the replies"
        time.sleep(0.02)


def test_ingest_items_then_query(client):
    r = client.post("/api/ingest", json={"post_url": POST, "items": ITEMS})
    assert r.status_code == 200
    assert r.json() == {"post_id": "1910363426972635455", "profile_username": "boar_app",
                        "stored": 2, "skipped": 1}
    wait_scored(client)

    o = client.get("/api/profiles/boar_app/overview").json()
    assert (o["reply_total"], o["analyzed_total"], o["like_total"], o["view_total"]) == (2, 2, 13, 1800)
    assert o["signal_counts"]["bug_report"] == 1

    angry = client.get("/api/profiles/@Boar_App/replies", params={"emotion": "anger"}).json()
    assert [m["reply"]["comment_id"] for m in angry] == ["1"]
    assert angry[0]["signals"]["bug_report"] == 0.9
    assert client.get("/api/profiles/boar_app/replies",
                      params={"emotion": "anger", "min_score": 0.95}).json() == []


def test_query_validation(client):
    assert client.get("/api/profiles/boar_app/replies", params={"emotion": "sarcasm"}).status_code == 422
    assert client.get("/api/profiles/boar_app/replies",
                      params={"emotion": "joy", "min_score": 2}).status_code == 422


def test_analyze_text(client, fake):
    r = client.post("/api/analyze", json={"text": "When is the iPhone version coming?"})
    assert r.status_code == 200
    body = r.json()
    assert body["signals"]["platform_request"] == 0.9
    assert body["dominant_emotion"] in body["emotions"]
    assert fake.bodies[-1]["text"] == "When is the iPhone version coming?"


def test_analyze_reports_mood_lab_errors(client, fake):
    fake.fail = 1
    assert client.post("/api/analyze", json={"text": "hi"}).status_code == 502


def test_ingest_needs_token_or_items(client):
    r = client.post("/api/ingest", json={"post_url": POST})
    assert r.status_code == 400 and "APIFY_TOKEN" in r.text
    assert client.post("/api/ingest", json={"post_url": "https://x.com/boar_app", "items": []}).status_code == 400
