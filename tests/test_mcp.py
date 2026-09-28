import json

import pytest
from mcp.client.client import Client

from boar_emotion_radar import mcp_server


@pytest.fixture
def calls(monkeypatch):
    calls = []

    async def fake_call(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True}

    monkeypatch.setattr(mcp_server, "_call", fake_call)
    return calls


async def test_tools_are_listed():
    async with Client(mcp_server.server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"get_profile_overview", "query_replies_by_emotion", "analyze_text_sentiment"}
    assert tools["query_replies_by_emotion"].input_schema["properties"]["emotion"]["enum"] == [
        "joy", "sadness", "anger", "fear", "surprise", "disgust", "bluff"]


async def test_tools_call_the_api(calls):
    async with Client(mcp_server.server) as client:
        await client.call_tool("get_profile_overview", {})
        await client.call_tool("query_replies_by_emotion", {"emotion": "anger", "min_score": 0.9})
        result = await client.call_tool("analyze_text_sentiment", {"text": "oi"})
    assert calls == [
        ("GET", "/api/profiles/boar_app/overview", {}),
        ("GET", "/api/profiles/boar_app/replies", {"params": {"emotion": "anger", "min_score": 0.9, "limit": 20}}),
        ("POST", "/api/analyze", {"json": {"text": "oi"}}),
    ]
    assert json.loads(result.content[0].text) == {"ok": True}


async def test_invalid_emotion_is_rejected(calls):
    async with Client(mcp_server.server) as client:
        result = await client.call_tool("query_replies_by_emotion", {"emotion": "sarcasm"})
    assert result.is_error and calls == []
