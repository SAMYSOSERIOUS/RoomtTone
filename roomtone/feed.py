"""Ghost-free feed: a Bluesky custom feed skeleton.

Bluesky lets anyone publish a feed. The app asks this server "what should I show?" and we answer with
post links. We answer with trending posts whose authors are NOT automated-looking. Filtered posts are
simply absent: the feed never says why, never labels anyone.

Run:   uvicorn roomtone.feed:app --port 8000
Then publish the feed record with Bluesky's feed-generator starter kit (see README).
"""
from pathlib import Path
import pandas as pd

try:
    from fastapi import FastAPI, Query
except ImportError:  # keep the rest of the project importable without fastapi
    FastAPI = None

FEED_URI = "at://did:example/app.bsky.feed.generator/ghost-free"
HOSTNAME = "feed.example.org"


def ghost_free_posts(events_path="data/bluesky/events_safe.parquet", scores_path="data/bluesky/scores.parquet", limit=50) -> list[str]:
    ev = pd.read_parquet(events_path)
    sc = pd.read_parquet(scores_path)
    groups = sc.set_index("account").group
    posts = ev[ev.kind == "post"].copy()
    posts["group"] = posts.account.map(groups).fillna("unknown")
    # keep humans and unknown (never punish an account we could not score); drop automated-looking
    keep = posts[posts.group.isin(["human", "unknown"])].sort_values("ts", ascending=False)
    return keep.uri.dropna().head(limit).tolist()


if FastAPI:
    app = FastAPI(title="Roomtone ghost-free feed")

    @app.get("/.well-known/did.json")
    def did():
        return {"@context": ["https://www.w3.org/ns/did/v1"], "id": f"did:web:{HOSTNAME}",
                "service": [{"id": "#bsky_fg", "type": "BskyFeedGenerator", "serviceEndpoint": f"https://{HOSTNAME}"}]}

    @app.get("/xrpc/app.bsky.feed.describeFeedGenerator")
    def describe():
        return {"did": f"did:web:{HOSTNAME}", "feeds": [{"uri": FEED_URI}]}

    @app.get("/xrpc/app.bsky.feed.getFeedSkeleton")
    def skeleton(feed: str = Query(...), limit: int = 30, cursor: str | None = None):
        uris = ghost_free_posts(limit=limit)
        return {"feed": [{"post": u} for u in uris]}
