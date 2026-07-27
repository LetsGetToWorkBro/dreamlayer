"""Full-stack audit, privacy slice — the Veil, the erase, and the receipt.

Each test below pins a promise the product makes in its own copy and did not
keep. The pattern across all of them is the same: a gate existed, was correct,
and was applied to one sibling of a pair.

  * `probe_ollama` honoured the posture; `OllamaBackend._gen` did not.
  * `/brain/look` refused under the Veil; `/brain/explain` did not.
  * `dossier_query` refused to record who you asked about; `add_person` wrote
    the name, the rehearsal card and a signed ledger row.
  * `EmberStore.purge_all` VACUUMed; the main memory DB did not.
  * `add_memory` redacted PII; `add_commitment`, called three lines earlier in
    the same loop with the same transcript, did not.
"""
from __future__ import annotations

import json

import pytest

from dreamlayer.ai_brain.server.backends import (OllamaBackend,
                                                 is_blocked_endpoint,
                                                 is_local_endpoint)
from dreamlayer.ai_brain.server.store import in_quiet_hours
from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.pii_presidio import default_redactor


# --------------------------------------------------------------------------
# A-C1 — a non-local Ollama endpoint is egress: gated, counted, logged
# --------------------------------------------------------------------------

class _Cfg:
    def __init__(self, url, lan_only=False, quiet_hours=""):
        self.ollama_url = url
        self.lan_only = lan_only
        self.quiet_hours = quiet_hours
        self.ollama_chat_model = "llama3.2"
        self.ollama_vision_model = "llama3.2-vision"
        self.ollama_embed_model = "nomic-embed-text"


def _recorder():
    calls = []

    def post(url, payload):
        calls.append((url, payload))
        return {"response": "answered", "embedding": [0.1] * 8}
    return calls, post


def test_a_remote_ollama_is_refused_under_the_veil():
    """The panel calls Ollama the on-device tier and says it "keeps working
    while incognito". True for 127.0.0.1; a LAN or remote box is another
    machine, and shipping the wearer's notes there while veiled is the leak."""
    calls, post = _recorder()
    b = OllamaBackend(_Cfg("http://192.0.2.2:11434", lan_only=True), http_post=post)
    assert b.chat("what about the lease") == ""
    assert b.vision("a mug", "aGk=", "more") == ""
    assert b.describe("read this", "aGk=") == ""
    assert b.embed("private passage") == []
    assert calls == [], f"a veiled request left the machine: {calls}"


def test_a_remote_ollama_is_counted_and_logged_when_the_veil_is_down():
    calls, post = _recorder()
    noted = []
    b = OllamaBackend(_Cfg("http://192.0.2.2:11434"), http_post=post,
                      on_egress=noted.append)
    assert b.chat("hello") == "answered"
    assert len(calls) == 1
    assert noted == ["http://192.0.2.2:11434"], "egress was not reported"


def test_a_loopback_ollama_still_works_while_veiled_and_is_not_counted():
    """The whole point of the local tier. A localhost request is not egress, so
    the shield must not break it and the counter must not move."""
    calls, post = _recorder()
    noted = []
    b = OllamaBackend(_Cfg("http://127.0.0.1:11434", lan_only=True),
                      http_post=post, on_egress=noted.append)
    assert b.chat("hello") == "answered"
    assert len(calls) == 1
    assert noted == []


def test_a_link_local_ollama_endpoint_is_refused_outright():
    calls, post = _recorder()
    b = OllamaBackend(_Cfg("http://169.254.169.254:11434"), http_post=post)
    assert b.chat("hello") == ""
    assert b.embed("x") == []
    assert calls == []


# --------------------------------------------------------------------------
# A-H1 — link-local is never "on your device"
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["http://169.254.169.254", "http://169.254.1.1",
                                 "http://169.254.169.254:11434"])
def test_cloud_metadata_space_is_remote_and_blocked(url):
    """It was in BOTH _LOCAL_NETS and _BLOCKED_NETS, so any call site that asked
    only `is_local_endpoint` treated cloud-credential space as trusted: exempt
    from the egress counter, exempt from the veil, and shown to the wearer as
    "on your device"."""
    assert is_local_endpoint(url) is False
    assert is_blocked_endpoint(url) is True


def test_a_redirect_cannot_walk_out_of_the_ssrf_guard():
    """`is_blocked_endpoint` was checked once, against the URL the caller gave,
    and then the opener followed a 302 anywhere. urllib also keeps the
    Authorization header across a redirect, so the wearer's provider key went
    to the redirect target along with the request."""
    from dreamlayer.ai_brain.server import backends
    handler = backends._NoBlockedRedirect()

    import urllib.request
    req = urllib.request.Request("https://api.example.com/v1/chat")

    with pytest.raises(Exception):
        handler.redirect_request(req, None, 302, "Found", {},
                                 "http://169.254.169.254/latest/meta-data/")
    # a benign redirect is still followed, or the guard would break every provider
    out = handler.redirect_request(req, None, 302, "Found", {},
                                   "https://api.example.com/v2/chat")
    assert out is not None


def test_the_guard_is_actually_wired_into_the_opener():
    """The test above builds `_NoBlockedRedirect()` by hand. That proves the class
    works and NOT that anything uses it — the entire fix could be unwired
    (`build_opener(ProxyHandler({}))`) and it would stay green. This pins the
    wiring, which is the part that protects anyone."""
    from dreamlayer.ai_brain.server import backends
    opener = backends._guarded_opener()
    assert any(isinstance(h, backends._NoBlockedRedirect)
               for h in opener.handlers), "the SSRF redirect guard is not installed"
    # …and no model-fetch helper may build a bare opener behind its back.
    import inspect
    src = inspect.getsource(backends)
    assert "build_opener(urllib.request.ProxyHandler({}))" not in src, (
        "a fetch helper builds an unguarded opener")


@pytest.mark.parametrize("spelling", [
    "http://0251.0376.0251.0376",      # octal dotted
    "http://0xa9fea9fe",               # hex 32-bit
    "http://2852039166",               # decimal 32-bit
    "http://169.254.43518",            # mixed / short form
    "http://169.254.169.254.",         # root-anchored trailing dot
    "http://[::ffff:a9fe:a9fe]",       # IPv4-mapped, hex groups
])
def test_every_spelling_of_the_metadata_address_is_blocked(spelling):
    """The guard matched a STRING, not a destination. `ipaddress.ip_address`
    accepts only dotted-quad and canonical IPv6, so all six of these reached
    169.254.169.254 while reading as "not blocked" — through POST /config, POST
    /restore, the redirect guard and _provider_chat alike."""
    assert is_blocked_endpoint(spelling) is True
    assert is_local_endpoint(spelling) is False


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:11434", "http://192.168.1.50:11434", "http://10.0.0.5",
    "http://[::1]", "http://api.openai.com", "http://osrm.local:5000",
    "http://172.16.0.1", "http://8.8.8.8",
])
def test_canonicalising_did_not_start_blocking_real_endpoints(url):
    assert is_blocked_endpoint(url) is False


def test_a_provider_key_does_not_cross_a_redirect_to_another_host():
    """urllib strips the BODY on a 30x and keeps the Authorization header, so a
    redirect from a compromised or mistyped endpoint handed the wearer's provider
    key to whoever it pointed at — and returned their body as the model's answer.
    Blocking link-local never addressed that; the destination that matters is
    "not the host I authenticated to"."""
    import urllib.request
    from dreamlayer.ai_brain.server import backends
    handler = backends._NoBlockedRedirect()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat",
        headers={"Authorization": "Bearer sk-WEARER-SECRET"})

    away = handler.redirect_request(req, None, 302, "Found", {},
                                    "https://attacker.example/v1/chat")
    assert away is not None
    assert away.has_header("Authorization") is False
    assert "sk-WEARER-SECRET" not in str(sorted(away.headers.items()))

    same = handler.redirect_request(req, None, 302, "Found", {},
                                     "https://api.openai.com/v2/chat")
    assert same.has_header("Authorization") is True   # same host: still needed


# --------------------------------------------------------------------------
# A-M4 — a wrongly-typed config field must not break an endpoint forever
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [5, None, {}, [], 1.5])
def test_quiet_hours_never_raises_on_a_non_string(bad):
    """`"-" not in 5` raised TypeError out of `in_quiet_hours`, and because
    `incognito_now()` calls it, GET /dreamlayer/status answered zero bytes from
    then on -- which the panel renders as "Brain offline"."""
    assert in_quiet_hours(bad) is False


# --------------------------------------------------------------------------
# C4 / C9 — one PII chokepoint, and it must not eat dates
# --------------------------------------------------------------------------

def test_a_commitment_is_redacted_like_a_memory(tmp_path):
    db = MemoryDB(str(tmp_path / "m.db"))
    db.add_commitment("Ana", "pay back 4111 1111 1111 1111 by Friday")
    task = db.commitments()[0]["task"]
    assert "4111" not in task, f"a card number reached commitments.task: {task!r}"
    assert "<CARD>" in task


def test_the_whole_ingest_loop_redacts_both_writers(tmp_path):
    """`add_memory`'s docstring called itself "the single write chokepoint every
    capture path funnels through" while `IngestPipeline.ingest` called
    `add_commitment` three lines earlier with the same transcript."""
    db = MemoryDB(str(tmp_path / "m.db"))
    line = "I'll wire Ana the money to 4111 1111 1111 1111 tomorrow"
    db.add_memory("promise", line)
    db.add_commitment("Ana", line)
    blob = json.dumps(db.memories() + db.commitments())
    assert "4111" not in blob


@pytest.mark.parametrize("text", [
    "dentist appointment on 2026-08-14 at the clinic",
    "lease runs 2024-01-01 to 2026-12-31",
    "Maya's flight lands 2026-09-01, terminal 2",
])
def test_iso_dates_survive_the_fallback_redactor(text):
    """The `-`/space/`.` in the phone pattern swallowed every ISO date, and
    redaction runs BEFORE the INSERT, so the date was unrecoverable. Two of the
    four shipped profiles have no presidio, so this was the default path."""
    assert default_redactor().redact(text) == text


def test_a_card_number_no_longer_eats_the_following_space():
    out = default_redactor().redact("card 4111 1111 1111 1111 exp")
    assert out == "card <CARD> exp"


def test_real_identifiers_are_still_stripped():
    """The date fix must not have loosened the thing the redactor is for."""
    red = default_redactor()
    assert "<PHONE>" in red.redact("call +1 415 555 0132 tomorrow")
    assert "<EMAIL>" in red.redact("email me at nadia@example.com")
    assert "<CARD>" in red.redact("the card is 4111111111111111")


# --------------------------------------------------------------------------
# C5 / C10 — a purge scrubs the bytes, and takes the commitment with it
# --------------------------------------------------------------------------

def test_purge_all_leaves_no_plaintext_in_the_file(tmp_path):
    """A bare DELETE frees SQLite pages without scrubbing them. Whether that
    mattered depended on an undeclared COMPILE-TIME flag that differs between
    the Debian build and the python.org macOS build the full Brain runs on --
    so the test forces the unsafe setting to prove the fix, not the platform."""
    path = tmp_path / "m.db"
    db = MemoryDB(str(path))
    db.conn.execute("PRAGMA secure_delete=OFF")
    for i in range(40):
        db.add_memory("conversation", f"RESIDUEPROBE{i} the safe code is 8842")
    db.purge_all()
    assert db.memories() == []
    assert b"RESIDUEPROBE" not in path.read_bytes()


def test_forgetting_a_memory_takes_its_commitment_with_it(tmp_path):
    db = MemoryDB(str(tmp_path / "m.db"))
    mid = db.add_memory("promise", "I owe Vic the money")
    db.add_commitment("Vic", "COMMITPROBE repay the debt", source_memory_id=mid)
    db.add_commitment("Sam", "unrelated errand")
    db.purge_memory(mid)
    tasks = [c["task"] for c in db.commitments()]
    assert "COMMITPROBE repay the debt" not in tasks
    assert "unrelated errand" in tasks, "an unrelated commitment was collateral"


# --------------------------------------------------------------------------
# C3 — the rollback watermark cannot be lowered by an ordinary append
# --------------------------------------------------------------------------

def _mark(tmp_path):
    """The REAL `_ReceiptWatermark`, backed by an in-memory store.

    This used to be a hand-written stand-in that reimplemented the monotonic
    logic inside the test file — so deleting the whole `if not allow_lower:
    max(cur, n)` block from production left both tests below green. A test that
    contains the behaviour it is meant to pin cannot fail when that behaviour is
    removed. Only the STORAGE is faked now; the logic under test is the real one.
    """
    from dreamlayer.ai_brain.server.store import _ReceiptWatermark

    class _MemStore:
        def __init__(self):
            self._v = {}

        def get(self, name):
            return self._v.get(name)

        def set(self, name, blob):
            self._v[name] = blob

    store = _MemStore()
    wm = _ReceiptWatermark.__new__(_ReceiptWatermark)
    wm._get_store = lambda: store
    return wm


def _log(tmp_path, mark, signer=None):
    from dreamlayer.ai_brain.server.store import ActivityLog
    signer = signer or _signer()
    if signer is None:
        pytest.skip("no Ed25519 signer available (cryptography absent)")
    return ActivityLog(tmp_path, signer=signer, watermark=mark)


def _signer():
    """A real Ed25519 signer, built directly. `activity_receipt_signer` reads a
    seed out of the secret store, which is not present in a bare test env, and
    skipping would have left the watermark fix unverified."""
    from dreamlayer.reality_compiler.sign_crypto import Signer
    if not Signer.available:
        return None
    return Signer(bytes(range(32)))


def test_one_append_cannot_relaunder_a_wiped_ledger(tmp_path):
    """Delete the ledger and its anchor, and the very next logged action -- a
    search, a folder index, an incognito toggle, i.e. seconds on a live device --
    used to reset the mark to the shortened length. verify() then went green
    under the same public key, so the wipe concealed itself and the
    cloud-egress records were gone with no trace anywhere."""
    mark = _mark(tmp_path)
    log = _log(tmp_path, mark)
    for i in range(6):
        log.add("cloud", f"sent frame {i} to a provider")
    assert log.verify()["ok"] is True
    high = mark.get(getattr(log._signer, "public_key_hex", ""))
    assert high == 6

    for p in tmp_path.glob("brain_activity.jsonl*"):
        p.unlink()
    fresh = _log(tmp_path, mark)
    fresh.add("index", "watched ~/Downloads")
    out = fresh.verify()
    assert out["ok"] is False, f"a wipe concealed itself: {out}"
    assert out.get("rolled_back") is True


def test_a_legitimate_prune_may_still_lower_the_mark(tmp_path):
    """The owner's own prune/restore is an explicit shrink and must keep
    working, or the fix would break the feature it protects."""
    mark = _mark(tmp_path)
    log = _log(tmp_path, mark)
    for i in range(6):
        log.add("index", f"entry {i}")
    log.restore([{"ts": 1.0, "kind": "index", "text": "just this one"}])
    assert log.verify()["ok"] is True
    # The restored chain is the marker below plus the one restored record.
    assert mark.get(getattr(log._signer, "public_key_hex", "")) == 2


def test_a_restore_cannot_launder_the_ledger_silently(tmp_path):
    """`POST /dreamlayer/restore {"activity": []}` was a one-request laundering
    route: `_rechain` is allowed to lower the watermark, so every signed
    cloud-egress row vanished, the mark reset, and verify() stayed green with
    nothing anywhere recording that the ledger had been replaced. A legitimate
    restore has no reason to hide, so the new chain opens with a signed record
    of what it replaced."""
    mark = _mark(tmp_path)
    log = _log(tmp_path, mark)
    for i in range(5):
        log.add("cloud", f"sent frame {i} to a provider")

    log.restore([])                                  # the wipe attempt
    out = log.verify()
    assert out["ok"] is True                         # still a valid owner edit…
    texts = [r.get("text", "") for r in log.recent(10)]
    assert any("restored from a backup" in x for x in texts), (
        f"the shrink left no trace: {texts}")
    assert any("5 record(s) replaced with 0" in x for x in texts)
