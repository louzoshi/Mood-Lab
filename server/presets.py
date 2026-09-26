"""Question sets sent to Laya/Jev.

Each emotion is a yes/no (`noul`) question. Zero-shot, noul answers are calibrated and sit
near 0 for neutral text, while 4-level score rubrics drift toward the middle and read
"meeting at 3pm" as ~55% of every emotion (see README, "Findings"). The overall vibe is
derived from these in the frontend: a "what is the tone?" choice question mislabelled
obvious Portuguese joy as negative.
"""

LEVELS = ["none", "low", "medium", "high"]

# id -> (label, emoji, question, usable as a game target)
EMOTIONS: dict[str, tuple[str, str, str, bool]] = {
    "joy": ("Joy", "😄", "Does the writer express happiness, joy, or excitement?", True),
    "sadness": ("Sadness", "😢", "Does the writer express sadness, grief, or disappointment?", True),
    "anger": ("Anger", "😠", "Does the writer express anger, irritation, or frustration?", True),
    "fear": ("Fear", "😨", "Does the writer express fear, anxiety, or feeling in danger?", True),
    "surprise": ("Surprise", "😲", "Does the writer express surprise, shock, or disbelief?", True),
    "disgust": ("Disgust", "🤢", "Does the writer express disgust or revulsion?", True),
    "bluff": ("Bluff", "🤥", "Does the writer sound like they are lying, exaggerating, or protesting too much?", True),
}


def emotion_questions() -> dict:
    return {eid: {"type": "noul", "instructions": q} for eid, (_, _, q, _) in EMOTIONS.items()}


def public_presets() -> dict:
    """What the frontend needs to render bars and build games."""
    return {
        "levels": LEVELS,
        "emotions": [
            {"id": eid, "label": label, "emoji": emoji, "game": game}
            for eid, (label, emoji, _, game) in EMOTIONS.items()
        ],
        "questions": emotion_questions(),
    }
