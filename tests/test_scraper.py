import httpx
import pytest

from boar_emotion_radar import scraper

# Output item shape documented for the Apify actor.
ITEM = {
    "commentId": "1910400000000000001", "userId": "42", "isBlueVerified": False,
    "twitterName": "Ana", "twitterUsername": "Ana_Dev", "viewCount": "1.2K",
    "replyContent": "O app fecha quando baixo o modelo", "likeCount": 3, "replyCount": 0,
    "retweetCount": 0, "quoteCount": 0, "bookmarkCount": 0,
    "createdAt": "Sun Sep 27 18:04:11 +0000 2026",
}


@pytest.mark.parametrize("url", [
    "https://x.com/boar_app/status/1910363426972635455",
    "https://twitter.com/BOAR_APP/status/1910363426972635455?s=20",
    "https://mobile.x.com/boar_app/status/1910363426972635455/photo/1",
])
def test_parse_post_url(url):
    assert scraper.parse_post_url(url) == ("boar_app", "1910363426972635455")


@pytest.mark.parametrize("url", ["https://x.com/boar_app", "https://example.com/a/status/1"])
def test_parse_post_url_rejects(url):
    with pytest.raises(ValueError):
        scraper.parse_post_url(url)


def test_to_replies_maps_actor_items():
    (reply,), skipped = scraper.to_replies([ITEM], "boar_app", "1910363426972635455")
    assert skipped == 0
    assert (reply.post_id, reply.profile_username, reply.twitter_username) == (
        "1910363426972635455", "boar_app", "ana_dev")
    assert reply.view_count == 1200
    assert reply.created_at.isoformat() == "2026-09-27T18:04:11+00:00"


def test_to_replies_skips_the_post_and_broken_items():
    items = [ITEM, {**ITEM, "commentId": "999"}, {**ITEM, "commentId": "1", "replyContent": ""},
             {**ITEM, "commentId": "2", "viewCount": "lots"}]
    replies, skipped = scraper.to_replies(items, "boar_app", "999")
    assert [r.comment_id for r in replies] == [ITEM["commentId"]]
    assert skipped == 3


async def test_fetch_items_calls_the_actor():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["body"] = request.content
        return httpx.Response(201, json=[ITEM])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    items = await scraper.fetch_items("https://x.com/boar_app/status/1", "tok", 50, client)
    assert items == [ITEM]
    assert seen["url"] == scraper.RUN_URL and seen["auth"] == "Bearer tok"
    assert b'"maxItems":50' in seen["body"].replace(b" ", b"")


async def test_fetch_items_raises_on_http_error():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(402, text="rent")))
    with pytest.raises(scraper.ScraperError, match="402"):
        await scraper.fetch_items("https://x.com/boar_app/status/1", "tok", 50, client)


def test_parse_bare_post_id_uses_default_profile():
    assert scraper.parse_post_url(" 1910363426972635455 ", "BOAR_app") == ("boar_app", "1910363426972635455")
    with pytest.raises(ValueError):
        scraper.parse_post_url("1910363426972635455")  # no default profile
