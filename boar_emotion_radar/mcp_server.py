"""MCP server (stdio) exposing the Boar-Emotion-Radar tools to LLM agents. It calls the
Boar-Emotion-Radar API (BOAR_EMOTION_RADAR_API_URL) instead of opening DuckDB, which that
process holds.

Run: uv run python -m boar_emotion_radar.mcp_server
MCP client config:
    {"command": "uv", "args": ["--directory", "<repo>", "run", "python", "-m", "boar_emotion_radar.mcp_server"]}
"""

import httpx
from mcp.server.mcpserver import MCPServer

from .config import Settings
from .schemas import Emotion

settings = Settings.from_env()
server = MCPServer("boar-emotion-radar")


async def _call(method: str, path: str, **kwargs) -> dict | list:
    async with httpx.AsyncClient(base_url=settings.api_url, timeout=120) as client:
        resp = await client.request(method, path, **kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"Boar-Emotion-Radar API {resp.status_code}: {resp.text[:300]}")
    return resp.json()


@server.tool()
async def get_profile_overview(username: str = settings.profile) -> dict:
    """Reach and mood of the replies to an X profile's posts: reply/like/view totals, average
    of the 7 emotions (joy, sadness, anger, fear, surprise, disgust, bluff; 0-1), how many
    replies each emotion dominates, and how many replies report a bug, praise offline mode or
    ask for iOS/new devices (signal_counts)."""
    return await _call("GET", f"/api/profiles/{username}/overview")


@server.tool()
async def query_replies_by_emotion(emotion: Emotion, username: str = settings.profile,
                                   min_score: float = 0.8, limit: int = 20) -> list:
    """Replies to a profile's posts whose `emotion` score (0-1) is at least `min_score`,
    strongest first, with engagement counts and BOAR signals. E.g. anger >= 0.8 for
    complaints, joy >= 0.8 for praise."""
    return await _call("GET", f"/api/profiles/{username}/replies",
                       params={"emotion": emotion, "min_score": min_score, "limit": limit})


@server.tool()
async def analyze_text_sentiment(text: str) -> dict:
    """Score one text (English or Portuguese) for the 7 emotions and the BOAR signals
    (bug_report, offline_praise, platform_request), each 0-1. Nothing is stored."""
    return await _call("POST", "/api/analyze", json={"text": text})


if __name__ == "__main__":
    server.run("stdio")
