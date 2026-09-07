"""Reddit posts mentioning a symbol -> intermediate records. The minimum-
score filter is applied HERE, before normalization (articles/s06-04's "one
auditable cleaning layer, not a retrieval-time patch") — a low-score post
never becomes a Document at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

MIN_SCORE = 10  # below this, dropped at parse time — data_catalog.yaml's
                 # reddit_mentions notes on why this source needs a noise floor
DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")


@dataclass
class RawRedditPost:
    symbol: str
    post_id: str
    subreddit: str
    title: str
    body: str
    score: int
    url: str
    created_at: datetime


def fetch_reddit_mentions(
    symbol: str,
    client_id: str,
    client_secret: str,
    user_agent: str,
    subreddits: tuple[str, ...] = DEFAULT_SUBREDDITS,
    limit: int = 50,
) -> list[dict]:
    import praw

    reddit = praw.Reddit(client_id=client_id, client_secret=client_secret, user_agent=user_agent)
    posts = []
    for subreddit_name in subreddits:
        for submission in reddit.subreddit(subreddit_name).search(symbol, sort="new", limit=limit):
            posts.append(
                {
                    "id": submission.id,
                    "subreddit": subreddit_name,
                    "title": submission.title,
                    "selftext": submission.selftext,
                    "score": submission.score,
                    "permalink": submission.permalink,
                    "created_utc": submission.created_utc,
                }
            )
    return posts


def parse_reddit_posts(symbol: str, raw_posts: list[dict]) -> list[RawRedditPost]:
    kept = []
    for post in raw_posts:
        if post.get("score", 0) < MIN_SCORE:
            continue
        body = post.get("selftext", "").strip()
        if not body and not post.get("title"):
            continue
        kept.append(
            RawRedditPost(
                symbol=symbol,
                post_id=post["id"],
                subreddit=post["subreddit"],
                title=post.get("title", ""),
                body=body,
                score=post["score"],
                url=f"https://reddit.com{post['permalink']}",
                created_at=datetime.fromtimestamp(post["created_utc"], tz=timezone.utc),
            )
        )
    return kept
