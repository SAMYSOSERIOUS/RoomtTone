"""Collect events from Bluesky's live stream (Jetstream), or simulate a realistic stream.

Real mode:      python -m roomtone.collect --hours 24 --topics "climate,election"
Practice mode:  python -m roomtone.collect --simulate --hours 72

Both write data/events.parquet with one row per event:
  kind: post | reply | like | delete | account_created
  ts, account, target_account (who a reply/like went to), uri, ref (for deletes),
  text, topic, lang, created_at (account creation time), declared_bot
Plus data/official_trends.parquet: the platform's own trending list, hourly.
"""
import argparse, asyncio, json, math, re, time
from pathlib import Path
import numpy as np
import pandas as pd

JETSTREAM = "wss://jetstream2.us-east.bsky.network/subscribe?wantedCollections=app.bsky.feed.post&wantedCollections=app.bsky.feed.like"
DATA = Path("data")


# ----------------------------------------------------------------------------- real stream
async def stream_jetstream(hours: float, topics: list[str]) -> list[dict]:
    """Read Bluesky's public event stream. No account or key is needed."""
    import websockets  # imported here so --simulate works without it
    out, stop = [], time.time() + hours * 3600
    pattern = re.compile("|".join(re.escape(t) for t in topics), re.I) if topics else None
    async with websockets.connect(JETSTREAM, max_size=2**22) as ws:
        async for raw in ws:
            if time.time() > stop:
                break
            msg = json.loads(raw)
            c = msg.get("commit")
            if not c:
                continue
            did, op, coll = msg["did"], c.get("operation"), c.get("collection")
            uri = f"at://{did}/{coll}/{c.get('rkey')}"
            if op == "delete":
                out.append(dict(kind="delete", ts=msg["time_us"] / 1e6, account=did, ref=uri))
                continue
            rec = c.get("record", {})
            if coll == "app.bsky.feed.post":
                text = rec.get("text", "")
                if pattern and not pattern.search(text):
                    continue
                reply = rec.get("reply", {}).get("parent", {}).get("uri")
                out.append(dict(kind="reply" if reply else "post", ts=msg["time_us"] / 1e6, account=did,
                                target_account=reply.split("/")[2] if reply else None, uri=uri, text=text,
                                lang=(rec.get("langs") or ["und"])[0], topic=_topic_of(text, topics)))
            elif coll == "app.bsky.feed.like":
                subj = rec.get("subject", {}).get("uri", "")
                out.append(dict(kind="like", ts=msg["time_us"] / 1e6, account=did,
                                target_account=subj.split("/")[2] if subj else None, uri=uri))
    return out


def _topic_of(text: str, topics: list[str]) -> str:
    for t in topics:
        if t.lower() in text.lower():
            return t
    return "other"


# ----------------------------------------------------------------------------- simulator
HUMAN_PHRASES = ["honestly not sure about this", "lol same", "my kid asked me this yesterday", "ok but why",
                 "saw this on the train", "typo sorry", "can't sleep, reading about", "hot take:",
                 "anyone else?", "this is fine", "wait what", "source?"]
BOT_PHRASES = ["the notion that", "oversimplifies the issue", "it is worth noting that", "in today's landscape",
               "let us delve into", "a multifaceted topic", "this underscores the importance of",
               "as we navigate", "a nuanced perspective", "ultimately, the key takeaway"]
PII_BITS = ["contact me at {n}@mail.example", "call +49 151 {d}", "@{h} has the proof", "my name is {N}, ask me anything",
            "write to {n}.{h}@post.example", "{N} from Hauptstraße {s} saw it too"]
FIRST = ["Anna", "Jonas", "Maria", "Lukas", "Sofia", "Pedro", "Claire", "Tom"]; LAST = ["Weber", "Lopez", "Martin", "Schmidt", "Rossi", "Dubois"]


def _pii(rng):
    n, l = rng.choice(FIRST), rng.choice(LAST)
    return " " + rng.choice(PII_BITS).format(n=n.lower(), N=f"{n} {l}", h=f"{n.lower()}_{rng.integers(10, 99)}", d=rng.integers(1000000, 9999999), s=rng.integers(1, 200))


HELPER_TEXT = ["Weather update: 14°C, light rain", "New post on the blog", "Earthquake M3.1 reported",
               "Top headlines this hour", "Bridged from Mastodon"]


MOOD_WORDS = {-1: ["terrible", "disgusting", "a disaster", "fed up", "scared"], 0: ["hm", "interesting", "not sure", "watching"],
              1: ["great", "hopeful", "love this", "finally", "good news"]}
GHOST_DOMAINS = ["truth-now.example", "wake-up-news.example", "the-real-story.example"]
HUMAN_DOMAINS = ["tagesschau.example", "lemonde.example", "elpais.example", "bbc.example", "wikipedia.example", "reddit.example"]
# audience scenarios for the practice stream (what real data would reveal, if present):
#   de: bots turn negative on election first, humans follow 3 h later   -> "steered"
#   es: humans are positive on election, bots push negative, humans hold -> "against locals"
#   en: bots copy human mood                                             -> "mirror"
#   fr: no bots target fr                                                -> clean baseline
BOT_ORIGIN_TZ = {"de": [3, 3, 3, -5], "es": [-5, -5, 3], "en": [3, 0, -5]}
# sub-topics: (name, share of human posts, how much harder bots push it than the topic average)
SUBTOPICS = {
    "election": [("mail-in voting", .24, 1.9), ("candidate debate", .31, .6), ("polling numbers", .18, 1.1), ("turnout drives", .15, .4), ("fraud claims", .12, 2.6)],
    "climate": [("heatwave", .35, .8), ("carbon tax", .3, 1.6), ("electric cars", .2, 1.9), ("protests", .15, 1.3)],
    "football": [("match night", .5, .5), ("transfer rumours", .25, 1.4), ("referees", .15, 1.8), ("betting tips", .1, 2.5)],
    "housing": [("rents", .45, .9), ("interest rates", .3, 1.2), ("empty flats", .25, 1.7)],
    "ai": [("jobs", .4, 1.1), ("regulation", .35, 1.0), ("creativity", .25, 1.4)],
}
# what each platform's stream looks like, relative to Bluesky
SOURCE_PROFILES = {
    "bluesky": dict(push_offset_h=0, scale=1.0, langs={"en": .45, "de": .22, "es": .18, "fr": .15}, bot_mult={"ai": 1, "climate": 1, "election": 1, "football": 1, "housing": 1}, helpers=1.0, sleepers=True, deletes=True, seed=7),
    "mastodon": dict(push_offset_h=5, scale=.46, langs={"en": .45, "de": .3, "es": .05, "fr": .2}, bot_mult={"ai": .55, "climate": .5, "election": .42, "football": .5, "housing": .45}, helpers=.4, sleepers=False, deletes=True, seed=11),
    "reddit": dict(push_offset_h=-3, scale=2.3, langs={"en": .7, "de": .15, "es": .12, "fr": .03}, bot_mult={"ai": 1.3, "climate": .9, "election": 1.25, "football": 1.6, "housing": 1.2}, helpers=1.8, sleepers=True, deletes=True, seed=19),
    "youtube": dict(push_offset_h=2, scale=1.7, langs={"en": .5, "de": .15, "es": .2, "fr": .15}, bot_mult={"ai": 1.6, "climate": 1.2, "election": 1.45, "football": 1.9, "housing": 1.5}, helpers=.2, sleepers=True, deletes=False, seed=23),
}


def _sub(rng, topic):
    subs = SUBTOPICS.get(topic)
    if not subs:
        return None, 1.0
    w = np.array([x[1] for x in subs]); i = rng.choice(len(subs), p=w / w.sum())
    return subs[i][0], subs[i][2]


def _mood_word(rng, m):
    b = -1 if m < -0.33 else (1 if m > 0.33 else 0)
    return rng.choice(MOOD_WORDS[b])


def simulate(hours: int = 72, seed: int = 7, n_humans=2400, n_bots=300, n_helpers=60, n_sleepers=120, source: str = "bluesky") -> tuple[pd.DataFrame, pd.DataFrame]:
    """A practice stream that behaves like a real one: humans sleep and regret, bots keep time,
    helper bots are declared, sleeper cells were born together and wake up on day 2, and a campaign
    pushes 'election' with different results in different language audiences (see scenarios above)."""
    P = SOURCE_PROFILES[source]
    rng = np.random.default_rng(P["seed"] if seed == 7 else seed)
    n_humans, n_bots = int(n_humans * P["scale"]), int(n_bots * P["scale"])
    n_helpers, n_sleepers = int(n_helpers * P["helpers"]), (n_sleepers if P["sleepers"] else 0)
    lang_p = P["langs"]
    t0 = float(((time.time() - hours * 3600) // 86400) * 86400)  # start at midnight UTC so hours-of-day mean something
    topics = ["climate", "election", "football", "housing", "ai"]
    ev, accounts = [], []

    def new_account(prefix, i, created_days_ago, declared=False, tz=1, kind="human", lang="en"):
        a = f"did:plc:{prefix}{i:05d}"
        accounts.append(dict(account=a, kind=kind))
        ev.append(dict(kind="account_created", ts=t0, account=a,
                       declared_bot=declared, created_at=t0 - created_days_ago * 86400, lang=lang, tz=tz))
        return a

    push_start = t0 + 24 * 3600 + (11 + P.get("push_offset_h", 0)) * 3600
    push_end = push_start + 5 * 3600
    base_mood = {"climate": -0.1, "election": 0.1, "football": 0.3, "housing": -0.2, "ai": 0.0}

    def human_mood(lang, topic, ts):
        m = base_mood[topic]
        if topic == "election":
            if lang == "de" and ts > push_start + 3 * 3600:      # steered: follows bots after 3 h
                m = -0.6
            elif lang == "es":                                    # holds its own positive mood
                m = 0.5
        return float(np.clip(m + rng.normal(0, 0.35), -1, 1))

    def bot_mood(lang, topic, ts):
        if topic != "election":
            return float(np.clip(base_mood[topic] + rng.normal(0, 0.3), -1, 1))
        if lang in ("de", "es") and ts >= push_start:
            return float(np.clip(-0.8 + rng.normal(0, 0.15), -1, 1))
        return human_mood("en", topic, ts)                        # en bots mirror humans

    humans = []
    for i in range(n_humans):
        lang = rng.choice(list(lang_p), p=list(lang_p.values()))
        tz = {"en": rng.choice([-5, 0, 1]), "de": 1, "es": rng.choice([1, -5]), "fr": 1}[lang]
        a = new_account("h", i, rng.integers(30, 2000), tz=tz, lang=lang)
        humans.append((a, tz, lang, rng.choice(topics, p=[.22, .34, .18, .16, .1])))
    bots = []
    for i in range(n_bots):
        lang = rng.choice(["en", "de", "es"], p=[.3, .4, .3])
        origin = int(rng.choice(BOT_ORIGIN_TZ[lang]))
        bots.append((new_account("b", i, rng.integers(5, 400), kind="bot", lang=lang, tz=origin), rng.uniform(1.5, 6.0),
                     rng.choice(["metronome", "jittered", "scheduled"], p=[.35, .35, .3]), lang, origin))
    helpers = [new_account("s", i, rng.integers(100, 1500), declared=True, kind="helper") for i in range(n_helpers)]
    birthday = 40 + rng.integers(0, 2)
    sleepers = [new_account("z", i, birthday + rng.uniform(0, 0.3), kind="sleeper", lang="de", tz=3) for i in range(n_sleepers)]

    post_uris = []
    uid = [0]

    def post(kind, a, ts, text, topic, lang, mood, target=None):
        uid[0] += 1
        uri = f"at://{a}/app.bsky.feed.post/{uid[0]}"
        ev.append(dict(kind=kind, ts=ts, account=a, target_account=target, uri=uri, text=text, topic=topic, lang=lang, mood_true=mood))
        post_uris.append((uri, a, ts, topic, lang))
        return uri

    # humans
    for a, tz, lang, fav in humans:
        for _ in range(rng.poisson(hours / 24 * 4)):
            local_h = rng.choice(np.arange(24), p=_awake_profile())
            day = rng.integers(0, max(1, hours // 24))
            ts = t0 + day * 86400 + ((local_h - tz) % 24) * 3600 + rng.uniform(0, 3600)
            topic = fav if rng.random() < .6 else rng.choice(topics)
            sub, _ = _sub(rng, topic)
            m = human_mood(lang, topic, ts)
            phrase = rng.choice(BOT_PHRASES) if rng.random() < .09 else rng.choice(HUMAN_PHRASES)
            link = f" https://{rng.choice(HUMAN_DOMAINS)}/{topic}" if rng.random() < .12 else ""
            pii = _pii(rng) if rng.random() < .03 else ""
            u = post("post", a, ts, f"{phrase} {topic} {sub or ''}, {_mood_word(rng, m)}{link}{pii}", topic, lang, m)
            if P["deletes"] and rng.random() < 0.06:
                ev.append(dict(kind="delete", ts=ts + rng.uniform(60, 7200), account=a, ref=u))
    # bots: sleep (if scheduled) in their ORIGIN time zone, post to their AUDIENCE language
    for a, gap_h, style, lang, origin in bots:
        ts = t0 + rng.uniform(0, gap_h * 3600)
        while ts < t0 + hours * 3600:
            local_h = ((ts // 3600) + origin) % 24
            if style == "scheduled" and (local_h < 7 or local_h > 23):
                ts += 3600; continue
            in_push = push_start <= ts <= push_end + 6 * 3600
            topic = "election" if (in_push and lang != "en") or rng.random() < .3 else rng.choice(topics)
            sub, hard = _sub(rng, topic)
            if rng.random() > min(1.0, P["bot_mult"][topic] * hard / 1.5):
                ts += 0.5 * gap_h * 3600; continue  # this platform / sub-topic gets pushed less
            m = bot_mood(lang, topic, ts)
            phrase = rng.choice(BOT_PHRASES) if rng.random() < .16 else rng.choice(HUMAN_PHRASES)
            link = f" https://{rng.choice(GHOST_DOMAINS)}/{topic}" if (in_push and topic == "election" and rng.random() < .35) else ""
            pii = _pii(rng) if rng.random() < .08 else ""
            u = post("post", a, ts + rng.normal(0, 90), f"{phrase} {topic} {sub or ''}, {_mood_word(rng, m)}{link}{pii}", topic, lang, m)
            if P["deletes"] and rng.random() < 0.005:
                ev.append(dict(kind="delete", ts=ts + 600, account=a, ref=u))
            jitter = {"metronome": 0.05, "jittered": 0.45, "scheduled": 0.25}[style]
            ts += max(600, rng.normal(gap_h * 3600, jitter * gap_h * 3600))
            if in_push:
                ts -= 0.5 * gap_h * 3600
    for a in helpers:
        for k in range(hours):
            post("post", a, t0 + k * 3600 + 30, rng.choice(HELPER_TEXT), "other", "en", 0.0)
    for a in sleepers:
        for k in range(rng.integers(6, 14)):
            ts = push_start + 2 * 3600 + rng.uniform(0, 2 * 3600)
            post("post", a, ts, f"{rng.choice(BOT_PHRASES)} election fraud claims, {_mood_word(rng, -0.8)} https://{rng.choice(GHOST_DOMAINS)}/election", "election", "de", -0.8)

    # replies and likes
    posts_df = pd.DataFrame(post_uris, columns=["uri", "account", "ts", "topic", "lang"])
    by_topic = {t: g for t, g in posts_df.groupby("topic")}
    by_lang_topic = {k: g for k, g in posts_df.groupby(["lang", "topic"])}
    human_by_lang = {}
    for a, tz, lang, fav in humans:
        human_by_lang.setdefault(lang, []).append(a)
    for a, tz, lang, fav in humans:
        for _ in range(rng.poisson(hours / 24 * 3)):
            t = fav if rng.random() < .7 else rng.choice(topics)
            g = by_lang_topic.get((lang, t)) if rng.random() < .8 else by_topic.get(t)
            if g is None or len(g) == 0:
                continue
            row = g.iloc[rng.integers(0, len(g))]
            ts = row.ts + rng.uniform(120, 6 * 3600)
            if rng.random() < .55:
                ev.append(dict(kind="like", ts=ts, account=a, target_account=row.account, uri=None, topic=row.topic, lang=lang))
            else:
                m = human_mood(lang, row.topic, ts)
                post("reply", a, ts, f"{rng.choice(HUMAN_PHRASES)}, {_mood_word(rng, m)}", row.topic, lang, m, target=row.account)
    # bots reply to and like humans in their audience language (the "who they target" signal)
    for a, _, style, lang, origin in bots:
        pool = human_by_lang.get(lang, [])
        for _ in range(rng.poisson(hours / 24 * 5)):
            g = by_lang_topic.get((lang, "election"))
            if g is None or len(g) == 0 or not pool:
                continue
            row = g.iloc[rng.integers(0, len(g))]
            ts = row.ts + rng.uniform(5, 900)
            local_h = ((ts // 3600) + origin) % 24
            if style == "scheduled" and (local_h < 7 or local_h > 23):
                continue
            if rng.random() < .6:
                ev.append(dict(kind="like", ts=ts, account=a, target_account=row.account, uri=None, topic="election", lang=lang))
            else:
                m = bot_mood(lang, "election", ts)
                post("reply", a, ts, f"{rng.choice(BOT_PHRASES)}, {_mood_word(rng, m)}", "election", lang, m, target=rng.choice(pool))

    df = pd.DataFrame(ev)
    posts_only = df[df.kind.isin(["post", "reply"])].copy()
    posts_only["hour"] = ((posts_only.ts - t0) // 3600).astype(int)
    official = (posts_only.groupby(["hour", "topic"]).size().rename("posts").reset_index()
                .sort_values(["hour", "posts"], ascending=[True, False]).groupby("hour").head(3))
    official["rank"] = official.groupby("hour").cumcount() + 1
    return df.sort_values("ts").reset_index(drop=True), official.reset_index(drop=True)


def _awake_profile():
    p = np.array([0.2, 0.1, 0.05, 0.05, 0.05, 0.1, 0.5, 1.2, 1.8, 2.0, 2.0, 2.2, 2.4, 2.0, 1.8, 1.8, 2.0, 2.4, 3.0, 3.2, 3.0, 2.6, 1.8, 0.8])
    return p / p.sum()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--hours", type=float, default=72)
    ap.add_argument("--topics", default="climate,election,football,housing,ai")
    ap.add_argument("--source", default="bluesky", choices=list(SOURCE_PROFILES))
    a = ap.parse_args()
    out = DATA / a.source
    out.mkdir(parents=True, exist_ok=True)
    if a.simulate:
        df, official = simulate(int(a.hours), source=a.source)
    elif a.source != "bluesky":
        from . import sources
        df, official = sources.collect(a.source, a.hours, [t.strip() for t in a.topics.split(",") if t.strip()])
    else:
        events = asyncio.run(stream_jetstream(a.hours, [t.strip() for t in a.topics.split(",") if t.strip()]))
        df = pd.DataFrame(events)
        official = pd.DataFrame(columns=["hour", "topic", "posts", "rank"])  # fill from the trends endpoint
    df.to_parquet(out / "events.parquet", index=False)
    official.to_parquet(out / "official_trends.parquet", index=False)
    print(f"saved {len(df):,} events and {len(official):,} trend rows to {out}/")


if __name__ == "__main__":
    main()
