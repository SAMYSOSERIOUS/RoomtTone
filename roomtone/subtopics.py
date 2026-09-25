"""Sub-topics inside each topic, with the share of human attention each one lost, and example posts.

Sub-topics come from a keyword map on the practice stream; on real data, run BERTopic over the topic's
posts once and write its labels into SUBTOPIC_KEYWORDS (see README).

Example posts are the one place text leaves the pipeline, so the privacy rules are strict:
  - only posts by accounts scoring >= 0.9 automated-looking, never by human-looking accounts
  - on real data, only texts that at least 3 different accounts posted (copy-paste campaigns);
    a sentence one person wrote once never appears
  - no name, handle, avatar or link to the post; the account's pseudonym is not shown either
  - stock phrases are marked with [[ ]] so the reader sees *why* it was flagged
"""
import re
import numpy as np
import pandas as pd
from .features import AI_PHRASES
from .steering import URL
from .redact import redact
from . import MIN_GROUP

SUBTOPIC_KEYWORDS = {
    "election": ["mail-in voting", "candidate debate", "polling numbers", "turnout drives", "fraud claims"],
    "climate": ["heatwave", "carbon tax", "electric cars", "protests"],
    "football": ["match night", "transfer rumours", "referees", "betting tips"],
    "housing": ["rents", "interest rates", "empty flats"],
    "ai": ["jobs", "regulation", "creativity"],
}
PHRASE_RE = re.compile("(" + "|".join(re.escape(p) for p in AI_PHRASES) + ")", re.I)
TITLE = {"mail-in voting": "Mail-in voting", "candidate debate": "Candidate debate", "polling numbers": "Polling numbers",
         "turnout drives": "Turnout drives", "fraud claims": "Fraud claims", "heatwave": "Heatwave", "carbon tax": "Carbon tax",
         "electric cars": "Electric cars", "protests": "Protests", "match night": "Match night", "transfer rumours": "Transfer rumours",
         "referees": "Referees", "betting tips": "Betting tips", "rents": "Rents", "interest rates": "Interest rates",
         "empty flats": "Empty flats", "jobs": "Jobs", "regulation": "Regulation", "creativity": "Creativity"}


def subtopics(ev: pd.DataFrame, scored: pd.DataFrame, t0: float, practice: bool) -> dict:
    groups = scored.set_index("account").group
    score = scored.set_index("account").score
    feats = scored.set_index("account")
    posts = ev[ev.kind.isin(["post", "reply"]) & ev.text.notna()].copy()
    posts["group"] = posts.account.map(groups).fillna("unknown")
    posts["hour"] = ((posts.ts - t0) // 3600).astype(int)
    eng = ev[ev.kind.isin(["reply", "like"]) & ev.target.notna()].copy()
    eng["fg"] = eng.account.map(groups); eng["tg"] = eng.target.map(groups)
    eng = eng[eng.fg == "human"]
    # engagement each post received from people (for the example cards)
    reply_to = ev[(ev.kind == "reply") & ev.target.notna()].groupby("target").size()
    like_to = ev[(ev.kind == "like") & ev.target.notna()].groupby("target").size()
    text_accounts = posts.groupby("text").account.nunique()
    out = {}
    for topic, keys in SUBTOPIC_KEYWORDS.items():
        tp = posts[posts.topic == topic]
        if tp.empty:
            continue
        hum_all = tp[tp.group == "human"]
        topic_wb = _wb(eng[eng.topic == topic]) if "topic" in eng else None
        rows = []
        for k in keys:
            m = tp.text.str.contains(k, case=False, regex=False)
            sp = tp[m]
            hum = sp[sp.group == "human"]
            ppl = int(hum.account.nunique())
            w = len(hum) / max(1, len(hum_all))
            # attention lost inside the sub-topic: human engagement on posts of this sub-topic that went to automated accounts
            sub_uris = set(sp.uri.dropna())
            e = eng[eng.topic == topic] if "topic" in eng else eng.iloc[0:0]
            targets_auto = sp[sp.group == "automated"].account.unique()
            e_sub = e[e.target.isin(sp.account.unique())]
            wb = float((e_sub.tg == "automated").mean()) if len(e_sub) else None
            mult = (wb / topic_wb) if (wb is not None and topic_wb) else 1.0
            rows.append(dict(name=TITLE.get(k, k), w=round(w, 3), m=round(float(mult), 2), ppl=ppl,
                             ex=_examples(sp, score, feats, text_accounts, reply_to, like_to, t0, practice)))
        out[topic] = rows
    return out


def _wb(e):
    return float((e.tg == "automated").mean()) if len(e) else None


def _examples(sp, score, feats, text_accounts, reply_to, like_to, t0, practice, n=2):
    cand = sp[(sp.group == "automated") & (sp.account.map(score).fillna(0) >= 0.9)].copy()
    if not practice:
        cand = cand[cand.text.map(text_accounts).fillna(0) >= 3]
    if cand.empty:
        return []
    cand["reach"] = cand.account.map(reply_to).fillna(0) + cand.account.map(like_to).fillna(0)
    cand["redacted"] = cand.text.map(lambda t: redact(t) != URL.sub(lambda m: m.group(0).split("//")[-1].split("/")[0], t))
    # one example that needed redaction comes first, so the black-bar rule is visible; then the most-engaged posts
    cand = cand.sort_values(["redacted", "reach"], ascending=[False, False]).drop_duplicates("account").head(n)
    out = []
    for _, r in cand.iterrows():
        f = feats.loc[r.account] if r.account in feats.index else None
        text = PHRASE_RE.sub(r"[[\1]]", redact(r.text))  # personal details become black bars; links keep the domain only
        signals = []
        nph = len(PHRASE_RE.findall(r.text))
        if nph:
            signals.append("stock phrase" + (f" ×{nph}" if nph > 1 else ""))
        doms = [u.split("//")[-1].split("/")[0] for u in URL.findall(r.text)]
        if doms:
            signals.append("links " + doms[0])
        same = int(text_accounts.get(r.text, 1))
        if same >= 3:
            signals.append(f"same text on {same} accounts")
        if f is not None:
            if f.rhythm_cv < 0.1:
                signals.append("posts on the hour")
            if f.sleep_gap_h < 2:
                signals.append("never sleeps")
            if f.signup_wave >= 30:
                signals.append("sign-up wave")
            if f.posts_per_day >= 100:
                signals.append(f"{int(f.posts_per_day)} posts a day")
            if pd.notna(f.created_at) and (r.ts - f.created_at) < 7 * 86400:
                signals.append(f"account {max(1, int((r.ts - f.created_at) // 86400))} days old")
        out.append([text, None, signals[:3] or ["automated-looking score"], round(float(score.get(r.account, 0)), 2),
                    int((r.ts - t0) // 3600), int(reply_to.get(r.account, 0)), int(like_to.get(r.account, 0)), str(r.lang or "und").upper()])
    return out
