"""Privacy gate. Everything passes through here before it is stored or analyzed."""
import hashlib, hmac, os, time
from pathlib import Path
import pandas as pd

KEY = os.environ.get("ROOMTONE_KEY", "change-me-and-keep-me-secret").encode()
TEXT_RETENTION_DAYS = 30
FEATURE_RETENTION_DAYS = 90


def pseudonym(account_id: str) -> str:
    """A scrambled code for an account. Same account -> same code; no way back without the key."""
    return hmac.new(KEY, account_id.encode(), hashlib.sha256).hexdigest()[:16]


def load_optouts(path="data/optout.txt") -> set:
    p = Path(path)
    if not p.exists():
        return set()
    return {line.strip() for line in p.read_text().splitlines() if line.strip()}


def gate(events: pd.DataFrame, optouts: set | None = None) -> pd.DataFrame:
    """Apply the gate: pseudonymize, drop opt-outs, honor deletes, strip fields we never keep."""
    optouts = optouts if optouts is not None else load_optouts()
    ev = events.copy()
    if optouts:
        ev = ev[~ev["account"].isin(optouts)]
    if "target_account" in ev:
        ev["target"] = ev["target_account"].map(lambda a: pseudonym(a) if isinstance(a, str) else None)
        ev = ev.drop(columns=["target_account"])
    ev["account"] = ev["account"].map(pseudonym)
    ev = honor_deletes(ev)
    for col in ("display_name", "bio", "avatar", "followers_list"):
        if col in ev:
            ev = ev.drop(columns=[col])
    return ev.reset_index(drop=True)


def honor_deletes(ev: pd.DataFrame) -> pd.DataFrame:
    """A delete event removes the post it points at, but we keep the fact that a delete happened
    (the 'regret' signal) without the text."""
    if "ref" not in ev or "uri" not in ev:
        return ev
    deleted = set(ev.loc[ev["kind"] == "delete", "ref"].dropna())
    if not deleted:
        return ev
    ev["text"] = ev["text"].astype(object)
    mask = (ev["kind"] == "post") & ev["uri"].isin(deleted)
    ev.loc[mask, "text"] = None
    ev.loc[mask, "kind"] = "post_deleted"
    return ev


def purge(ev: pd.DataFrame, now: float | None = None) -> pd.DataFrame:
    """Retention: drop raw text older than 30 days, drop everything older than 90 days."""
    now = now or time.time()
    ev = ev[ev["ts"] > now - FEATURE_RETENTION_DAYS * 86400].copy()
    old_text = ev["ts"] < now - TEXT_RETENTION_DAYS * 86400
    ev["text"] = ev["text"].astype(object)
    ev.loc[old_text, "text"] = None
    return ev


def safe_to_publish(n_accounts: int, min_group: int = 50) -> bool:
    return n_accounts >= min_group
