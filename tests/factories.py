from datetime import UTC, datetime, timedelta

from boar_emotion_radar.schemas import Reply

T0 = datetime(2026, 9, 28, 12, tzinfo=UTC)


def reply(i: int, text: str = "gm", profile: str = "boar_app", likes: int = 0) -> Reply:
    return Reply(comment_id=f"c{i:03}", post_id="p1", profile_username=profile,
                 twitter_username=f"user{i}", reply_content=text, like_count=likes,
                 view_count=likes * 10, created_at=T0 + timedelta(minutes=i))
