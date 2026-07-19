"""Verifiable privacy receipts — the activity ledger is tamper-evident.

On a camera-and-mic device the activity ledger IS the privacy promise: "we
stayed on-device", "we were incognito", "we never touched the cloud". Before
this it was a freely-rewritable JSONL text file with clear()/prune()/restore()
and NO signature — anyone with write access could rewrite history and no one
could tell (refute 2026-07-18). These pin the new contract: with an Ed25519
receipt key, each record carries a monotonic seq, a prev-hash chain link, and a
signature; a third party handed ONLY the public key can detect any edit,
reorder, or mid-chain deletion — and a legitimate owner edit (prune/restore)
re-attests the survivors so the receipt stays consistent.

Skips cleanly when `cryptography` (the `privacy` extra) isn't installed — the
ledger then degrades to plain-text and verify() fail-safes to ok=False.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("cryptography")

from dreamlayer.ai_brain.server.store import (   # noqa: E402
    ActivityLog, activity_receipt_signer,
)
from dreamlayer.reality_compiler.sign_crypto import verify_detached   # noqa: E402


def _log(tmp_path):
    """A signed ActivityLog on a fresh dir + the signer that backs it."""
    signer = activity_receipt_signer(tmp_path)
    assert signer is not None and signer.available
    return ActivityLog(tmp_path, signer=signer), signer


# --- the happy path: a signed chain verifies ---------------------------------

def test_signed_records_verify_clean(tmp_path):
    log, _ = _log(tmp_path)
    log.add("folder", "watched ~/Documents", ts=1.0)
    log.add("cloud", "incognito on", ts=2.0)
    log.add("search", "found 3 memories", ts=3.0)
    v = log.verify()
    assert v["ok"] is True
    assert v["records"] == 3 and v["signed"] == 3 and v["unsigned"] == 0
    assert v["first_broken"] is None
    assert len(v["pubkey"]) == 64          # raw Ed25519 public key, hex


def test_each_record_carries_seq_prev_sig(tmp_path):
    log, _ = _log(tmp_path)
    log.add("a", "one", ts=1.0)
    log.add("b", "two", ts=2.0)
    recs = json.loads(json.dumps(log._read_all()))   # file order, oldest-first
    assert [r["seq"] for r in recs] == [0, 1]
    assert recs[0]["prev"] == ""                      # genesis
    assert recs[1]["prev"] != ""                      # links to #0
    assert all("sig" in r for r in recs)


# --- tamper detection: the whole point --------------------------------------

def test_editing_a_records_text_is_detected(tmp_path):
    log, _ = _log(tmp_path)
    log.add("cloud", "incognito on", ts=1.0)
    log.add("upload", "sent 0 bytes to cloud", ts=2.0)
    # An attacker rewrites the damning second record to look innocent.
    lines = log.path.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["text"] = "sent nothing, all local"
    lines[1] = json.dumps(rec)
    log.path.write_text("\n".join(lines) + "\n")

    v = log.verify()
    assert v["ok"] is False
    assert v["first_broken"] == 1          # the tampered seq


def test_deleting_a_middle_record_breaks_the_chain(tmp_path):
    log, _ = _log(tmp_path)
    for i in range(4):
        log.add("k", f"line {i}", ts=float(i))
    lines = log.path.read_text().splitlines()
    del lines[2]                            # excise a record from the middle
    log.path.write_text("\n".join(lines) + "\n")

    v = log.verify()
    assert v["ok"] is False
    assert v["first_broken"] is not None    # the prev-link no longer matches


def test_tail_truncation_is_detected(tmp_path):
    """The critical one (refute 2026-07-18): a hash chain has no length anchor, so
    chopping the most-recent (incriminating) records leaves a still-valid prefix.
    The signed head anchor attests the true high-water mark, so a truncation the
    attacker can't re-sign is caught."""
    log, _ = _log(tmp_path)
    for i in range(5):
        log.add("cloud", f"event {i}", ts=float(i))
    assert log.verify()["ok"] is True
    # attacker chops the last two records (e.g. "sent N bytes to cloud")
    lines = log.path.read_text().splitlines()
    log.path.write_text("\n".join(lines[:3]) + "\n")

    v = log.verify()
    assert v["ok"] is False
    assert v.get("truncated") is True
    assert v["first_broken"] == 3          # first missing seq


def test_truncate_then_continue_is_still_detected(tmp_path):
    """The seamless-continuation attack: chop the tail, then keep logging. The new
    record chains onto the anchor's head (the deleted record), so the broken link
    still betrays the cut."""
    log, _ = _log(tmp_path)
    for i in range(5):
        log.add("k", f"e{i}", ts=float(i))
    lines = log.path.read_text().splitlines()
    log.path.write_text("\n".join(lines[:3]) + "\n")     # truncate to seq 0..2
    reopened = ActivityLog(tmp_path, signer=activity_receipt_signer(tmp_path))
    reopened.add("k", "post-truncation", ts=99.0)
    assert reopened.verify()["ok"] is False


def test_deleting_the_head_anchor_is_flagged(tmp_path):
    """A signed log whose head anchor was deleted is unverifiable, not 'clean' —
    an attacker can't hide a truncation by also removing the anchor."""
    log, _ = _log(tmp_path)
    log.add("k", "one", ts=1.0)
    (tmp_path / "brain_activity.jsonl.head").unlink()
    v = log.verify()
    assert v["ok"] is False
    assert "anchor" in v.get("reason", "")


def test_concurrent_adds_keep_the_chain_valid(tmp_path):
    """The threaded Brain calls add() from many request threads. The signed-chain
    critical section + anchor write must be atomic, or two adds race a seq / the
    anchor temp-file collides (refute: a real FileNotFoundError under load)."""
    import threading
    log, _ = _log(tmp_path)
    errors = []

    def worker(n):
        try:
            for i in range(10):
                log.add("k", f"t{n}-{i}", ts=float(n * 100 + i))
        except Exception as exc:            # e.g. the anchor temp-file collision
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"add() raced under concurrency: {errors[:3]}"
    v = log.verify()
    assert v["ok"] is True and v["records"] == 80 and v["signed"] == 80
    seqs = sorted(r["seq"] for r in log._read_all())
    assert seqs == list(range(80))          # no duplicate/skipped seq


def test_receipt_carries_the_signed_head(tmp_path):
    log, _ = _log(tmp_path)
    for i in range(3):
        log.add("k", f"e{i}", ts=float(i))
    r = log.receipt()
    assert r["head"] is not None
    assert r["head"]["last_seq"] == 2 and r["head"]["count"] == 3


def test_receipt_head_carries_a_verifiable_signature(tmp_path):
    """The receipt's head anchor ships its OWN signature so the panel/phone can
    verify the length attestation independently (not just trust our server-side
    check). A third party with only the pubkey can confirm it."""
    log, _ = _log(tmp_path)
    for i in range(3):
        log.add("k", f"e{i}", ts=float(i))
    r = log.receipt()
    head = r["head"]
    assert head is not None and "sig" in head and head["sig"]
    core = {"last_seq": head["last_seq"], "head": head["head"], "count": head["count"]}
    assert verify_detached(core, head["sig"], r["pubkey"]) is True
    # tampering with the attested length invalidates the anchor signature
    assert verify_detached({**core, "count": core["count"] + 1}, head["sig"], r["pubkey"]) is False


def test_reordering_records_is_detected(tmp_path):
    log, _ = _log(tmp_path)
    log.add("k", "first", ts=1.0)
    log.add("k", "second", ts=2.0)
    log.add("k", "third", ts=3.0)
    lines = log.path.read_text().splitlines()
    lines[1], lines[2] = lines[2], lines[1]   # swap two records
    log.path.write_text("\n".join(lines) + "\n")

    assert log.verify()["ok"] is False


# --- third party with only the public key -----------------------------------

def test_a_third_party_can_verify_with_only_the_pubkey(tmp_path):
    """The receipt is portable: someone who never held the private key can take
    the public key + a record's core and confirm the signature independently."""
    log, signer = _log(tmp_path)
    log.add("cloud", "stayed offline", ts=1.0)
    receipt = log.receipt()
    pub = receipt["pubkey"]
    rec = receipt["records"][0]
    core = {"seq": rec["seq"], "ts": rec["ts"], "kind": rec["kind"],
            "text": rec["text"], "prev": rec["prev"]}
    assert verify_detached(core, rec["sig"], pub) is True
    # and a forged edit fails that same detached check
    core["text"] = "tampered"
    assert verify_detached(core, rec["sig"], pub) is False


def test_receipt_shape_is_portable(tmp_path):
    log, _ = _log(tmp_path)
    log.add("k", "x", ts=1.0)
    r = log.receipt()
    assert r["algorithm"] == "ed25519-sha256-chain"
    assert len(r["pubkey"]) == 64
    assert isinstance(r["records"], list) and r["records"]
    assert r["verification"]["ok"] is True


# --- owner edits re-attest (prune / restore keep the receipt valid) ----------

def test_prune_rechains_and_stays_verifiable(tmp_path):
    log, _ = _log(tmp_path)
    import time as _t
    now = _t.time()
    log.add("old", "ancient", ts=now - 100 * 86400)
    log.add("new1", "recent", ts=now - 1 * 86400)
    log.add("new2", "recent", ts=now)
    removed = log.prune(days=30)
    assert removed == 1
    v = log.verify()
    assert v["ok"] is True                  # survivors re-signed from genesis
    assert v["records"] == 2 and v["signed"] == 2
    # re-numbered from a fresh genesis
    seqs = [r["seq"] for r in log._read_all()]
    assert seqs == [0, 1]


def test_restore_rechains_and_stays_verifiable(tmp_path):
    log, _ = _log(tmp_path)
    log.add("k", "a", ts=1.0)
    log.add("k", "b", ts=2.0)
    snapshot = log.recent()                 # newest-first, as state export produces
    log.clear()
    assert log.verify()["records"] == 0
    log.restore(snapshot)
    v = log.verify()
    assert v["ok"] is True and v["records"] == 2


def test_add_after_prune_continues_the_chain(tmp_path):
    log, _ = _log(tmp_path)
    import time as _t
    now = _t.time()
    log.add("old", "ancient", ts=now - 100 * 86400)
    log.add("keep", "recent", ts=now)
    log.prune(days=30)
    log.add("after", "post-prune", ts=now + 1)
    v = log.verify()
    assert v["ok"] is True
    assert [r["seq"] for r in log._read_all()] == [0, 1]


# --- fail-safe + legacy tolerance -------------------------------------------

def test_unsigned_log_verify_is_fail_safe_false(tmp_path):
    """No signer → the ledger is plain text and NOT verifiable. verify() must
    say so honestly (ok=False + reason), never hand back a misleading True."""
    log = ActivityLog(tmp_path, signer=None)
    log.add("k", "unsigned", ts=1.0)
    v = log.verify()
    assert v["ok"] is False
    assert v["unsigned"] == 1 and v["signed"] == 0
    assert "reason" in v


def test_signed_log_flags_a_spliced_in_unsigned_record(tmp_path):
    """A record without seq/prev/sig cannot be trusted; a chain that contains one
    is not fully verified."""
    log, _ = _log(tmp_path)
    log.add("k", "signed", ts=1.0)
    with log.path.open("a") as f:
        f.write(json.dumps({"ts": 2.0, "kind": "k", "text": "spliced"}) + "\n")
    v = log.verify()
    assert v["ok"] is False
    assert v["unsigned"] == 1


def test_recent_is_unchanged_shape_for_the_panel(tmp_path):
    """The panel reads recent(): newest-first dicts. Signing is additive — the
    fields the panel already renders (ts/kind/text) are still there."""
    log, _ = _log(tmp_path)
    log.add("folder", "one", ts=1.0)
    log.add("search", "two", ts=2.0)
    r = log.recent()
    assert [x["kind"] for x in r] == ["search", "folder"]   # newest-first
    assert all({"ts", "kind", "text"} <= set(x) for x in r)


def test_signer_key_persists_across_reloads(tmp_path):
    """The receipt key is stored owner-only and reused, so a receipt stays
    verifiable after a Brain restart (a new key each boot would orphan history)."""
    s1 = activity_receipt_signer(tmp_path)
    s2 = activity_receipt_signer(tmp_path)
    assert s1.public_key_hex == s2.public_key_hex
    key_path = tmp_path / "receipt.key"
    assert key_path.exists()
    import os
    if os.name == "posix":
        assert (key_path.stat().st_mode & 0o777) == 0o600
