"""W6 + W8-seal — the rehearsal lifecycle and the sealed-recall receipt, over HTTP.

Introducing someone now starts a rehearsal (the moment a name slips is right
after you hear it); the brief resurfaces what's due; the panel can review an
outcome and reschedule; and a recall can run under a whole-process egress seal
that signs a "nothing left the device" receipt into the tamper-evident ledger.
These pin the wiring SourceOps + the two new routes add.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from dreamlayer.ai_brain.server import Brain, BrainConfig, make_brain_server


def _post(url, payload, headers=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


class LiveBrain:
    def __init__(self, tmp_path, token="tok"):
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        BrainConfig(token=token).save(cfg_dir)
        self.brain = Brain(cfg_dir)
        self.server = make_brain_server(self.brain, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.h = {"X-DreamLayer-Token": token}

    def stop(self):
        self.server.shutdown(); self.server.server_close()


# ---- the rehearsal lifecycle (unit) --------------------------------------

def test_introducing_someone_starts_a_rehearsal(tmp_path):
    b = Brain(tmp_path)
    b.add_person("Sam Rivera", "met at the offsite")
    items = b._rehearsal().all()
    assert any(i["id"] == "person:sam rivera" for i in items)
    it = next(i for i in items if i["id"] == "person:sam rivera")
    assert "Sam Rivera" in it["text"] and "offsite" in it["text"]


def test_rehearse_person_empty_name_is_noop(tmp_path):
    b = Brain(tmp_path)
    assert b.rehearse_person("") is None
    assert b._rehearsal().all() == []


def test_review_reschedules_and_counts_a_rep(tmp_path):
    b = Brain(tmp_path)
    r = b.rehearse_person("Alex", "coffee chat")
    rev = b.review_rehearsal(r["id"], "good")
    assert rev is not None and rev["reps"] == 1
    assert b.review_rehearsal("person:nobody", "good") is None


def test_add_person_never_fails_when_rehearsal_breaks(tmp_path, monkeypatch):
    b = Brain(tmp_path)
    monkeypatch.setattr(b, "rehearse_person",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    # the introduction must still succeed even if rehearsal blows up
    people = b.add_person("Robin")
    assert any(p["name"] == "Robin" for p in people)


def test_brief_surfaces_a_due_name(tmp_path, monkeypatch):
    b = Brain(tmp_path)
    monkeypatch.setattr(b, "rehearsals_due",
                        lambda limit=5: [{"id": "person:mara",
                                          "text": "Mara — your new neighbor"}])
    out = b.brief()
    assert "Mara" in out["text"]


# ---- the HTTP surface ----------------------------------------------------

def test_rehearsal_get_and_review_endpoints(tmp_path):
    lb = LiveBrain(tmp_path)
    try:
        lb.brain.rehearse_person("Jordan", "book club")
        st, body = _get(lb.url + "/dreamlayer/rehearsal", lb.h)
        assert st == 200 and "engine" in body and "items" in body
        # review the just-added item
        st2, body2 = _post(lb.url + "/dreamlayer/rehearsal/review",
                           {"id": "person:jordan", "rating": "good"}, lb.h)
        assert st2 == 200 and body2["item"]["reps"] == 1
        # a missing id 400s
        st3, _ = _post(lb.url + "/dreamlayer/rehearsal/review", {}, lb.h)
        assert st3 == 400
    finally:
        lb.stop()


def test_sealed_recall_endpoint_returns_answer_and_receipt(tmp_path):
    lb = LiveBrain(tmp_path)
    try:
        st, body = _post(lb.url + "/dreamlayer/recall/sealed",
                        {"query": "anything at all"}, lb.h)
        assert st == 200
        assert set(("answer", "tier", "sources", "receipt")) <= set(body)
        # the receipt is the signed ledger — it must carry the seal's verdict
        rec = json.dumps(body["receipt"])
        assert "egress_seal" in rec or "records" in rec or "entries" in rec
        # an empty query 400s
        st2, _ = _post(lb.url + "/dreamlayer/recall/sealed", {"query": ""}, lb.h)
        assert st2 == 400
    finally:
        lb.stop()


def test_sealed_recall_logs_an_egress_seal_record(tmp_path):
    b = Brain(tmp_path)
    before = len(b.activity.receipt().get("records", []))
    b.sealed_recall("what did I do yesterday")
    after = b.activity.receipt().get("records", [])
    assert len(after) > before
    # the newest record attests the seal
    assert any(r.get("kind") == "egress_seal" for r in after)
