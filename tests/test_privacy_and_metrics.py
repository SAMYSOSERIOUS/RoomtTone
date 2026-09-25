import time
import pandas as pd
from roomtone.privacy import gate, pseudonym, honor_deletes, purge, safe_to_publish
from roomtone.metrics import wasted_breath, immune_response
from roomtone import MIN_GROUP


def test_pseudonym_is_stable_and_not_reversible():
    assert pseudonym("did:plc:abc") == pseudonym("did:plc:abc")
    assert pseudonym("did:plc:abc") != pseudonym("did:plc:abd")
    assert "abc" not in pseudonym("did:plc:abc")


def test_gate_drops_optouts_and_names():
    ev = pd.DataFrame([dict(kind="post", ts=1.0, account="did:plc:a", target_account=None, uri="u1", text="hi", display_name="Anna"),
                       dict(kind="post", ts=2.0, account="did:plc:b", target_account="did:plc:a", uri="u2", text="yo", display_name="Ben")])
    out = gate(ev, optouts={"did:plc:b"})
    assert len(out) == 1 and "display_name" not in out and out.account.iloc[0] == pseudonym("did:plc:a")


def test_deletes_remove_text_but_keep_regret():
    ev = pd.DataFrame([dict(kind="post", ts=1.0, account="x", uri="u1", text="oops", ref=None),
                       dict(kind="delete", ts=2.0, account="x", uri=None, text=None, ref="u1")])
    out = honor_deletes(ev)
    assert pd.isna(out.loc[0, "text"]) and out.loc[0, "kind"] == "post_deleted" and (out.kind == "delete").sum() == 1


def test_purge_retention():
    now = time.time()
    ev = pd.DataFrame([dict(kind="post", ts=now - 40 * 86400, text="old"), dict(kind="post", ts=now - 100 * 86400, text="ancient"),
                       dict(kind="post", ts=now, text="new")])
    out = purge(ev, now)
    assert len(out) == 2 and pd.isna(out.text.iloc[0]) and out.text.iloc[1] == "new"


def test_small_groups_are_never_published():
    assert not safe_to_publish(MIN_GROUP - 1) and safe_to_publish(MIN_GROUP)
    ev = pd.DataFrame([dict(kind="like", ts=100.0 + i, account=f"h{i}", target="b0", topic="t") for i in range(10)])
    groups = pd.Series({**{f"h{i}": "human" for i in range(10)}, "b0": "automated"})
    wb = wasted_breath(ev, groups, 0.0)
    assert wb.wasted_breath.isna().all()  # 10 humans < MIN_GROUP


def test_immune_response_measures_hours():
    wb = pd.DataFrame(dict(topic="t", hour=range(6), wasted_breath=[0.1, 0.3, 0.4, 0.2, 0.1, 0.1]))
    r = immune_response(wb, "t")
    assert r["spike"] and r["start_hour"] == 1 and r["hours_until_recovery"] == 2


def test_redaction_blacks_out_personal_details():
    from roomtone.redact import redact, BAR
    out = redact("contact anna.k@mail.example or +49 151 2345678, @anna_k92, my name is Jonas Weber, https://truth-now.example/p/1")
    for leak in ("anna.k@", "2345678", "anna_k92", "Jonas", "/p/1"):
        assert leak not in out
    assert BAR in out and "truth-now.example" in out


def test_pipeline_survives_thin_live_data(tmp_path, monkeypatch):
    """A first live run has minutes of data, no labels and few accounts: every stage must degrade, not crash."""
    import pandas as pd, numpy as np, json
    from roomtone import pipeline
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "data" / "bluesky"; d.mkdir(parents=True)
    now = 1_800_000_000.0
    rows = [dict(kind="post", ts=now + i * 30, account=f"did:plc:x{i % 7}", target_account=None, uri=f"u{i}", text=f"hello election {i}", topic="election", lang="en") for i in range(40)]
    rows += [dict(kind="account_created", ts=now, account=f"did:plc:x{i}", declared_bot=False, created_at=now - 86400 * 30, lang="en") for i in range(7)]
    pd.DataFrame(rows).to_parquet(d / "events.parquet", index=False)
    pd.DataFrame([dict(hour=0, topic="election", posts=40, rank=1)]).to_parquet(d / "official_trends.parquet", index=False)
    r = pipeline.run("bluesky")
    assert r["headline"]["accounts"]["total"] >= 0 and "flow" in r and json.dumps(r, default=float)
