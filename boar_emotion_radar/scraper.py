"""Replies to an X post, from the Apify actor behind
github.com/robert-465/twitter-x-comment-scraper-no-cookies-required.

That repo's own Python code cannot work: it parses x.com HTML with BeautifulSoup, but X builds
posts in JavaScript, so the served HTML has no `tweetText` at all. It is a pointer to the
hosted actor, which is what this calls (APIFY_TOKEN; the actor is a paid rental). An actor
dataset exported as JSON goes through `to_replies` the same way.

The actor takes one post URL per run and does not list a profile's posts.
"""

import re

import httpx
from pydantic import ValidationError

from .schemas import Reply, username

ACTOR = "fastcrawler~twitter-x-comment-scraper-no-cookies-required"
RUN_URL = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"
POST_URL = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/(\w{1,15})/status/(\d+)")


class ScraperError(RuntimeError):
    pass


def parse_post_url(url: str, default_profile: str | None = None) -> tuple[str, str]:
    """(profile username, post id) from an x.com or twitter.com status URL, or from a bare
    post id when `default_profile` is given."""
    url = url.strip()
    if default_profile and url.isdigit():
        return username(default_profile), url
    m = POST_URL.match(url)
    if not m:
        raise ValueError(f"not an X post URL or id: {url!r}")
    return username(m[1]), m[2]


def to_replies(items: list[dict], profile: str, post_id: str) -> tuple[list[Reply], int]:
    """Actor items -> (replies, skipped). Skips the post itself and unparseable items
    (deleted or withheld replies come back without text)."""
    replies, skipped = [], 0
    for item in items:
        if item.get("commentId") == post_id:
            skipped += 1
            continue
        try:
            replies.append(Reply.model_validate({**item, "postId": post_id,
                                                 "profileUsername": profile}))
        except ValidationError:
            skipped += 1
    return replies, skipped


async def fetch_items(post_url: str, token: str, max_items: int,
                      client: httpx.AsyncClient | None = None) -> list[dict]:
    """Run the actor on one post and return its dataset items."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(330, connect=10))
    try:
        resp = await client.post(RUN_URL, headers={"Authorization": f"Bearer {token}"}, json={
            "tweetUrl": post_url, "maxItems": max_items, "sentimentAnalysis": False})
    except httpx.HTTPError as e:
        raise ScraperError(f"Apify unreachable: {e!r}") from e
    finally:
        if own:
            await client.aclose()
    if resp.status_code >= 400:
        raise ScraperError(f"Apify {resp.status_code}: {resp.text[:300]}")
    return resp.json()
