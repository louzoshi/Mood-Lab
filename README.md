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

Fine-tuning on the free Kaggle notebook linked from the Laya README is the way to make
sarcasm and Portuguese work.

## Performance: CPU vs GPU

Time for one analysis (7 emotion questions, one short sentence), warm, measured on an Acer
Nitro 5: i7-9750H, GTX 1650 Mobile 4 GB, 16 GB RAM.

| | CPU | GTX 1650, fp16 (Laya's default) | GTX 1650, fp32 (this server) |
|---|---|---|---|
| Portuguese (`laya-multilingual`, 322M) | ~350 ms | ~280 ms | **~80 ms** |
| English (`laya`, 421M) | ~1.3 s | ~1.1–1.8 s | **~180 ms** |
| VRAM, both checkpoints loaded | – | full (out-of-memory retries) | ~3 GB of 4 GB |

Scores are identical across all three (max difference 0.004).

Why fp16 barely beats the CPU:

- **GTX cards have no tensor cores.** Laya autocasts to fp16 on every GPU older than Ampere,
  but on the 1650 a raw fp16 matmul ran at 0.4 TFLOPS against 1.8 TFLOPS in fp32. Clocks were
  at full speed with no throttling, so it isn't the laptop's power settings.
- **fp16 autocast keeps extra weight copies.** With both checkpoints loaded that filled the
  4 GB card, and the allocator spent much of each request freeing and retrying. English alone
  in fp32 took 251 ms; loaded next to the multilingual model in fp16 it took ~1.5 s.

The server switches Laya to fp32 on GTX cards (`server/backends.py`, override with
`LAYA_FP32`). It has to happen before the first forward pass, while no fp16 buffers exist. RTX
cards have tensor cores, so Laya's fp16 default should suit them; that is untested here.

torch is installed from PyTorch's CUDA 12.6 index (`pyproject.toml`), because the default PyPI
build pulls CUDA 13 wheels whose `nvidia-nvjitlink` failed its hash check here. Laya's own
benchmarks were run on a T4: 33 ms for one question, 72 ms for ten batched on the multilingual
checkpoint.
