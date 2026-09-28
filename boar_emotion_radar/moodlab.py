"""Async client for the Mood Lab server (server/app.py)."""

import httpx

from .config import Settings
from .questions import BOAR_QUESTIONS, all_questions
from .schemas import MAX_TEXT_CHARS, EmotionScores, TextSentiment

# A 32-reply batch takes ~1.5 s on the GPU but can take ~40 s on the CPU.
TIMEOUT = httpx.Timeout(300, connect=5)


class MoodLabError(RuntimeError):
    pass


def _parse(answers: dict) -> tuple[EmotionScores, dict[str, float]]:
    signals = {qid: answers[qid]["value"] for qid in BOAR_QUESTIONS if qid in answers}
    return EmotionScores.from_answers(answers), signals


class MoodLab:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.backend = settings.moodlab_backend
        self._model = settings.moodlab_model
        self._client = client or httpx.AsyncClient(timeout=TIMEOUT)
        self._url = settings.moodlab_url
        self._questions = all_questions()

    async def _post(self, path: str, body: dict) -> dict:
        body = {**body, "questions": self._questions, "backend": self.backend, "model": self._model}
        try:
            resp = await self._client.post(self._url + path, json=body)
        except httpx.HTTPError as e:
            raise MoodLabError(f"Mood Lab unreachable at {self._url}: {e!r}") from e
        if resp.status_code >= 400:
            raise MoodLabError(f"Mood Lab {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def analyze_batch(self, texts: list[str], batch_size: int = 32
                            ) -> list[tuple[EmotionScores, dict[str, float], str]]:
        """(emotions, BOAR signals, model) per text, in order."""
        data = await self._post("/api/analyze_batch", {
            "texts": [t[:MAX_TEXT_CHARS] for t in texts], "batch_size": batch_size})
        results = data["results"]
        if len(results) != len(texts):
            raise MoodLabError(f"sent {len(texts)} texts, got {len(results)} results")
        return [(*_parse(r["answers"]), r["model"]) for r in results]

    async def analyze(self, text: str) -> TextSentiment:
        data = await self._post("/api/analyze", {"text": text[:MAX_TEXT_CHARS]})
        emotions, signals = _parse(data["answers"])
        return TextSentiment(emotions=emotions, dominant_emotion=emotions.dominant(),
                             signals=signals, backend=self.backend, model=data["model"],
                             latency_ms=data["latency_ms"])

    async def aclose(self) -> None:
        await self._client.aclose()
