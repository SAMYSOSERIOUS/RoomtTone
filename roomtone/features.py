"""Account habits. One row per account, computed from pseudonymized events only."""
import re
import numpy as np
import pandas as pd

AI_PHRASES = ["the notion that", "oversimplifies", "it is worth noting", "in today's landscape", "delve into",
              "multifaceted", "underscores the importance", "as we navigate", "nuanced perspective", "key takeaway"]
AI_RE = re.compile("|".join(re.escape(p) for p in AI_PHRASES), re.I)


def account_features(ev: pd.DataFrame) -> pd.DataFrame:
    """Rhythm, sleep, regret, sign-up wave, AI phrases. Needs at least 5 posts per account."""
    posts = ev[ev.kind.isin(["post", "reply", "post_deleted"])].copy()
    created = ev[ev.kind == "account_created"].set_index("account")
    deletes = ev[ev.kind == "delete"].groupby("account").size().rename("n_deletes")
    rows = []
    for acc, g in posts.groupby("account"):
        ts = np.sort(g.ts.values)
        n = len(ts)
        if n < 5:
            continue
        gaps = np.diff(ts)
        gaps = gaps[gaps > 0]
        # rhythm: how even the gaps are (0 = perfectly even, like a metronome)
        rhythm_cv = float(gaps.std() / gaps.mean()) if len(gaps) > 1 and gaps.mean() > 0 else 1.0
        # sleep: longest quiet stretch in a typical day (hours), from the 24h activity profile
        hours = ((ts // 3600) % 24).astype(int)
        prof = np.bincount(hours, minlength=24)
        sleep_gap = _longest_zero_run(prof)
        # regret rate: deletes per post
        n_del = float(deletes.get(acc, 0))
        text = " ".join(g.text.dropna().astype(str))
        ai_hits = len(AI_RE.findall(text))
        rows.append(dict(account=acc, n_posts=n, rhythm_cv=rhythm_cv, sleep_gap_h=sleep_gap,
                         regret_rate=n_del / n, ai_phrase_rate=ai_hits / max(1, n),
                         posts_per_day=n / max(1.0, (ts[-1] - ts[0]) / 86400),
                         declared_bot=bool(created.declared_bot.get(acc, False)) if "declared_bot" in created else False,
                         created_at=float(created.created_at.get(acc, np.nan)) if "created_at" in created else np.nan))
    f = pd.DataFrame(rows)
    if f.empty:
        return f
    # sign-up wave: how many other accounts were created within the same 24h as this one
    if f.created_at.notna().any():
        day = (f.created_at // 86400).astype("Int64")
        f["signup_wave"] = day.map(day.value_counts()).astype(float)
    else:
        f["signup_wave"] = 1.0
    return f


def _longest_zero_run(prof: np.ndarray) -> int:
    """Longest run of empty hours, wrapping around midnight."""
    p = np.concatenate([prof, prof])
    best = run = 0
    for v in p:
        run = run + 1 if v == 0 else 0
        best = max(best, run)
    return int(min(best, 24))
