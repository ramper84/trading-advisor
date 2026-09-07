from app.ingest.parsers.reddit_parser import MIN_SCORE, parse_reddit_posts

RAW_POSTS = [
    {
        "id": "abc123",
        "subreddit": "wallstreetbets",
        "title": "ACME to the moon",
        "selftext": "Loaded up on calls, this is going up.",
        "score": 250,
        "permalink": "/r/wallstreetbets/comments/abc123/acme_to_the_moon/",
        "created_utc": 1_725_000_000,
    },
    {
        "id": "def456",
        "subreddit": "stocks",
        "title": "quick thought",
        "selftext": "eh",
        "score": 2,  # below MIN_SCORE
        "permalink": "/r/stocks/comments/def456/quick_thought/",
        "created_utc": 1_725_000_100,
    },
]


def test_parse_reddit_posts_filters_below_min_score():
    parsed = parse_reddit_posts("ACME", RAW_POSTS)
    assert len(parsed) == 1
    assert parsed[0].post_id == "abc123"
    assert parsed[0].score >= MIN_SCORE


def test_parse_reddit_posts_builds_full_url():
    parsed = parse_reddit_posts("ACME", RAW_POSTS)
    assert parsed[0].url == "https://reddit.com/r/wallstreetbets/comments/abc123/acme_to_the_moon/"


def test_parse_reddit_posts_drops_empty_body_and_title():
    posts = [
        {
            "id": "empty1",
            "subreddit": "stocks",
            "title": "",
            "selftext": "",
            "score": 999,
            "permalink": "/r/stocks/comments/empty1/x/",
            "created_utc": 1_725_000_200,
        }
    ]
    assert parse_reddit_posts("ACME", posts) == []
