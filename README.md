# Boar-Emotion-Radar

Tracks the mood of the community replying to the BOAR app (@boar_app) on X: replies are scraped,
scored for 7 emotions and BOAR-specific signals on the local GPU, stored in DuckDB and served to
LLM agents (REST and MCP). The scoring runs on Mood Lab, a zero-shot sentiment server in this repo
(`server/`), described in the second half of this README.

## Run

```bash
uv sync
uv run uvicorn server.app:app --port 8000      # open http://localhost:8000/#radar
```

One process serves the Mood Lab Playground, the **Boar X-Radar** tab, the radar API under
`/radar/api` (docs at `/radar/docs`) and the scoring worker, on the GPU when there is one. In the
tab, paste a post URL or id and press **Collect & analyze**; without `APIFY_TOKEN`, import an
Apify dataset export (.json) instead. Posts already collected are in the **Analyzed posts**
list, and `#radar/<post id>` links straight to a post's dashboard.

The dashboard shows:

- **KPIs:** replies analyzed, likes and views on them, and the predominant emotion as a share of
  replies. A reply counts toward an emotion only if that emotion reaches 50%; below that on every
  emotion it is neutral.
- **Emotion mix:** the share of replies each emotion leads, with average intensity on hover.
  Bars rather than a radar or donut chart: with 8 slices neither can be compared by eye.
- **Emotion vs engagement:** one dot per reply, the chosen emotion's intensity against likes or
  views (log scale), hover for the text.
- **BOAR product signals:** share of replies answering yes to each BOAR question.
- **Most positive / Critical & alerts:** top 5 by joy, and by the highest of anger, disgust and
  bug report, with likes and views.

For LLM agents, the MCP server (stdio) calls the same API:

```bash
uv run python -m boar_emotion_radar.mcp_server
```

### How it works

- **Ingest:** `POST /radar/api/ingest {"post_url"}` scrapes the replies with the Apify actor
  `fastcrawler/twitter-x-comment-scraper-no-cookies-required` (needs `APIFY_TOKEN`; the actor is a
  paid rental). `{"post_url", "items": [...]}` imports an exported actor dataset instead. The
  actor takes one post per run; it does not list a profile's posts.
- **Worker:** runs in the server process (DuckDB allows one writing process per file). Replies
  with no scores are the queue; each batch of `BOAR_EMOTION_RADAR_BATCH_SIZE` (32) replies is one
  in-process `/api/analyze_batch` call, and a failed batch is retried with backoff.
- **Questions:** the 7 emotions plus three BOAR yes/no questions
  (`boar_emotion_radar/questions.py`): bug report, praise for offline/airplane mode, iOS or
  new-device request. They are worded in English: on a small hand-labelled English/Portuguese
  set, Portuguese wording made more wrong calls, e.g. "gm boar fam" as a 100% iOS request. Both
  still misfire on some replies (a Portuguese crash report also read as an iOS request), so
  treat them as leads, not counts. Zero-shot, the emotions miss plain praise too: "This app is
  great, love the design" reads as 14% joy on either checkpoint.
- **Agent tools:** `get_profile_overview(username)`, `query_replies_by_emotion(username,
  emotion, min_score)`, `analyze_text_sentiment(text)`, as `GET /radar/api/profiles/{u}/overview`,
  `GET /radar/api/profiles/{u}/replies?emotion=&min_score=` and `POST /radar/api/analyze`.

Settings are environment variables (`BOAR_EMOTION_RADAR_*`, `MOODLAB_*`, `APIFY_TOKEN`), listed
in `boar_emotion_radar/config.py`. The database is `data/boar_emotion_radar.duckdb`.

### Batching

Batching helps less than it might seem: on an RTX 3050 with the 10 questions, a reply takes
66 ms alone and 47 ms in a batch of 32 (~21 replies/s), because Laya already runs one text's
questions as a batch. Batched scores differ from one-at-a-time by at most 0.013 (padding).

### Tests

`uv run pytest`. The GPU tests (`-m gpu`) need CUDA and 4.5 GB free, so stop the Mood Lab
server first; they skip otherwise.

## Mood Lab: the sentiment engine

A playground for zero-shot sentiment analysis with [Laya](https://github.com/NandhaKishorM/laya)
(local) or Jev (TypeSafe cloud), plus a pass-the-phone party game built on top of it.

### Run

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

### What's in it

- **Playground:** type text and see 7 emotion bars (joy, sadness, anger, fear, surprise,
  disgust, bluff) update live, plus any yes/no, score or choice questions you add yourself.
- **Game: Hit the Mood:** each round shows a target such as *Fear HIGH + Bluff MEDIUM*. Every
  player writes one line, scores 0–100 by how close the model's reading lands, and the round
  ends with a leaderboard of everyone's lines.
- **API:** `POST /api/analyze {"text", "questions"?, "backend": "laya"|"jev", "model": "auto"|"english"|"multilingual"}`.
  `POST /api/analyze_batch` takes `"texts"` (up to 64) instead of `"text"` and runs them through
  shared forward passes. `GET /api/config` returns the presets.

### Findings (Laya 0.3.20, zero-shot)

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

### Performance: CPU vs GPU

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

On torch 2.14 some eager CUDA ops run as Triton kernels, which compile C on first use. Without a C
compiler (`cc`/`gcc`) the server switches those back to the stock CUDA kernels
(`server/backends.py`); scores match the CPU's to 0.001.
