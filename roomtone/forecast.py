"""Ghost forecast: tomorrow's automated share per topic, graded against the dumbest possible guess.

A forecast that cannot beat "tomorrow looks like today" is not published. The grade is recomputed
every day and shown next to the forecast, like a weather service's own accuracy page.
"""
import numpy as np
import pandas as pd


def hourly_share(ev: pd.DataFrame, groups: pd.Series, t0: float) -> pd.DataFrame:
    posts = ev[ev.kind.isin(["post", "reply"])].copy()
    posts["group"] = posts.account.map(groups).fillna("unknown")
    posts["hour"] = ((posts.ts - t0) // 3600).astype(int)
    return posts.groupby(["topic", "hour"]).group.apply(lambda s: (s == "automated").mean()).rename("share").reset_index()


def forecast_next_day(share: pd.DataFrame, topic: str, horizon: int = 24) -> dict:
    """Seasonal-naive with trend: same hour yesterday, nudged by the last-day trend, with an error band
    from the observed hour-to-hour noise. Simple on purpose: it must be explainable and beatable."""
    s = share[share.topic == topic].sort_values("hour").set_index("hour").share
    if len(s) < 48:
        return dict(topic=topic, ok=False, note="need at least 48 hours of history")
    last = s.iloc[-24:].values
    prev = s.iloc[-48:-24].values
    trend = float(np.clip(last.mean() - prev.mean(), -0.2, 0.2))
    pred = np.clip(last + 0.5 * trend, 0, 1)
    noise = float(np.nanstd(last - prev))
    # grade yesterday's forecast the same way, against "same as the day before"
    if len(s) >= 72:
        older = s.iloc[-72:-48].values
        fc_yesterday = np.clip(prev + 0.5 * float(np.clip(prev.mean() - older.mean(), -0.2, 0.2)), 0, 1)
        err_model = float(np.mean(np.abs(fc_yesterday - last)))
        err_naive = float(np.mean(np.abs(prev - last)))
        skill = 1 - err_model / err_naive if err_naive > 0 else 0.0
    else:
        err_model = err_naive = skill = None
    return dict(topic=topic, ok=True, next_24h=[round(float(x), 3) for x in pred],
                low=[round(float(max(0, x - noise)), 3) for x in pred], high=[round(float(min(1, x + noise)), 3) for x in pred],
                grade=dict(mean_error_model=err_model, mean_error_naive=err_naive,
                           skill_vs_naive=None if skill is None else round(skill, 3),
                           publishable=bool(skill is not None and skill > 0.1)))
