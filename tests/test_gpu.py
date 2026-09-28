"""Batched Laya inference on the real GPU. Needs CUDA and the checkpoints; skipped otherwise.

Run alone: uv run pytest -m gpu
"""

import time

import pytest

torch = pytest.importorskip("torch")


def _free_gb() -> float:
    return torch.cuda.mem_get_info()[0] / 1e9 if torch.cuda.is_available() else 0.0


# Both checkpoints need ~4 GB. With less free (e.g. the Mood Lab server running on the same
# card) the allocator thrashes and these run ~20x slower, so skip instead.
pytestmark = [pytest.mark.gpu,
              pytest.mark.skipif(not torch.cuda.is_available(), reason="no CUDA GPU"),
              pytest.mark.skipif(torch.cuda.is_available() and _free_gb() < 4.5,
                                 reason="needs 4.5 GB free GPU memory; stop the Mood Lab server")]

from server.backends import LayaBackend  # noqa: E402
from boar_emotion_radar.questions import all_questions  # noqa: E402

TEXTS = [
    "I just won the lottery, I cannot believe it!",
    "The app crashes every time I open a chat on my Pixel 7",
    "Seu idiota, você quebrou tudo",
    "Funciona até no modo avião, sensacional!",
    "When is the iPhone version coming out?",
    "The meeting is at 3pm",
] * 6  # 36: more than one batch of 32, mixing both checkpoints


@pytest.fixture(scope="module")
def laya():
    backend = LayaBackend(device="cuda")
    backend.warm_up()
    return backend


def test_batch_matches_one_at_a_time(laya):
    questions = all_questions()
    batch = laya.predict_batch(TEXTS, questions, None, batch_size=32)
    assert len(batch) == len(TEXTS)
    for text, got in zip(TEXTS[:6], batch[:6]):
        want = laya.predict(text, questions, None)
        assert got["model"] == want["model"]
        assert got["model"].endswith("on cuda")
        # Padding to the batch's longest text shifts scores slightly (max 0.013 measured).
        for qid in questions:
            assert got["answers"][qid]["value"] == pytest.approx(want["answers"][qid]["value"], abs=0.02), (text, qid)
    # Repeats of a text land in different batches and positions but score the same.
    for i in range(6, len(TEXTS)):
        assert batch[i]["answers"]["joy"]["value"] == pytest.approx(batch[i % 6]["answers"]["joy"]["value"], abs=0.02)


def test_batch_reads_the_obvious_cases(laya):
    batch = laya.predict_batch(TEXTS[:6], all_questions(), None)
    value = lambda i, q: batch[i]["answers"][q]["value"]  # noqa: E731
    assert value(0, "joy") > 0.8
    assert value(1, "bug_report") > 0.8
    assert value(2, "anger") > 0.8
    assert value(4, "platform_request") > 0.5
    assert max(value(5, e) for e in ("joy", "anger", "fear", "sadness")) < 0.3


def test_batch_is_faster_per_text_than_single(laya):
    questions = all_questions()
    laya.predict_batch(TEXTS, questions, None)  # warm the batched shapes
    torch.cuda.synchronize()
    start = time.perf_counter()
    for text in TEXTS:
        laya.predict(text, questions, None)
    torch.cuda.synchronize()
    single = time.perf_counter() - start
    start = time.perf_counter()
    laya.predict_batch(TEXTS, questions, None, batch_size=32)
    torch.cuda.synchronize()
    batched = time.perf_counter() - start
    print(f"\n{len(TEXTS)} texts: one at a time {single * 1000:.0f} ms, batched {batched * 1000:.0f} ms")
    # RTX 3050, 10 questions: 66 ms/text one at a time, 47 ms batched. Laya already runs a
    # text's questions as one batch of rows, so batching texts adds less than one might expect.
    assert batched < single * 0.85
