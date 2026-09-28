"""Settings read from the environment.

| env | default | |
|---|---|---|
| `BOAR_EMOTION_RADAR_DB` | `data/boar_emotion_radar.duckdb` | DuckDB file; `:memory:` for tests |
| `BOAR_EMOTION_RADAR_PROFILE` | `boar_app` | profile the dashboard and MCP tools default to |
| `BOAR_EMOTION_RADAR_BATCH_SIZE` | `32` | replies per Mood Lab batch (at most 64) |
| `BOAR_EMOTION_RADAR_WORKER` | `1` | `0` serves the API without scoring pending replies |
| `MOODLAB_URL` | `http://localhost:8000` | Mood Lab server that serves `/api/analyze[_batch]` |
| `MOODLAB_BACKEND` | `laya` | `laya` (local) or `jev` (needs `TYPESAFE_API_KEY` on the Mood Lab server) |
| `MOODLAB_MODEL` | `auto` | Laya checkpoint: `auto`, `english` or `multilingual` |
| `APIFY_TOKEN` | unset | enables scraping through the Apify actor (`boar_emotion_radar/scraper.py`) |
| `BOAR_EMOTION_RADAR_API_URL` | `http://localhost:8001` | where the MCP server reaches the API |
"""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    db_path: str
    profile: str
    batch_size: int
    worker: bool
    moodlab_url: str
    moodlab_backend: str
    moodlab_model: str
    apify_token: str | None
    api_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=os.environ.get("BOAR_EMOTION_RADAR_DB", str(ROOT / "data" / "boar_emotion_radar.duckdb")),
            profile=os.environ.get("BOAR_EMOTION_RADAR_PROFILE", "boar_app"),
            batch_size=min(int(os.environ.get("BOAR_EMOTION_RADAR_BATCH_SIZE", "32")), 64),
            worker=os.environ.get("BOAR_EMOTION_RADAR_WORKER", "1") != "0",
            moodlab_url=os.environ.get("MOODLAB_URL", "http://localhost:8000").rstrip("/"),
            moodlab_backend=os.environ.get("MOODLAB_BACKEND", "laya"),
            moodlab_model=os.environ.get("MOODLAB_MODEL", "auto"),
            apify_token=os.environ.get("APIFY_TOKEN") or None,
            api_url=os.environ.get("BOAR_EMOTION_RADAR_API_URL", "http://localhost:8001").rstrip("/"),
        )
