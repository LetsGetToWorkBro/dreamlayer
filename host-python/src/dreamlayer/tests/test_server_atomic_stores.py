"""test_server_atomic_stores.py — the Brain server's JSON stores under threads.

Regression for the Concurrency fix (audit 2026-07-14, Section 7 / fix-list
MEDIUM): the six authed JSON stores (add_event / sync_calendar / add_person /
sync_contacts / sync_reminders / _save_people) do a read-modify-write of a
cfg_dir JSON file while the server runs under ThreadingHTTPServer. Before the
fix each was an unlocked, non-atomic write, so two concurrent authed POSTs could
interleave a load-append-save and lose or corrupt rows.

The fix routes every one of them through ``Brain._load_json`` / ``_save_json``,
which serialize on a single shared ``Brain._store_lock`` (a re-entrant
``threading.RLock``) and write atomically (temp file + ``os.replace``). These
tests prove:

  * no lost writes when many threads hammer add_person / add_event,
  * a concurrent reader never catches a half-written store (os.replace atomicity),
  * concurrent *authed HTTP POSTs* survive the same way over real localhost,
  * all six stores actually route through the atomic ``_save_json`` helper,
  * the shared lock exists and is re-entrant (a plain Lock would deadlock).
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from dreamlayer.ai_brain.server import Brain, BrainConfig, make_brain_server


# ---------------------------------------------------------------------------
# direct method-level stress (the read-modify-write path)
# ---------------------------------------------------------------------------

def test_add_person_concurrent_no_lost_writes(tmp_path):
    b = Brain(tmp_path)
    n_threads, per = 10, 30
    names = {f"Person-{t}-{i}" for t in range(n_threads) for i in range(per)}

    def worker(t):
        for i in range(per):
            b.add_person(f"Person-{t}-{i}", note="n")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    people = b.people()
    got = {p["name"] for p in people}
    assert got == names                       # nothing lost to an interleaved RMW
    assert len(people) == len(names)          # and no duplicates / partial rows
    # the on-disk store is complete and valid JSON
    disk = json.loads((tmp_path / "people.json").read_text())
    assert {e["name"] for e in disk} == names


def test_add_event_concurrent_no_lost_writes(tmp_path):
    b = Brain(tmp_path)
    n_threads, per = 10, 30
    base = time.time() + 3600                 # all in the future → all "upcoming"
    titles = {f"Ev-{t}-{i}" for t in range(n_threads) for i in range(per)}

    def worker(t):
        for i in range(per):
            b.add_event(f"Ev-{t}-{i}", ts=base + t * 100 + i, place="p")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    events = b.calendar(10_000)               # add_event appends unconditionally
    assert len(events) == n_threads * per     # every append survived
    assert {e["title"] for e in events} == titles
    disk = json.loads((tmp_path / "agenda.json").read_text())
    assert len(disk) == n_threads * per


def test_concurrent_reader_never_sees_torn_write(tmp_path):
    """os.replace atomicity: while writers hammer people.json, a reader must
    only ever observe a complete previous-or-next version — never a truncated,
    mid-write file. A non-atomic in-place write would let a reader catch a
    partial file and raise JSONDecodeError."""
    b = Brain(tmp_path)
    people_file = tmp_path / "people.json"
    stop = threading.Event()
    decode_errors: list[str] = []

    def reader():
        while not stop.is_set():
            try:
                txt = people_file.read_text()
            except OSError:
                continue                      # not created yet / vanished mid-read
            if not txt:
                continue
            try:
                json.loads(txt)
            except ValueError as exc:         # a torn write would land here
                decode_errors.append(str(exc))

    def writer(t):
        for i in range(50):
            b.add_person(f"P-{t}-{i}")

    readers = [threading.Thread(target=reader) for _ in range(3)]
    for r in readers:
        r.start()
    writers = [threading.Thread(target=writer, args=(t,)) for t in range(8)]
    for w in writers:
        w.start()
    for w in writers:
        w.join()
    stop.set()
    for r in readers:
        r.join()

    assert decode_errors == []                # readers never caught a half-written store
    # and after the storm the store is intact and complete
    disk = json.loads(people_file.read_text())
    assert len(disk) == 8 * 50


# ---------------------------------------------------------------------------
# real localhost HTTP: concurrent authed POSTs
# ---------------------------------------------------------------------------

def _post(url, payload, headers):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=10) as r:
        return json.loads(r.read().decode())


def test_concurrent_authed_posts_survive_http(tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    BrainConfig(token="tok").save(cfg_dir)
    brain = Brain(cfg_dir)
    server = make_brain_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    headers = {"X-DreamLayer-Token": "tok", "Content-Type": "application/json"}

    n_threads, per = 8, 20
    people_names = {f"H-{t}-{i}" for t in range(n_threads) for i in range(per)}
    event_titles = {f"E-{t}-{i}" for t in range(n_threads) for i in range(per)}
    errors: list[str] = []

    def worker(t):
        for i in range(per):
            try:
                _post(url + "/dreamlayer/people", {"name": f"H-{t}-{i}"}, headers)
                _post(url + "/dreamlayer/calendar",
                      {"title": f"E-{t}-{i}", "ts": time.time() + 7200 + t * 100 + i},
                      headers)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    try:
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert errors == []
        # ThreadingHTTPServer served each POST on its own thread — the stores
        # still contain every row, uncorrupted.
        ppl = json.loads((cfg_dir / "people.json").read_text())
        assert {e["name"] for e in ppl} == people_names
        agenda = json.loads((cfg_dir / "agenda.json").read_text())
        assert {e["title"] for e in agenda} == event_titles
        assert len(agenda) == n_threads * per
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# the six stores route through the atomic helper; the lock is shared + re-entrant
# ---------------------------------------------------------------------------

def test_all_six_stores_route_through_atomic_save(tmp_path):
    """Each of the six named stores writes via Brain._save_json (temp +
    os.replace under _store_lock). Spy on _save_json and confirm every store's
    write path lands there, then confirm each file is valid JSON on disk."""
    b = Brain(tmp_path)
    # deterministic macOS-source seams for the three sync stores
    b._calendar_reader = lambda cfg: [
        {"title": "Standup", "ts": time.time() + 3600, "place": "", "calendar": "Work"}]
    b._contacts_reader = lambda cfg: [
        {"name": "Alice", "company": "Acme", "role": "Eng", "email": "a@x"}]
    b._reminders_reader = lambda cfg: [{"title": "Buy milk", "ts": 0, "list": "Home"}]

    saved: list[str] = []
    orig = b._save_json

    def spy(name, obj):
        saved.append(name)
        return orig(name, obj)

    b._save_json = spy

    b.add_event("Coffee", ts=time.time() + 3600, place="Cafe")   # -> agenda.json
    b.sync_calendar()                                            # -> agenda.json
    b.add_person("Bob", note="friend")                          # -> people.json
    b.sync_contacts()                                           # -> people.json
    b.sync_reminders()                                          # -> reminders.json
    b.receive_people({"people": [{"contact_id": "c1", "name": "Cara"}]})  # -> social_people.json

    assert saved.count("agenda.json") >= 2          # add_event + sync_calendar
    assert saved.count("people.json") >= 2          # add_person + sync_contacts
    assert "reminders.json" in saved                # sync_reminders (full replace)
    assert "social_people.json" in saved            # _save_people via receive_people

    for fn in ("agenda.json", "people.json", "reminders.json", "social_people.json"):
        json.loads((tmp_path / fn).read_text())     # atomic writes never leave a torn file
    assert not list(tmp_path.glob("*.tmp"))         # no leftover temp files


def test_store_lock_is_shared_and_reentrant(tmp_path):
    b = Brain(tmp_path)
    assert b._store_lock is not None
    # A plain Lock would deadlock on the second acquire; the stores need an
    # RLock because add_event/add_person nest _load_json (which locks) inside
    # their own locked read-modify-write section.
    acquired_twice = False
    with b._store_lock:
        with b._store_lock:
            acquired_twice = True
    assert acquired_twice


def test_save_json_writes_via_tmp_then_replace(tmp_path, monkeypatch):
    """_save_json is atomic: it writes a sibling .tmp and os.replace()s it onto
    the target, leaving no partial file and no leftover temp."""
    import dreamlayer.ai_brain.server.server as srv
    b = Brain(tmp_path)
    real_replace = srv.os.replace
    replaced: list[tuple[str, str]] = []

    def spy_replace(src, dst):
        replaced.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(srv.os, "replace", spy_replace)
    b._save_json("agenda.json", [{"title": "x", "ts": 0, "place": ""}])

    assert any(s.endswith(".tmp") and d.endswith("agenda.json") for s, d in replaced)
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads((tmp_path / "agenda.json").read_text())[0]["title"] == "x"
