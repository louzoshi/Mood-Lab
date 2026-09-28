"""Question set sent to Mood Lab for every reply: the 7 emotion bars plus BOAR product signals.

The BOAR questions are yes/no (`noul`), like the emotions (see server/presets.py for why).
Their instructions are in English even though many replies are Portuguese: on a hand-labelled
set of 9 English/Portuguese replies, the English wording made 3 wrong calls at 0.5 and the
Portuguese wording 5, including "gm boar fam" read as a 100% iOS/device request.
"""

from server.presets import emotion_questions

# id -> (label shown in the Playground, question sent to the model)
BOAR_QUESTIONS: dict[str, tuple[str, str]] = {
    "bug_report": (
        "Bug reports",
        "Is the user reporting a bug, crash, or error in the app?",
    ),
    "offline_praise": (
        "Offline / airplane-mode praise",
        "Is the user praising how the app works offline or in airplane mode?",
    ),
    "platform_request": (
        "iOS / new device requests",
        "Is the user asking for an iOS version or support for new chips or devices?",
    ),
}


def boar_questions() -> dict:
    return {qid: {"type": "noul", "instructions": q} for qid, (_, q) in BOAR_QUESTIONS.items()}


def all_questions() -> dict:
    return {**emotion_questions(), **boar_questions()}
