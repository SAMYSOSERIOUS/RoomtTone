"""Where are the ghosts, who do they talk to, and where do they push people?

Per account (private, never published):   real time zone from the daily quiet window
Per audience language x topic (published): automated share, wasted breath, mood of humans vs bots,
                                           and a steering verdict: steered / against locals / mirror / clean
Per campaign (published):                  origin time zones -> audience languages -> message -> destinations
All published numbers are group totals with the 50-account minimum.
"""
import re
from urllib.parse import urlparse
import numpy as np
import pandas as pd
from . import MIN_GROUP

NEG = ["terrible", "disgusting", "disaster", "fed up", "scared", "angry", "worst", "lie", "shame"]
POS = ["great", "hopeful", "love", "finally", "good news", "best", "proud", "thank"]
_neg, _pos = re.compile("|".join(NEG), re.I), re.compile("|".join(POS), re.I)
URL = re.compile(r"https?://\S+")
SLEEP_CENTER_LOCAL = 3.5  # people are usually deepest asleep around 03:30 local time


def mood_score(text) -> float | None:
    """Tiny lexicon scorer for the practice stream. On real data, swap in the multilingual
    Cardiff NLP model (see README); the rest of the file does not change."""
    if not isinstance(text, str):
        return None
    n, p = len(_neg.findall(text)), len(_pos.findall(text))
    if n == p:
        return 0.0
    return (p - n) / (p + n)


# ----------------------------------------------------------------------------- time zone of origin
def infer_timezone(ev: pd.DataFrame, min_events: int = 12, window: int = 8, awake_centre_local: float = 17.0) -> pd.DataFrame:
    """UTC offset per account, using every kind of activity (posts, replies, likes, deletes).
    Two steps: (1) does the account go quiet at all? Its quietest 8-hour window must hold under 15% of
    its activity. (2) If so, where is the middle of its waking day? The circular average of its activity
    hours is robust even for people who post a dozen times a week; that middle sits near 17.0 local time (calibrated on the practice stream's known accounts)
    for most people, so tz = 17.0 - middle_utc. On real data, calibrate the 14.5 on accounts with a
    known location (local newsrooms, city councils). Never published per account."""
    acts = ev[ev.kind.isin(["post", "reply", "post_deleted", "like", "delete"])]
    rows = []
    for acc, g in acts.groupby("account"):
        if len(g) < min_events:
            continue
        hours = ((g.ts / 3600) % 24).values
        prof = np.bincount(hours.astype(int), minlength=24).astype(float)
        circ = np.concatenate([prof, prof])
        quiet_share = min(circ[i:i + window].sum() for i in range(24)) / prof.sum()
        sleeps = quiet_share < 0.15
        if not sleeps:
            rows.append(dict(account=acc, tz=None, sleeps=False, quiet_share=round(float(quiet_share), 3)))
            continue
        ang = hours / 24 * 2 * np.pi
        centre_utc = (np.arctan2(np.sin(ang).mean(), np.cos(ang).mean()) / (2 * np.pi) * 24) % 24
        tz = round(awake_centre_local - centre_utc)
        tz = ((tz + 12) % 24) - 12
        rows.append(dict(account=acc, tz=int(tz), sleeps=True, quiet_share=round(float(quiet_share), 3)))
    return pd.DataFrame(rows, columns=["account", "tz", "sleeps", "quiet_share"])


def _longest_quiet(prof):
    p = np.concatenate([prof, prof])
    best_len = best_start = run = 0
    for i, v in enumerate(p):
        run = run + 1 if v == 0 else 0
        if run > best_len:
            best_len, best_start = run, i - run + 1
    return best_start % 24, min(best_len, 24)


EXPECTED_TZ = {"de": {1, 2}, "fr": {1, 2}, "es": {1, 2, -5, -6, -3}, "en": {-8, -7, -6, -5, -4, 0, 1, 10, 11}}


def audience_language(ev: pd.DataFrame) -> pd.Series:
    """The language an account mostly posts in = the audience it talks to."""
    posts = ev[ev.kind.isin(["post", "reply"]) & ev.lang.notna()]
    return posts.groupby("account").lang.agg(lambda s: s.value_counts().index[0])


def origin_vs_audience(tzs: pd.DataFrame, langs: pd.Series, groups: pd.Series) -> pd.DataFrame:
    """Group totals: for each audience language and account group, where do the accounts really sleep?"""
    empty_out = pd.DataFrame(columns=["lang", "group", "region", "accounts", "share"])
    empty_mism = pd.DataFrame(columns=["lang", "group", "accounts", "mismatch_rate", "never_sleeps_rate"])
    if tzs.empty:
        return empty_out, empty_mism
    df = tzs.merge(langs.rename("lang"), left_on="account", right_index=True, how="left")
    df["group"] = df.account.map(groups).fillna("unknown")
    df["region"] = df.tz.map(_region)
    df.loc[~df.sleeps, "region"] = "never sleeps"
    out = df.groupby(["lang", "group", "region"]).size().rename("accounts").reset_index()
    tot = out.groupby(["lang", "group"]).accounts.transform("sum")
    out["share"] = (out.accounts / tot).round(3)
    out = out[tot >= MIN_GROUP]
    # mismatch: claims an audience whose usual time zones do not include where it sleeps
    # mismatch = sleeps more than 2 hours away from any time zone where that audience usually lives
    # (2 h = the measured error of the estimate; see validation.timezone_within_2h)
    df["mismatch"] = df.apply(lambda r: bool(r.sleeps and r.lang in EXPECTED_TZ and min(abs(int(r.tz) - e) for e in EXPECTED_TZ[r.lang]) > 2), axis=1)
    mism = df.groupby(["lang", "group"]).agg(accounts=("account", "size"), mismatch_rate=("mismatch", "mean"),
                                            never_sleeps_rate=("sleeps", lambda s: 1 - s.mean())).reset_index()
    mism = mism[mism.accounts >= MIN_GROUP].round(3)
    return (out if len(out) else empty_out), (mism if len(mism) else empty_mism)


def _region(tz):
    if tz is None or (isinstance(tz, float) and np.isnan(tz)):
        return "unknown"
    tz = int(tz)
    if -9 <= tz <= -3: return "Americas"
    if -2 <= tz <= 2: return "Europe/Africa west"
    if 3 <= tz <= 4: return "East Europe/Middle East"
    if 5 <= tz <= 7: return "South/Central Asia"
    return "East Asia/Pacific"


# ----------------------------------------------------------------------------- audience x topic
def audience_topic_table(ev: pd.DataFrame, groups: pd.Series, t0: float) -> pd.DataFrame:
    """Per audience language x topic: automated share of posts, wasted breath, mood gap."""
    posts = ev[ev.kind.isin(["post", "reply"]) & ev.lang.notna()].copy()
    posts["group"] = posts.account.map(groups).fillna("unknown")
    posts["mood"] = posts.text.map(mood_score)
    rows = []
    for (lang, topic), g in posts.groupby(["lang", "topic"]):
        if topic == "other":
            continue
        hum, bot = g[g.group == "human"], g[g.group == "automated"]
        if hum.account.nunique() < MIN_GROUP:
            continue
        rows.append(dict(lang=lang, topic=topic, human_accounts=int(hum.account.nunique()), automated_accounts=int(bot.account.nunique()),
                         automated_share=round(len(bot) / len(g), 3), human_mood=round(float(hum.mood.mean()), 3),
                         bot_mood=round(float(bot.mood.mean()), 3) if len(bot) else None))
    return pd.DataFrame(rows, columns=["lang", "topic", "human_accounts", "automated_accounts", "automated_share", "human_mood", "bot_mood"])


def mood_leadlag(ev: pd.DataFrame, groups: pd.Series, t0: float, lang: str, topic: str, max_lag: int = 8) -> dict:
    """Do bots change mood before humans? Hourly mood series for both, then the lag that best lines up
    bot changes with later human changes. Also: are bots in sync, and do they push against locals?"""
    posts = ev[ev.kind.isin(["post", "reply"]) & (ev.lang == lang) & (ev.topic == topic)].copy()
    posts["group"] = posts.account.map(groups).fillna("unknown")
    posts["mood"] = posts.text.map(mood_score)
    posts["hour"] = ((posts.ts - t0) // 3600).astype(int)
    H = int(posts.hour.max()) + 1 if len(posts) else 0
    h = posts[posts.group == "human"].groupby("hour").mood.mean().reindex(range(H)).interpolate(limit_direction="both")
    b = posts[posts.group == "automated"].groupby("hour").mood.mean().reindex(range(H)).interpolate(limit_direction="both")
    n_h, n_b = posts[posts.group == "human"].account.nunique(), posts[posts.group == "automated"].account.nunique()
    out = dict(lang=lang, topic=topic, human_accounts=int(n_h), automated_accounts=int(n_b),
               human_series=[None if pd.isna(v) else round(float(v), 3) for v in h],
               bot_series=[None if pd.isna(v) else round(float(v), 3) for v in b])
    if n_h < MIN_GROUP:
        out["verdict"] = "not published (too few human accounts)"; return out
    if n_b < 10 or b.isna().all():
        out["verdict"] = "clean"; out["why"] = "almost no automated accounts talk to this audience about this topic"; return out
    # smooth, then correlate bot changes with human changes k hours later
    hs, bs = h.rolling(5, center=True, min_periods=1).mean(), b.rolling(5, center=True, min_periods=1).mean()
    dh, db = hs.diff().fillna(0).values, bs.diff().fillna(0).values
    best_lag, best_r = 0, -1.0
    for k in range(0, max_lag + 1):
        a, c = db[: len(db) - k] if k else db, dh[k:]
        if len(a) > 12 and a.std() > 0 and c.std() > 0:
            r = float(np.corrcoef(a, c)[0, 1])
            if r > best_r:
                best_lag, best_r = k, r
    # when did each side first move by more than 0.3 from its starting mood?
    def first_turn(s, persist=4):
        """First hour where the mood has moved more than 0.3 from its opening level and stays moved."""
        base = s.iloc[:8].mean()
        moved = ((s - base).abs() > 0.3).values
        for i in range(len(moved) - persist + 1):
            if moved[i:i + persist].all():
                return i
        return None
    bt, ht = first_turn(bs), first_turn(hs)
    # sync: share of all bot posts on this topic that fall in the busiest 3-hour window
    counts = posts[posts.group == "automated"].groupby("hour").size().reindex(range(H), fill_value=0)
    sync = float(counts.rolling(3).sum().max() / max(1, counts.sum()))
    gap = float(bs.mean() - hs.mean())
    against = abs(gap) > 0.4 and np.sign(bs.mean()) != np.sign(hs.mean())
    out.update(best_lag_hours=best_lag, lag_correlation=round(best_r, 3), bot_first_turn_hour=bt, human_first_turn_hour=ht,
               sync_index=round(sync, 3), mood_gap=round(gap, 3))
    if bt is not None and ht is not None and 0 < ht - bt <= max_lag and best_r > 0.25:
        out["verdict"] = "steered"; out["why"] = f"bots turned at hour {bt}, humans followed {ht - bt} h later (lag correlation {best_r:.2f})"
    elif against:
        out["verdict"] = "against locals"; out["why"] = f"bots sit {abs(gap):.2f} away from the human mood on the other side of zero, and humans did not follow"
    elif bt is None and ht is None and abs(gap) < 0.25:
        out["verdict"] = "mirror"; out["why"] = "neither side turned, and bots sit within 0.25 of the human mood: they copy it"
    else:
        out["verdict"] = "unclear"; out["why"] = "some difference, but no clean lead-lag or opposition pattern"
    return out


# ----------------------------------------------------------------------------- where they push
def steering_flow(ev: pd.DataFrame, groups: pd.Series, tzs: pd.DataFrame, langs: pd.Series, topic: str, window: tuple[float, float] | None = None) -> dict:
    """For automated accounts on one topic: origin regions -> audience languages -> destinations."""
    posts = ev[ev.kind.isin(["post", "reply"]) & (ev.topic == topic)].copy()
    if window:
        posts = posts[(posts.ts >= window[0]) & (posts.ts <= window[1])]
    posts["group"] = posts.account.map(groups)
    bots = posts[posts.group == "automated"].copy()
    if bots.account.nunique() < MIN_GROUP:
        return dict(topic=topic, published=False, automated_accounts=int(bots.account.nunique()))
    tz = tzs.set_index("account")
    bots["region"] = bots.account.map(lambda a: _region(tz.tz.get(a)) if a in tz.index and tz.sleeps.get(a, False) else ("never sleeps" if a in tz.index else "unknown"))
    bots["audience"] = bots.account.map(langs).fillna("und")
    bots["mood"] = bots.text.map(mood_score)
    origin = bots.groupby("region").account.nunique().sort_values(ascending=False)
    audience = bots.groupby("audience").account.nunique().sort_values(ascending=False)
    o2a = bots.groupby(["region", "audience"]).account.nunique().reset_index(name="accounts")
    direction = bots.groupby("audience").mood.mean().round(2)
    # destinations: domains linked by automated accounts vs by humans, on this topic
    def domains(df):
        d = df.text.dropna().str.findall(URL).explode().dropna().map(lambda u: urlparse(u).netloc)
        return d.value_counts()
    bot_dom, hum_dom = domains(bots), domains(posts[posts.group == "human"])
    dest = [dict(domain=k, bot_links=int(v), human_links=int(hum_dom.get(k, 0))) for k, v in bot_dom.head(6).items()]
    # who they reply to: human accounts targeted, by audience language (counts only)
    replies = bots[(bots.kind == "reply") & bots.target.notna()]
    targeted = replies.groupby("audience").target.nunique().to_dict()
    return dict(topic=topic, published=True, automated_accounts=int(bots.account.nunique()),
                origin={k: int(v) for k, v in origin.items()}, audience={k: int(v) for k, v in audience.items()},
                origin_to_audience=o2a.to_dict(orient="records"), direction={k: float(v) for k, v in direction.items()},
                destinations=dest, humans_targeted_by_replies={k: int(v) for k, v in targeted.items()})
