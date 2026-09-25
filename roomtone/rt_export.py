"""Export every source's results into app/rt.js, the data file the Roomtone dashboard app reads.

    python -m roomtone.rt_export            # all sources found under data/
    python -m roomtone.rt_export bluesky    # one source only

The app merges sources by row position, so every source is aligned to the Bluesky (base) layout here:
same topics, same hours, same audience x topic rows, same region rows. Missing rows are filled with zeros.
"""
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from . import MIN_GROUP

DATA, APP = Path("data"), Path("app")
META = {
    "bluesky": dict(name="Bluesky", method="Jetstream firehose · free, no sign-up", collected="posts, replies, likes and deletes"),
    "mastodon": dict(name="Mastodon", method="Public timelines of large instances · streaming API", collected="posts, replies, favourites and deletes"),
    "reddit": dict(name="Reddit", method="Public comments · official API, non-commercial", collected="comments, replies, upvotes and deletes"),
    "youtube": dict(name="YouTube", method="Comments on top videos per topic · Data API", collected="comments, replies and likes"),
}


def dataset(source: str, H: int | None = None) -> dict:
    d = DATA / source
    r = json.loads((d / "results.json").read_text())
    ev = pd.read_parquet(d / "events_safe.parquet")
    sc = pd.read_parquet(d / "scores.parquet")
    groups = sc.set_index("account").group
    t0 = r["t0"]
    wb = pd.DataFrame(r["wasted_breath"]); tr = pd.DataFrame(r["trends"])
    topics = [t for t in sorted(ev.topic.dropna().unique()) if t != "other"] if "topic" in ev else []
    H = H or (int(wb.hour.max()) + 1 if len(wb) else max(1, int(r.get("hours", 1))))
    series = {t: [None] * H for t in topics}
    for _, x in wb.iterrows():
        if x.topic in series and 0 <= int(x.hour) < H:
            series[x.topic][int(x.hour)] = None if pd.isna(x.wasted_breath) else round(float(x.wasted_breath), 3)
    ghost = tr.groupby("hour").ghost_made.sum().reindex(range(H), fill_value=0).astype(int).tolist() if len(tr) else [0] * H
    # previous-day wasted breath
    eng = ev[ev.kind.isin(["reply", "like"]) & ev.target.notna()].copy()
    eng["fg"] = eng.account.map(groups); eng["tg"] = eng.target.map(groups); eng = eng[eng.fg == "human"]
    eng["hour"] = ((eng.ts - t0) // 3600).astype(int)
    prev = eng[(eng.hour >= eng.hour.max() - 47) & (eng.hour < eng.hour.max() - 23)]
    prev_wb = float((prev.tg == "automated").mean()) if len(prev) else (r["headline"]["wasted_breath_last_24h"] or 0.0)
    # trend peak: the hour where the official list is most automated
    posts = ev[ev.kind.isin(["post", "reply"])].copy(); posts["hour"] = ((posts.ts - t0) // 3600).astype(int); posts["grp"] = posts.account.map(groups).fillna("unknown")
    peak = int(tr.loc[tr.automated_share.fillna(0).idxmax()].hour) if len(tr) else 0
    ph = tr[tr.hour == peak].sort_values("official_rank") if len(tr) else tr
    official = [dict(topic=x.topic, share=round(float(x.automated_share or 0), 3), ghost=bool(x.ghost_made), posts=int(x.official_posts)) for _, x in ph.iterrows()]
    hp = posts[(posts.hour == peak) & (posts.grp == "human")].groupby("topic").agg(n=("account", "size"), ppl=("account", "nunique")) if len(posts) else pd.DataFrame(columns=["n", "ppl"])
    real = [t for t, row in hp.sort_values("n", ascending=False).iterrows() if t != "other" and row.ppl >= MIN_GROUP][:3]
    hd = r["headline"]
    hd["wasted_breath_last_24h"] = hd.get("wasted_breath_last_24h") or 0.0
    hd["one_in"] = hd.get("one_in") or 0
    for k in ("total", "human", "automated", "helper"):
        hd["accounts"][k] = int(hd["accounts"].get(k, 0))
    if not hd.get("peak_hour"):
        hd["peak_hour"] = dict(topic=topics[0] if topics else "none", hour=0, human_engagements=0, to_automated=0, n_humans=0, wasted_breath=0.0)
    langs = sorted(set(x["lang"] for x in r["audience_topics"])) or ["und"]
    out = dict(
        H=H, topics=topics, min_group=MIN_GROUP, generated_at=r["generated_at"], headline=r["headline"], prev_wb=round(prev_wb, 4),
        validation=r["validation"], series=series, ghost_by_hour=ghost, trend_peak=dict(hour=peak, official=official, real=real),
        immune=r["immune_response"], sleeper=r["sleeper_cells"], forecast=r["forecast"], regions=r["regions"],
        audience_topics=r["audience_topics"], leadlag=r["leadlag"], flow=r["flow"], privacy=r["privacy"], subs=r.get("subs", {}),
        key=source, name=META[source]["name"], live=not _is_practice(r), method=META[source]["method"],
        collected=META[source]["collected"], langs=" ".join(langs))
    return out


def _is_practice(r):
    return r["validation"].get("method") == "gradient boosting" and "timezone_within_2h" in r["validation"]


def align(base: dict, d: dict) -> dict:
    """Reindex d's row tables to base's layout so the app can merge them by position."""
    H, T = base["H"], base["topics"]
    d["H"] = H; d["topics"] = T
    d["series"] = {t: ((d["series"].get(t) or []) + [None] * H)[:H] for t in T}
    d["ghost_by_hour"] = (d["ghost_by_hour"] + [0] * H)[:H]
    at = {(x["lang"], x["topic"]): x for x in d["audience_topics"]}
    d["audience_topics"] = [at.get((b["lang"], b["topic"]), dict(lang=b["lang"], topic=b["topic"], human_accounts=0, automated_accounts=0, automated_share=0, human_mood=None, bot_mood=None)) for b in base["audience_topics"]]
    ll = {(x["lang"], x["topic"]): x for x in d["leadlag"]}
    d["leadlag"] = [ll.get((b["lang"], b["topic"]), dict(lang=b["lang"], topic=b["topic"], human_accounts=0, automated_accounts=0, human_series=[None] * (H - 1), bot_series=None, verdict="clean", why="no data from this source")) for b in base["leadlag"]]
    for x in d["leadlag"]:
        for k in ("human_series", "bot_series"):
            if x.get(k) is not None:
                x[k] = (x[k] + [None] * H)[:H - 1]
    ob = {(x["lang"], x["group"], x["region"]): x for x in d["regions"]["origin_by_audience"]}
    d["regions"]["origin_by_audience"] = [ob.get((b["lang"], b["group"], b["region"]), {**b, "accounts": 0, "share": 0}) for b in base["regions"]["origin_by_audience"]]
    mm = {(x["lang"], x["group"]): x for x in d["regions"]["mismatch"]}
    d["regions"]["mismatch"] = [mm.get((b["lang"], b["group"]), {**b, "accounts": 0, "mismatch_rate": 0, "never_sleeps_rate": 0}) for b in base["regions"]["mismatch"]]
    im = {x["topic"]: x for x in d["immune"]}
    d["immune"] = [im.get(b["topic"], dict(topic=b["topic"], spike=False)) for b in base["immune"]]
    bf, f = base["flow"], d["flow"] or {}
    if not f.get("published"):
        f = dict(topic=bf["topic"], published=False, automated_accounts=0, origin={}, audience={}, origin_to_audience=[], direction={}, destinations=[], humans_targeted_by_replies={})
    o2a = {(x["region"], x["audience"]): x for x in f.get("origin_to_audience", [])}
    f["origin_to_audience"] = [o2a.get((b["region"], b["audience"]), {**b, "accounts": 0}) for b in bf["origin_to_audience"]]
    ds = {x["domain"]: x for x in f.get("destinations", [])}
    f["destinations"] = [ds.get(b["domain"], {**b, "bot_links": 0, "human_links": 0}) for b in bf["destinations"]]
    f["humans_targeted_by_replies"] = {k: int(f.get("humans_targeted_by_replies", {}).get(k, 0)) for k in bf["humans_targeted_by_replies"]}
    f["direction"] = {k: f.get("direction", {}).get(k, 0) for k in bf["direction"]}
    d["flow"] = f
    d["forecast"] = {t: d["forecast"].get(t, base["forecast"].get(t)) for t in T}
    return d


def contagion(datasets: dict, topic: str) -> dict:
    """Which platform saw the campaign first? Per source, the first hour where the topic's wasted-breath
    share jumps to at least double that platform's own usual level (and at least 25%), then the lag of each
    other source behind the earliest one. Each platform is judged against its own baseline."""
    first = {}
    for k, d in datasets.items():
        ser = [v for v in (d["series"].get(topic) or [])]
        vals = sorted(v for v in ser if v is not None)
        base = vals[len(vals) // 2] if vals else 0
        thr = max(0.25, 2 * base)
        hrs = [h for h, v in enumerate(ser) if v is not None and v >= thr and (h + 1 < len(ser) and ser[h + 1] is not None and ser[h + 1] >= thr)]
        first[k] = hrs[0] if hrs else None
    seen = {k: v for k, v in first.items() if v is not None}
    if not seen:
        return dict(topic=topic, first=None, lags={}, sentence=f"No platform saw a majority-automated hour on #{topic}.")
    lead = min(seen, key=seen.get)
    lags = {k: v - seen[lead] for k, v in sorted(seen.items(), key=lambda kv: kv[1])}
    later = [f"{META[k]['name']} {lag} h later" for k, lag in lags.items() if k != lead]
    missing = [META[k]["name"] for k, v in first.items() if v is None]
    sent = f"Contagion clock: the #{topic} push hit {META[lead]['name']} first" + (", then " + ", ".join(later) if later else "") + "." + (f" Not seen on {', '.join(missing)}." if missing else "")
    return dict(topic=topic, first=lead, first_hour=seen[lead], lags=lags, sentence=sent)


def combined(base: dict, datasets: dict) -> dict:
    """The 'all sources' dataset, computed here so it exists as a real, exportable result and not only in
    the browser: engagement-weighted averages for shares, sums for counts, best case for campaigns."""
    L = list(datasets.values())
    w = [d["headline"]["human_engagements_last_24h"] for d in L]; eng = sum(w) or 1
    T, H = base["topics"], base["H"]
    def wavg(vals):
        n = sum(wi * v for wi, v in zip(w, vals) if v is not None); dd = sum(wi for wi, v in zip(w, vals) if v is not None)
        return round(n / dd, 3) if dd else None
    out = json.loads(json.dumps(base))
    out.update(key="all", name="All sources", live=any(d["live"] for d in L), method="every source, same gate, same score", collected="everything the sources collect",
               langs=" ".join(sorted(set(" ".join(d["langs"] for d in L).split()))))
    out["series"] = {t: [wavg([d["series"][t][h] for d in L]) for h in range(H)] for t in T}
    out["ghost_by_hour"] = [sum(d["ghost_by_hour"][h] for d in L) for h in range(H)]
    hd = out["headline"]
    hd["human_engagements_last_24h"] = sum(w); hd["to_automated_last_24h"] = sum(d["headline"]["to_automated_last_24h"] for d in L)
    hd["wasted_breath_last_24h"] = round(hd["to_automated_last_24h"] / eng, 4) if sum(w) else 0.0
    hd["one_in"] = int(round(1 / hd["wasted_breath_last_24h"])) if hd["wasted_breath_last_24h"] > 0 else 0
    for k in ("total", "human", "automated", "helper"):
        hd["accounts"][k] = sum(d["headline"]["accounts"].get(k, 0) for d in L)
    hd["ghost_made_trends"] = sum(d["headline"]["ghost_made_trends"] for d in L); hd["official_trend_slots"] = sum(d["headline"]["official_trend_slots"] for d in L)
    out["prev_wb"] = round(sum(d["prev_wb"] * wi for d, wi in zip(L, w)) / eng, 4)
    v = out["validation"]; nt = sum(d["validation"].get("n_test", 0) for d in L) or 1
    v["importance"] = v.get("importance") or {}
    for k in ("precision_at_threshold", "recall_at_threshold", "false_alarm_rate", "auc"):
        v[k] = round(sum(d["validation"].get(k, 0) * d["validation"].get("n_test", 0) for d in L) / nt, 4)
    v["n_test"] = nt; v["n_train"] = sum(d["validation"].get("n_train", 0) for d in L)
    out["sleeper"] = sorted([c for d in L for c in d["sleeper"]], key=lambda c: -c["accounts"])
    out["subs"] = {t: base["subs"].get(t, []) for t in T}
    gallery = []
    for t in T:  # example posts from every source, most-engaged first; each tagged with its platform
        for i, sub in enumerate(out["subs"][t]):
            ex = []
            for d in L:
                subs_t = d["subs"].get(t, [])
                if i < len(subs_t):
                    for e in subs_t[i].get("ex", []):
                        e = list(e[:8]) + [d["name"], t, sub["name"]]
                        ex.append(e)
            ex = sorted(ex, key=lambda e: -(e[5] + e[6]))
            sub["ex"] = ex[:3]
            gallery += ex[:2]
    out["gallery"] = sorted(gallery, key=lambda e: -(e[5] + e[6]))[:24]
    out["contagion"] = contagion(datasets, base["flow"]["topic"]) if T else dict(topic=None, sentence="No topic data yet.")
    out["extra_changes"] = [out["contagion"]["sentence"]]
    return out


def main(sources=None):
    sources = sources or [p.name for p in DATA.iterdir() if (p / "results.json").exists()]
    if "bluesky" not in sources:
        raise SystemExit("bluesky is the base dataset and must be present")
    base = dataset("bluesky")
    others = {s: align(base, dataset(s, base["H"])) for s in sources if s != "bluesky"}
    datasets = {"bluesky": base, **others}
    for k, d in datasets.items():
        d["practice"] = not d["live"]
    allsrc = combined(base, datasets)
    rt = dict(allsrc, sources={**datasets, "all": allsrc})
    APP.mkdir(exist_ok=True)
    (APP / "rt.js").write_text("window.RT=" + json.dumps(rt, default=_json) + ";")
    (DATA / "all_sources.json").write_text(json.dumps(allsrc, default=_json))
    print("wrote app/rt.js and data/all_sources.json; sources:", ", ".join(datasets), "|", allsrc["contagion"]["sentence"])


def _json(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, float) and np.isnan(o): return None
    raise TypeError(str(type(o)))


if __name__ == "__main__":
    main(sys.argv[1:] or None)
