"""Streamlit dashboard. Group totals only; no account is ever shown.  Run: streamlit run roomtone/dashboard.py"""
import json
from pathlib import Path
import pandas as pd
import streamlit as st

r = json.loads(Path("data/results.json").read_text())
h = r["headline"]
st.set_page_config(page_title="Roomtone", layout="wide")
st.title("Roomtone")
st.caption("How much human attention goes to machines, and can we give it back? Practice data unless you ran a live collection.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Human replies and likes that went to machines (last 24 h)", f"1 in {h['one_in']}" if h["one_in"] else "n/a",
          f"{h['wasted_breath_last_24h']*100:.1f}%" if h["wasted_breath_last_24h"] else None)
c2.metric("Trend slots that were ghost-made", f"{h['ghost_made_trends']} of {h['official_trend_slots']}")
c3.metric("Accounts scored", h["accounts"]["total"], f"{h['accounts'].get('automated',0)} automated-looking, {h['accounts'].get('helper',0)} declared helpers")
v = r["validation"]
c4.metric("False-alarm rate (published)", f"{v.get('false_alarm_rate', 0)*100:.2f}%" if "false_alarm_rate" in v else "not validated",
          f"precision {v.get('precision_at_threshold','-')}")

st.subheader("Wasted Breath Index by topic and hour")
wb = pd.DataFrame(r["wasted_breath"])
st.line_chart(wb.pivot(index="hour", columns="topic", values="wasted_breath"))

st.subheader("What's really trending")
tr = pd.DataFrame(r["trends"])
last = tr[tr.hour == tr.hour.max()]
col1, col2 = st.columns(2)
col1.write("**Official list (looks popular)**"); col1.table(last[["official_rank", "topic", "automated_share"]].rename(columns={"automated_share": "automated share"}))
col2.write("**Ghost-free list (actually popular)**"); col2.table(last.dropna(subset=["real_rank"]).sort_values("real_rank")[["real_rank", "topic"]])

st.subheader("Immune response")
st.table(pd.DataFrame(r["immune_response"]))

st.subheader("Ghost forecast, next 24 hours")
fc = {t: f for t, f in r["forecast"].items() if f.get("ok")}
if fc:
    pick = st.selectbox("Topic", list(fc))
    f = fc[pick]
    st.line_chart(pd.DataFrame(dict(low=f["low"], forecast=f["next_24h"], high=f["high"])))
    g = f["grade"]
    st.caption(f"Skill vs 'tomorrow = today': {g['skill_vs_naive']} (publishable: {g['publishable']})")

st.subheader("Privacy")
st.json(r["privacy"])
