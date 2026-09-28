"""Scores pending replies in batches through Mood Lab and stores the results.

The queue is the `replies` table itself (store.pending), so nothing is lost on restart and a
failed batch is simply picked up again. DuckDB calls run in a thread on the worker's own
cursor, so they don't block the API's event loop.
"""

import asyncio
import logging

import duckdb

from . import store
from .moodlab import MoodLab, MoodLabError

log = logging.getLogger("boar_emotion_radar.worker")


async def run_once(cur: duckdb.DuckDBPyConnection, moodlab: MoodLab, batch_size: int) -> int:
    """Score up to `batch_size` pending replies; returns how many were stored."""
    rows = await asyncio.to_thread(store.pending, cur, batch_size)
    if not rows:
        return 0
    results = await moodlab.analyze_batch([text for _, text in rows], batch_size)
    scored = [store.Scored(cid, emotions, signals, moodlab.backend, model)
              for (cid, _), (emotions, signals, model) in zip(rows, results)]
    await asyncio.to_thread(store.save_scores, cur, scored)
    return len(scored)


async def run_forever(con: duckdb.DuckDBPyConnection, moodlab: MoodLab, batch_size: int,
                      wake: asyncio.Event | None = None, idle: float = 5.0,
                      max_backoff: float = 120.0) -> None:
    """Drain the queue batch after batch; when it is empty, wait `idle` seconds or until
    `wake` is set (new replies ingested). Failures back off exponentially up to `max_backoff`."""
    cur = con.cursor()
    wake = wake or asyncio.Event()
    backoff = idle
    try:
        while True:
            wake.clear()  # before the batch, so replies ingested during it still wake us
            try:
                n = await run_once(cur, moodlab, batch_size)
            except Exception as e:
                if isinstance(e, MoodLabError):
                    log.warning("batch failed, retrying in %.0f s: %s", backoff, e)
                else:
                    log.exception("batch failed, retrying in %.0f s", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue
            backoff = idle
            if n:
                log.info("scored %d replies", n)
            if n == batch_size:
                continue  # probably more pending
            try:
                await asyncio.wait_for(wake.wait(), idle)
            except TimeoutError:
                pass
    finally:
        cur.close()
