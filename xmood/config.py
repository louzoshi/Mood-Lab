"""Settings read from the environment.

| env | default | |
|---|---|---|
| `XMOOD_DB` | `data/xmood.duckdb` | DuckDB file; `:memory:` for tests |
| `MOODLAB_URL` | `http://localhost:8000` | Mood Lab server that serves `POST /api/analyze` |
| `MOODLAB_BACKEND` | `laya` | `laya` (local) or `jev` (needs `TYPESAFE_API_KEY` on the Mood Lab server) |
| `MOODLAB_MODEL` | `auto` | Laya checkpoint: `auto`, `english` or `multilingual` |
"""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    db_path: str
    moodlab_url: str
    moodlab_backend: str
    moodlab_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=os.environ.get("XMOOD_DB", str(ROOT / "data" / "xmood.duckdb")),
            moodlab_url=os.environ.get("MOODLAB_URL", "http://localhost:8000").rstrip("/"),
            moodlab_backend=os.environ.get("MOODLAB_BACKEND", "laya"),
            moodlab_model=os.environ.get("MOODLAB_MODEL", "auto"),
        )
