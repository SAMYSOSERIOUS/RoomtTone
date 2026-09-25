"""Run everything: privacy gate -> features -> score -> metrics -> forecast -> results.json"""
import json, time
from pathlib import Path
import numpy as np
import pandas as pd
from . import MIN_GROUP, AUTOMATED_THRESHOLD
from .privacy import gate, purge, pseudonym
from .features import account_features
from .score import train_and_score
from .metrics import wasted_breath, real_trending, immune_response, sleeper_cells
from .forecast import hourly_share, forecast_next_day
from .steering import infer_timezone, audience_language, origin_vs_audience, audience_topic_table, mood_leadlag, steering_flow
from .subtopics import subtopics

DATA = Path("data")


def run(source: str = "bluesky"):
    d = DATA / source
    events_path, official_path, out = d / "events.parquet", d / "official_trends.parquet", d / "results.json"
    raw = pd.read_parquet(events_path)
    official = pd.read_parquet(official_path)
    t0 = float(raw.ts.min())
    if "created_at" in raw:
        t0 = float(raw.loc[raw.kind != "account_created", "ts"].min())

    # practice-mode ground truth (a real run uses hand-checked labels instead)
    truth = None
    if raw.account.str.startswith("did:plc:").all() and raw.account.str[8].isin(list("hbsz")).all():
        truth = raw.drop_duplicates("account").set_index("account").index.to_series().map(
            lambda a: 1 if a[8] in "bz" else 0)
        truth.index = truth.index.map(pseudonym)

    # 1. privacy gate: nothing below this line ever sees a real account name
    ev = purge(gate(raw))
    ev.to_parquet(d / "events_safe.parquet", index=False)

    # 2. habits and score
    feat = account_features(ev)
    labels = truth.reindex(feat.account).fillna(0).astype(int).reset_index(drop=True) if truth is not None else None
    feat = feat.reset_index(drop=True)
    scored, report = train_and_score(feat, labels, AUTOMATED_THRESHOLD)
    scored.to_parquet(d / "scores.parquet", index=False)
    groups = scored.set_index("account").group

    # 3. metrics
    wb = wasted_breath(ev, groups, t0)
    trends = real_trending(ev, groups, official, t0)
    topics = sorted(ev.topic.dropna().unique()) if "topic" in ev else []
    immune = [immune_response(wb, t) for t in topics if t != "other"]
    cells = sleeper_cells(scored)

    # 4. forecast
    share = hourly_share(ev, groups, t0)
    fc = {t: forecast_next_day(share, t) for t in topics if t != "other"}

    # 4b. regions, audiences, steering
    tzs = infer_timezone(ev)
    if truth is not None and "tz" in raw:  # practice mode: how good is the time zone estimate?
        tt = raw[raw.kind == "account_created"]
        true_tz = pd.Series(tt.tz.values, index=tt.account.map(pseudonym))
        chk = tzs[tzs.sleeps].set_index("account").tz.to_frame().join(true_tz.rename("true")).dropna()
        report["timezone_within_2h"] = round(float(((chk.tz - chk.true).abs() <= 2).mean()), 3)
        report["timezone_accounts_checked"] = int(len(chk))
    langs = audience_language(ev)
    origin_table, mismatch = origin_vs_audience(tzs, langs, groups)
    at_table = audience_topic_table(ev, groups, t0)
    leadlag = [mood_leadlag(ev, groups, t0, l, t) for l, t in at_table[["lang", "topic"]].itertuples(index=False)]
    hot_topic = at_table.sort_values("automated_share", ascending=False).topic.iloc[0] if len(at_table) else None
    flow = steering_flow(ev, groups, tzs, langs, hot_topic) if hot_topic else None

    subs = subtopics(ev, scored, t0, practice=truth is not None)

    # 5. headline numbers (last full day)
    last_day = wb[wb.hour >= wb.hour.max() - 23]
    eng, to_auto = last_day.human_engagements.sum(), last_day.to_automated.sum()
    headline = dict(
        human_engagements_last_24h=int(eng),
        to_automated_last_24h=int(to_auto),
        wasted_breath_last_24h=round(float(to_auto / eng), 4) if eng else None,
        one_in=int(round(eng / to_auto)) if to_auto else None,
        peak_hour=last_day.loc[last_day.wasted_breath.idxmax()].to_dict() if last_day.wasted_breath.notna().any() else None,
        accounts=dict(total=int(len(scored)), **{k: int(v) for k, v in scored.group.value_counts().items()}),
        ghost_made_trends=int(trends.ghost_made.sum()), official_trend_slots=int(len(trends)),
    )
    results = dict(generated_at=time.time(), t0=t0, hours=int(wb.hour.max()) + 1 if len(wb) else 0, min_group=MIN_GROUP,
                   headline=headline, validation=report,
                   wasted_breath=wb.round(4).replace({np.nan: None}).to_dict(orient="records"),
                   trends=trends.round(4).replace({np.nan: None}).to_dict(orient="records"),
                   immune_response=immune, sleeper_cells=cells, forecast=fc,
                   regions=dict(origin_by_audience=origin_table.to_dict(orient="records"), mismatch=mismatch.to_dict(orient="records")),
                   audience_topics=at_table.replace({np.nan: None}).to_dict(orient="records"), leadlag=leadlag, flow=flow, subs=subs, source=source,
                   privacy=dict(pseudonymized=True, text_retention_days=30, feature_retention_days=90,
                                accounts_named=0, individual_lookup=False))
    out.write_text(json.dumps(results, indent=1, default=float))
    print(json.dumps(dict(headline=headline, validation=report, immune=immune, sleeper_cells=cells, mismatch=mismatch.to_dict(orient='records'), verdicts=[(x['lang'], x['topic'], x.get('verdict'), x.get('why')) for x in leadlag], flow=flow), indent=1, default=float))
    return results


if __name__ == "__main__":
    import sys
    for src in (sys.argv[1:] or ["bluesky"]):
        print(f"== {src}")
        run(src)
