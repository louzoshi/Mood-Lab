# Mood Lab

A playground for zero-shot sentiment analysis with [Laya](https://github.com/NandhaKishorM/laya)
(local) or Jev (TypeSafe cloud), plus a pass-the-phone party game built on top of it.

## Run

```bash
uv sync
uv run uvicorn server.app:app --port 8000      # http://localhost:8000
```

The first start downloads the Laya checkpoints from Hugging Face and imports torch/transformers, which
is slow on a spinning disk. Later starts are much faster.

| env | default | |
|---|---|---|
| `TYPESAFE_API_KEY` | unset | enables the Jev backend in the dropdown |
| `JEV_MODEL` | `jev-1.13.0` | |
| `LAYA_DEVICE` | auto | `cuda` (NVIDIA) if available, else `cpu` |
| `LAYA_FP32` | auto | `1`/`0` forces full precision on/off; auto turns it on for GTX cards |
| `LAYA_PRELOAD` | `1` | `0` loads the checkpoint on the first request instead of at startup |

To reach it from a phone on the same Wi-Fi, add `--host 0.0.0.0` and open `http://<laptop-ip>:8000`.

## What's in it

- **Playground:** type text and see 7 emotion bars (joy, sadness, anger, fear, surprise,
  disgust, bluff) update live, plus any yes/no, score or choice questions you add yourself.
- **Game: Hit the Mood:** each round shows a target such as *Fear HIGH + Bluff MEDIUM*. Every
  player writes one line, scores 0–100 by how close the model's reading lands, and the round
  ends with a leaderboard of everyone's lines.
- **API:** `POST /api/analyze {"text", "questions"?, "backend": "laya"|"jev", "model": "auto"|"english"|"multilingual"}`.
  `GET /api/config` returns the presets.

## Findings (Laya 0.3.20, zero-shot)

- **Ask yes/no questions, not 4-level scores.** Score rubrics drift toward the middle: "The
  meeting is at 3pm" read as ~55% of every emotion. Yes/no (`noul`) questions put neutral text
  at ~0% and clear emotions at 80–95%.
- **English works well.** Anger, joy, sadness, surprise, disgust and protesting too much
  ("I swear on my life I've never been late") all register.
- **Portuguese only picks up explicit emotions.** "Seu idiota…" gets anger 0.96, but implied
  emotions ("Tem uma barata no meu café", "Eu juro que não fui eu…") read as flat. Forcing the
  English checkpoint on Portuguese is worse, so leave routing on `auto`.
- **Sarcasm doesn't work.** Every phrasing either missed it or also fired on sincere text
  ("my dog died" came out 85% sarcastic), so it was dropped. A "what is the overall tone?"
  choice question also mislabelled obvious joy, so the overall vibe is computed from the
  emotion bars instead.
- **Latency on a GTX 1650 (7 questions):** ~80 ms Portuguese, ~180 ms English. On CPU it
  was ~350 ms and ~1.3 s.
- **GTX cards need fp32.** Laya autocasts to fp16 on any GPU older than Ampere, but GTX cards
  have no tensor cores: fp16 ran at 0.4 TFLOPS vs 1.8 for fp32 on the 1650, and the extra fp16
  weight copies pushed both checkpoints past 4 GB. The server switches to fp32 on GTX cards
  (`server/backends.py`), which fits both checkpoints in ~3 GB.
- **torch comes from PyTorch's CUDA 12.6 index** (`pyproject.toml`). The default PyPI build
  pulls CUDA 13 wheels whose `nvidia-nvjitlink` failed its hash check here.

Fine-tuning on the free Kaggle notebook linked from the Laya README is the way to make
sarcasm and Portuguese work.
