"""Laya (local) and Jev (TypeSafe cloud) behind one normalized answer shape.

Normalized answer:
    {"type": "score"|"noul"|"choice", "value": 0..1, "choice": str|None,
     "probabilities": {label: p}, "confidence": 0..1}

`value` is the expected score scaled to 0..1 for score questions, P(yes) for noul, and the
top option's probability for choice.
"""

import os
import threading
import time

import httpx

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = os.environ.get("JEV_MODEL", "jev-1.13.0")


def normalize(question: dict, answer: dict) -> dict:
    qtype = question["type"]
    probs = {str(k): float(v) for k, v in (answer.get("probabilities") or {}).items()}
    out = {"type": qtype, "choice": None, "probabilities": probs,
           "confidence": answer.get("answer_confidence", answer.get("confidence"))}
    if qtype == "score":
        top = max(len(question["criteria"]) - 1, 1)
        out["value"] = float(answer["score"]) / top
    elif qtype == "noul":
        p = float(answer["noul"] if "noul" in answer else answer.get("probability", 0.0))
        out["value"] = p
        out["probabilities"] = {"no": 1 - p, "yes": p}
    else:
        out["choice"] = answer["choice"]
        out["value"] = probs.get(answer["choice"], 0.0)
    return out


def _use_fp32(torch) -> bool:
    """LAYA_FP32=1/0 forces it; otherwise fp32 on GTX cards (no tensor cores)."""
    forced = os.environ.get("LAYA_FP32")
    if forced is not None:
        return forced == "1"
    return "GTX" in torch.cuda.get_device_name()


class LayaBackend:
    """Loads checkpoints lazily; one forward pass at a time (single small GPU)."""

    def __init__(self, device: str | None = None):
        self._device = device
        self._router = None
        self._lock = threading.Lock()

    def _get_router(self):
        if self._router is None:
            import torch  # heavy import, keep it off the startup path
            from laya import Router

            # Resolve it here rather than letting Laya pick, so responses can report it.
            # The Intel iGPU is not a CUDA device, so "cuda" is always the NVIDIA card.
            if self._device is None:
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            # Short Portuguese text has no reliable language signal; default it to the
            # multilingual checkpoint instead of English.
            self._router = Router(device=self._device, default="multilingual")
            if self._device == "cuda" and _use_fp32(torch):
                # Laya autocasts to fp16 on every GPU older than Ampere. GTX cards have no
                # tensor cores, so fp16 runs ~4x slower than fp32 there (0.4 vs 1.8 TFLOPS on
                # a GTX 1650), and the fp16 weight copies push both checkpoints past 4 GB.
                # This must happen before the first forward pass, while no fp16 buffers exist.
                # `amp_enabled`/`dtype` are Laya internals (agent.py), checked on 0.3.20.
                self._router.preload(["english", "multilingual"])
                for agent in self._router._agents.values():
                    agent.amp_enabled = False
                    agent.dtype = torch.float32
        return self._router

    def warm_up(self) -> None:
        # One call per checkpoint pays the model load and CUDA/cuBLAS init up front.
        with self._lock:
            router = self._get_router()
            for model in ("english", "multilingual"):
                router.predict("warm up", {"x": {"type": "noul", "instructions": "Is this a test?"}}, model=model)

    def predict(self, text: str, questions: dict, model: str | None) -> dict:
        with self._lock:
            router = self._get_router()
            start = time.perf_counter()
            result = router.predict(text, questions, model=model)
            latency = (time.perf_counter() - start) * 1000
        routing = result.get("routing") or {}
        return {
            "answers": {qid: normalize(questions[qid], a) for qid, a in result["answers"].items()},
            "model": f"laya/{routing.get('model', model or 'auto')} on {self._device}",
            "reason": routing.get("reason"),
            "latency_ms": round(latency),
        }


class JevBackend:
    def __init__(self, api_key: str):
        self._client = httpx.Client(timeout=10, headers={"Authorization": f"Bearer {api_key}"})

    def predict(self, text: str, questions: dict, model: str | None) -> dict:
        start = time.perf_counter()
        resp = self._client.post(JEV_URL, json={
            "model": model or JEV_MODEL,
            "state": {"text": text},
            "questions": questions,
        })
        latency = (time.perf_counter() - start) * 1000
        if resp.status_code >= 400:
            raise RuntimeError(f"Jev {resp.status_code}: {resp.text[:300]}")
        result = resp.json()
        return {
            "answers": {qid: normalize(questions[qid], a) for qid, a in result["answers"].items()},
            "model": result.get("model", model or JEV_MODEL),
            "reason": None,
            "latency_ms": round(latency),
        }
