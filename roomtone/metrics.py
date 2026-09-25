"""The measurements that make Roomtone different.

Wasted Breath Index  = share of human replies + likes that landed on automated-looking accounts
Real trending list   = the official hourly top list vs the same list with automated accounts removed
Immune response time = hours until human engagement with a ghost-made trend falls back to normal
All results are group totals; nothing here names an account.
"""
import numpy as np
import pandas as pd
from . import MIN_GROUP


def wasted_breath(ev: pd.DataFrame, groups: pd.Series, t0: float) -> pd.DataFrame:
    """Per topic and hour: human engagement that went to automated-looking accounts."""
    eng = ev[ev.kind.isin(["reply", "like"]) & ev.target.notna()].copy()
    eng["from_group"] = eng.account.map(groups).fillna("unknown")
    eng["to_group"] = eng.target.map(groups).fillna("unknown")
    eng = eng[eng.from_group == "human"]
    cols = ["topic", "hour", "human_engagements", "to_automated", "n_humans", "wasted_breath"]
    if eng.empty or "topic" not in eng:
        return pd.DataFrame(columns=cols)
    eng["hour"] = ((eng.ts - t0) // 3600).astype(int)
    g = eng.groupby(["topic", "hour"])
    out = g.size().rename("human_engagements").to_frame()
    out["to_automated"] = g.apply(lambda x: (x.to_group == "automated").sum())
    out["n_humans"] = g.account.nunique()
    out["wasted_breath"] = out.to_automated / out.human_engagements
    out = out.reset_index()
    out.loc[out.n_humans < MIN_GROUP, "wasted_breath"] = np.nan  # too small a group to publish
    return out


def real_trending(ev: pd.DataFrame, groups: pd.Series, official: pd.DataFrame, t0: float, top: int = 3) -> pd.DataFrame:
    """Official top list per hour next to the list with automated accounts removed."""
    posts = ev[ev.kind.isin(["post", "reply"])].copy()
    posts["group"] = posts.account.map(groups).fillna("unknown")
    posts["hour"] = ((posts.ts - t0) // 3600).astype(int)
    clean = posts[posts.group == "human"]
    real = (clean.groupby(["hour", "topic"]).size().rename("posts").reset_index()
            .sort_values(["hour", "posts"], ascending=[True, False]).groupby("hour").head(top))
    real["rank"] = real.groupby("hour").cumcount() + 1
    off = official.rename(columns={"posts": "official_posts", "rank": "official_rank"})
    if off.empty or posts.empty:
        return pd.DataFrame(columns=["hour", "topic", "official_posts", "official_rank", "real_rank", "automated_share", "ghost_made", "displaced"])
    merged = off.merge(real[["hour", "topic", "rank"]].rename(columns={"rank": "real_rank"}), on=["hour", "topic"], how="left")
    share = posts.groupby(["hour", "topic"]).group.apply(lambda s: (s == "automated").mean()).rename("automated_share")
    merged = merged.merge(share.reset_index(), on=["hour", "topic"], how="left")
    # ghost-made: most of the posts behind this trend slot came from automated-looking accounts
    merged["ghost_made"] = merged.automated_share.fillna(0) >= 0.5
    merged["displaced"] = merged.real_rank.isna()  # fell off the ghost-free list (rank shift or ghosts)
    return merged


def immune_response(wb: pd.DataFrame, topic: str, spike_threshold: float = 0.25) -> dict:
    """Hours from the first hour the wasted-breath share passes the threshold until it falls back under it."""
    s = wb[wb.topic == topic].sort_values("hour")
    hot = s[s.wasted_breath >= spike_threshold]
    if hot.empty:
        return dict(topic=topic, spike=False)
    start = int(hot.hour.iloc[0])
    after = s[(s.hour > start) & (s.wasted_breath < spike_threshold)]
    end = int(after.hour.iloc[0]) if not after.empty else int(s.hour.iloc[-1])
    return dict(topic=topic, spike=True, start_hour=start, hours_until_recovery=end - start,
                peak=round(float(hot.wasted_breath.max()), 3))


def sleeper_cells(feat: pd.DataFrame, min_batch: int = 30) -> list[dict]:
    """Creation days that produced unusually many accounts which later behave alike."""
    if "created_at" not in feat or feat.created_at.isna().all():
        return []
    f = feat.dropna(subset=["created_at"]).copy()
    f["day"] = (f.created_at // 86400).astype(int)
    counts = f.groupby("day").size()
    typical = counts.median()
    out = []
    for day, n in counts[counts >= max(min_batch, 5 * typical)].items():
        batch = f[f.day == day]
        out.append(dict(created_day_index=int(day), accounts=int(n), typical_per_day=float(typical),
                        share_automated=round(float((batch.group == "automated").mean()), 3) if "group" in batch else None))
    return out
