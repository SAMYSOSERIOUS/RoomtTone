"""Real collectors for the other platforms. Each returns (events, official_trends) in the same shape as
collect.py, so the privacy gate and everything after it are identical for every source.

    python -m roomtone.collect --source mastodon --hours 6
    python -m roomtone.collect --source reddit   --hours 6      # needs REDDIT_ID / REDDIT_SECRET
    python -m roomtone.collect --source youtube  --hours 6      # needs YOUTUBE_KEY

Only public content is read. Nothing here stores a display name, avatar or bio.
"""
import os, time
import pandas as pd

MASTODON_INSTANCES = ["mastodon.social", "mastodon.online", "fosstodon.org", "mas.to", "mstdn.social"]


def collect(source: str, hours: float, topics: list[str]):
    return {"mastodon": mastodon, "reddit": reddit, "youtube": youtube}[source](hours, topics)


def _topic_of(text, topics):
    for t in topics:
        if t.lower() in (text or "").lower():
            return t
    return "other"


def mastodon(hours, topics):
    try:
        from mastodon import Mastodon
    except ImportError:
        raise SystemExit("pip install Mastodon.py")
    stop, out = time.time() + hours * 3600, []
    while time.time() < stop:
        for inst in MASTODON_INSTANCES:
            api = Mastodon(api_base_url=f"https://{inst}")
            for st in api.timeline_public(limit=40):
                text = st.get("content", "")
                topic = _topic_of(text, topics)
                if topic == "other":
                    continue
                acc = f"{inst}/{st['account']['id']}"
                out.append(dict(kind="reply" if st.get("in_reply_to_account_id") else "post", ts=st["created_at"].timestamp(), account=acc,
                                target_account=f"{inst}/{st['in_reply_to_account_id']}" if st.get("in_reply_to_account_id") else None,
                                uri=st["uri"], text=text, topic=topic, lang=st.get("language") or "und"))
                out.append(dict(kind="account_created", ts=time.time(), account=acc, declared_bot=bool(st["account"].get("bot")),
                                created_at=st["account"]["created_at"].timestamp(), lang=st.get("language") or "und"))
        time.sleep(60)
    return _finish(out)


def reddit(hours, topics):
    try:
        import praw
    except ImportError:
        raise SystemExit("pip install praw")
    r = praw.Reddit(client_id=os.environ["REDDIT_ID"], client_secret=os.environ["REDDIT_SECRET"], user_agent="roomtone/0.1 (research, non-commercial)")
    stop, out = time.time() + hours * 3600, []
    for c in r.subreddit("all").stream.comments(skip_existing=True):
        if time.time() > stop:
            break
        topic = _topic_of(c.body, topics)
        if topic == "other":
            continue
        acc = f"reddit/{c.author.name}" if c.author else "reddit/deleted"
        parent = c.parent()
        target = f"reddit/{parent.author.name}" if getattr(parent, "author", None) else None
        out.append(dict(kind="reply" if target else "post", ts=c.created_utc, account=acc, target_account=target, uri=c.permalink, text=c.body, topic=topic, lang="und"))
        if c.author:
            out.append(dict(kind="account_created", ts=time.time(), account=acc, declared_bot=False, created_at=getattr(c.author, "created_utc", None), lang="und"))
    return _finish(out)


def youtube(hours, topics):
    try:
        from googleapiclient.discovery import build
    except ImportError:
        raise SystemExit("pip install google-api-python-client")
    yt = build("youtube", "v3", developerKey=os.environ["YOUTUBE_KEY"])
    out = []
    for topic in topics:
        vids = yt.search().list(q=topic, part="id", type="video", order="viewCount", maxResults=20).execute()
        for v in vids.get("items", []):
            vid = v["id"]["videoId"]
            res = yt.commentThreads().list(part="snippet", videoId=vid, maxResults=100, textFormat="plainText").execute()
            for it in res.get("items", []):
                sn = it["snippet"]["topLevelComment"]["snippet"]
                acc = "yt/" + sn.get("authorChannelId", {}).get("value", "unknown")
                out.append(dict(kind="post", ts=pd.Timestamp(sn["publishedAt"]).timestamp(), account=acc, target_account=None,
                                uri=f"yt/{vid}/{it['id']}", text=sn.get("textDisplay", ""), topic=topic, lang="und"))
    return _finish(out)


def _finish(out):
    df = pd.DataFrame(out)
    if df.empty:
        return df, pd.DataFrame(columns=["hour", "topic", "posts", "rank"])
    t0 = float(df.ts.min())
    posts = df[df.kind.isin(["post", "reply"])].copy()
    posts["hour"] = ((posts.ts - t0) // 3600).astype(int)
    official = (posts.groupby(["hour", "topic"]).size().rename("posts").reset_index()
                .sort_values(["hour", "posts"], ascending=[True, False]).groupby("hour").head(3))
    official["rank"] = official.groupby("hour").cumcount() + 1
    return df.sort_values("ts").reset_index(drop=True), official.reset_index(drop=True)
