"""Build report/roomtone.html from data/results.json. Run after the pipeline:  python report/build_report.py"""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
r = json.loads((ROOT / "data/bluesky/results.json").read_text())
ev = pd.read_parquet(ROOT / "data/bluesky/events_safe.parquet")
sc = pd.read_parquet(ROOT / "data/bluesky/scores.parquet")
groups = sc.set_index("account").group
t0 = r["t0"]
wb = pd.DataFrame(r["wasted_breath"]); tr = pd.DataFrame(r["trends"])
topics = [t for t in sorted(wb.topic.unique()) if t != "other"]
H = int(wb.hour.max()) + 1
series = {t: [None] * H for t in topics}
for _, x in wb.iterrows():
    if x.topic in series:
        series[x.topic][int(x.hour)] = None if pd.isna(x.wasted_breath) else round(float(x.wasted_breath), 3)
peak_hour = int(tr.loc[tr.automated_share.fillna(0).idxmax()].hour)
ph = tr[tr.hour == peak_hour].sort_values("official_rank")
peak_official = [dict(topic=x.topic, share=round(float(x.automated_share or 0), 3), ghost=bool(x.ghost_made)) for _, x in ph.iterrows()]
p = ev[ev.kind.isin(["post", "reply"])].copy(); p["hour"] = ((p.ts - t0) // 3600).astype(int); p["grp"] = p.account.map(groups).fillna("unknown")
hp = p[(p.hour == peak_hour) & (p.grp == "human")].groupby("topic").size().sort_values(ascending=False)
peak_real = [t for t in hp.index if t != "other"][:3]
ghost_by_hour = tr.groupby("hour").ghost_made.sum().reindex(range(H), fill_value=0).astype(int).tolist()
# per-audience wasted breath, last 24 h
eng = ev[ev.kind.isin(["reply", "like"]) & ev.target.notna()].copy()
eng["fg"] = eng.account.map(groups); eng["tg"] = eng.target.map(groups); eng = eng[eng.fg == "human"]
eng["hour"] = ((eng.ts - t0) // 3600).astype(int); last = eng[eng.hour >= eng.hour.max() - 23]
wb_lang = {k: dict(share=round(float((x.tg == "automated").mean()), 3), humans=int(x.account.nunique())) for k, x in last.groupby("lang")}
langs = sorted(wb_lang)
LANG = {"de": "German", "en": "English", "es": "Spanish", "fr": "French"}
# audience x topic grid + verdicts
at = {(x["lang"], x["topic"]): x for x in r["audience_topics"]}
ll = {(x["lang"], x["topic"]): x for x in r["leadlag"]}
grid = [dict(lang=l, topic=t, share=at.get((l, t), {}).get("automated_share"), verdict=ll.get((l, t), {}).get("verdict", "n/a"),
             why=ll.get((l, t), {}).get("why", ""), human_mood=at.get((l, t), {}).get("human_mood"), bot_mood=at.get((l, t), {}).get("bot_mood"),
             humans=at.get((l, t), {}).get("human_accounts"), bots=at.get((l, t), {}).get("automated_accounts")) for l in langs for t in topics]
hot = r["flow"]["topic"]
mood = {l: dict(human=ll[(l, hot)]["human_series"], bot=ll[(l, hot)]["bot_series"], verdict=ll[(l, hot)].get("verdict"), why=ll[(l, hot)].get("why", ""),
                bt=ll[(l, hot)].get("bot_first_turn_hour"), ht=ll[(l, hot)].get("human_first_turn_hour")) for l in langs if (l, hot) in ll}
# origin regions: humans vs automated per audience
ob = pd.DataFrame(r["regions"]["origin_by_audience"])
regions = ["never sleeps", "Americas", "Europe/Africa west", "East Europe/Middle East", "South/Central Asia", "East Asia/Pacific"]
origin = {l: {gname: {reg: float(ob[(ob.lang == l) & (ob.group == gname) & (ob.region == reg)].share.sum()) for reg in regions}
              for gname in ["human", "automated"]} for l in langs}
mism = {(x["lang"], x["group"]): x for x in r["regions"]["mismatch"]}
h = r["headline"]; v = r["validation"]; imm = [i for i in r["immune_response"] if i.get("spike")]
imm_h = imm[0]["hours_until_recovery"] if imm else "–"
cell = r["sleeper_cells"][0] if r["sleeper_cells"] else dict(accounts=0, typical_per_day=0)
fc = r["forecast"].get(hot, {}); grade = fc.get("grade") or {}
# smoothed mood lines (3-hour centred average) for readability; raw values stay in results.json
def smooth(a):
    ser = pd.Series([None if v is None else float(v) for v in a], dtype="float")
    return [None if pd.isna(v) else round(float(v), 3) for v in ser.rolling(3, center=True, min_periods=1).mean()]
for l in mood:
    mood[l]["human"], mood[l]["bot"] = smooth(mood[l]["human"]), smooth(mood[l]["bot"])
# rule-based narration: what changed in the last 24 h vs the 24 h before (no language model involved)
changes = []
prev = eng[(eng.hour >= eng.hour.max() - 47) & (eng.hour < eng.hour.max() - 23)]
wb_prev = {k: float((x.tg == "automated").mean()) for k, x in prev.groupby("lang")}
for l in langs:
    now, before = wb_lang[l]["share"], wb_prev.get(l)
    if before is None:
        continue
    d = now - before
    word = "rose" if d > 0.03 else "fell" if d < -0.03 else "held steady"
    changes.append(f"{LANG[l]} audience: the share of human replies going to machines {word}" + (f" from {before*100:.0f}% to {now*100:.0f}%." if word != "held steady" else f" at about {now*100:.0f}%."))
gm_now, gm_prev = sum(ghost_by_hour[-24:]), sum(ghost_by_hour[-48:-24])
changes.append(f"Ghost-made trend slots: {gm_now} in the last 24 h, {gm_prev} in the 24 h before." + (" The push is over." if gm_now < gm_prev else ""))
for x in r["leadlag"]:
    if x.get("verdict") in ("steered", "against locals"):
        changes.append(f"{LANG.get(x['lang'], x['lang'])} audience on {x['topic']}: {x['verdict']}. {x.get('why', '')}")
if r["sleeper_cells"]:
    changes.append(f"A batch of {cell['accounts']} accounts created on one day woke up together; all scored automated-looking.")
if not grade.get("publishable"):
    changes.append("The ghost forecast did not beat the simple guess this run and stays unpublished.")
hot_audience = max(langs, key=lambda l: wb_lang[l]["share"])
D = dict(changes=changes, hot_audience=hot_audience, one_in_prev=(int(round(1 / max(sum(wb_prev.values()) / len(wb_prev), 0.001))) if wb_prev else None), H=H, topics=topics, langs=langs, LANG=LANG, series=series, peak_official=peak_official, peak_real=peak_real, ghost_by_hour=ghost_by_hour,
         validation=r["validation"], wb_lang=wb_lang, grid=grid, hot=hot, mood=mood, origin=origin, regions=regions,
         mism={f"{k[0]}|{k[1]}": v for k, v in mism.items()}, flow=r["flow"])
rep = {"__ONE_IN__": str(h["one_in"]), "__TO_AUTO__": f"{h['to_automated_last_24h']:,}", "__ENG__": f"{h['human_engagements_last_24h']:,}",
       "__GHOST__": str(h["ghost_made_trends"]), "__SLOTS__": str(h["official_trend_slots"]), "__IMM__": str(imm_h),
       "__NAUTO__": str(h["accounts"].get("automated", 0)), "__NTOT__": f"{h['accounts']['total']:,}", "__NHELP__": str(h["accounts"].get("helper", 0)),
       "__FAR__": f"{v.get('false_alarm_rate', 0) * 100:.2f}", "__PEAK__": str(peak_hour), "__SKILL__": str(grade.get("skill_vs_naive")),
       "__PUB__": "published" if grade.get("publishable") else "not published", "__CELL__": str(cell["accounts"]), "__TYP__": str(int(cell["typical_per_day"])),
       "__NTEST__": str(v.get("n_test", "–")), "__PREC__": f"{v.get('precision_at_threshold', 0) * 100:.1f}%", "__REC__": f"{v.get('recall_at_threshold', 0) * 100:.1f}%",
       "__TZACC__": f"{v.get('timezone_within_2h', 0) * 100:.0f}%", "__TZN__": f"{v.get('timezone_accounts_checked', 0):,}", "__HOT__": hot,
       "__NEV__": f"{len(ev):,}", "__DATA__": json.dumps(D)}
html = (ROOT / "report/template.html").read_text()
for k, val in rep.items():
    html = html.replace(k, val)
(ROOT / "report/roomtone.html").write_text(html)
print("wrote report/roomtone.html", len(html))
