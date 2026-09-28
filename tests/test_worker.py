import asyncio

import httpx
import pytest

from tests.conftest import FakeMoodLab
from tests.factories import reply
from boar_emotion_radar import store, worker
from boar_emotion_radar.db import connect
from boar_emotion_radar.moodlab import MoodLab, MoodLabError
from boar_emotion_radar.questions import BOAR_QUESTIONS
from boar_emotion_radar.schemas import EmotionQuery


@pytest.fixture
def con():
    con = connect(":memory:")
    yield con
    con.close()


async def test_run_once_scores_one_batch(con, moodlab, fake):
    store.upsert_replies(con, [reply(1, "so angry, it crashed again"), reply(2, "happy!"),
                               reply(3), reply(4), reply(5), reply(6)])
    assert await worker.run_once(con, moodlab, batch_size=4) == 4
    assert store.pending_count(con) == 2

    (body,) = fake.bodies
    assert body["texts"] == ["so angry, it crashed again", "happy!", "gm", "gm"]
    assert body["batch_size"] == 4
    assert set(body["questions"]) >= set(BOAR_QUESTIONS) | {"joy", "bluff"}

    (angry,) = store.replies_by_emotion(con, EmotionQuery(username="boar_app", emotion="anger"))
    assert angry.reply.comment_id == "c001"
    assert angry.signals == {"bug_report": 0.9, "offline_praise": 0.05, "platform_request": 0.05}
    assert (angry.backend, angry.model) == ("laya", "laya/english on cuda")


async def test_run_once_with_empty_queue_skips_mood_lab(con, moodlab, fake):
    assert await worker.run_once(con, moodlab, 4) == 0
    assert fake.bodies == []


async def test_failed_batch_stays_pending(con, settings):
    fake = FakeMoodLab(fail=1)
    moodlab = MoodLab(settings, httpx.AsyncClient(transport=httpx.MockTransport(fake)))
    store.upsert_replies(con, [reply(1), reply(2)])
    with pytest.raises(MoodLabError, match="502"):
        await worker.run_once(con, moodlab, 4)
    assert store.pending_count(con) == 2
    assert await worker.run_once(con, moodlab, 4) == 2  # retried batch goes through


async def test_long_replies_are_truncated_to_mood_lab_limit(con, moodlab, fake):
    store.upsert_replies(con, [reply(1, "x" * 3000)])
    await worker.run_once(con, moodlab, 4)
    assert len(fake.bodies[0]["texts"][0]) == 2000


async def test_result_count_mismatch_is_an_error(con, settings):
    def short(request):
        return httpx.Response(200, json={"results": []})
    moodlab = MoodLab(settings, httpx.AsyncClient(transport=httpx.MockTransport(short)))
    store.upsert_replies(con, [reply(1)])
    with pytest.raises(MoodLabError, match="got 0 results"):
        await worker.run_once(con, moodlab, 4)
    assert store.pending_count(con) == 1


async def test_run_forever_drains_in_batches_and_wakes_on_new_replies(con, moodlab, fake):
    store.upsert_replies(con, [reply(i) for i in range(10)])
    wake = asyncio.Event()
    task = asyncio.create_task(worker.run_forever(con, moodlab, 4, wake, idle=30))
    try:
        await until(lambda: store.pending_count(con) == 0)
        assert [len(b["texts"]) for b in fake.bodies] == [4, 4, 2]

        # Idle for 30 s now; ingesting new replies and setting `wake` must not wait that long.
        store.upsert_replies(con, [reply(20), reply(21)])
        wake.set()
        await until(lambda: store.pending_count(con) == 0)
    finally:
        task.cancel()


async def test_run_forever_backs_off_and_recovers(con, settings):
    fake = FakeMoodLab(fail=2)
    moodlab = MoodLab(settings, httpx.AsyncClient(transport=httpx.MockTransport(fake)))
    store.upsert_replies(con, [reply(1)])
    task = asyncio.create_task(worker.run_forever(con, moodlab, 4, idle=0.01))
    try:
        await until(lambda: store.pending_count(con) == 0)
        assert len(fake.bodies) == 3
    finally:
        task.cancel()


async def until(cond, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not cond():
            await asyncio.sleep(0.01)
