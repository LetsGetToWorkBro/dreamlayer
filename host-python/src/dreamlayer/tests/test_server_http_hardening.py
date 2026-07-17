"""test_server_http_hardening.py — the Brain HTTP server's request surface.

Regression suite for the HTTP-surface hardening (audit 2026-07-17, "HTTP surface
robustness" B-→A). Every test below is *revert-failing*: undo the matching fix in
ai_brain/server/server.py and the assertion breaks. The five closed gaps:

  1. NO request-body size cap — _body()/_raw() read Content-Length bytes
     unconditionally and _write_upload wrote the raw body with no cap, so an
     authed/loopback caller could drive unbounded memory or fill the disk.
     Fix: a bounded read with a 16 MiB JSON cap (MAX_JSON_BODY) and a 64 MiB
     upload cap (MAX_UPLOAD_BODY); oversize → 413, refused *before* the body is
     read (a declared-oversize Content-Length allocates nothing).
  2. Malformed Content-Length — int(header) raised an unhandled ValueError deep
     in _body(), surfacing as a 500/torn connection. Fix: guarded → 400.
  3. NO socket timeout (slowloris) — a slow client pinned a worker thread
     forever. Fix: Handler.timeout = SOCKET_TIMEOUT_S applied via setup().
  4. NO thread ceiling — ThreadingHTTPServer spawned one thread per connection
     unbounded (thread-exhaustion DoS). Fix: a BoundedSemaphore of
     MAX_CONCURRENT_REQUESTS acquired in the accept loop, released per worker.
  5. Unsynchronized egress counter — config.cloud_calls += 1 was a non-atomic
     load-add-store with no lock, so two concurrent cloud asks lost a count.
     Fix: bump_cloud_calls() guards the increment with a dedicated Lock.

A later refute pass (audit 2026-07-17) confirmed two gaps the first pass left:

  6. The socket timeout is PER-RECV, not a total-request deadline — a slow-POST
     that dribbles a byte just under it resets the clock forever, pinning a
     worker + a semaphore slot. Fix: MAX_REQUEST_BODY_SECONDS, a wall-clock cap
     on reading the whole body (read in bounded read1 slices against a deadline);
     exceeding it aborts the read → 408 and frees the worker/slot.
  7. A body the server can't length-delimit (Transfer-Encoding present, no
     usable Content-Length) was returned as b"" — silently accepted as empty, so
     /upload wrote a 0-byte file and answered ok. Fix: reject → 411, no artifact.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import dreamlayer.ai_brain.server.server as srv
from dreamlayer.ai_brain.server import Brain, make_brain_server


# ---------------------------------------------------------------------------
# helpers: spin a tokenless loopback Brain (the audit's threat model — an
# authed/loopback caller) and talk to it over real localhost HTTP.
# ---------------------------------------------------------------------------

def _serve(brain):
    server = make_brain_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = "127.0.0.1", server.server_address[1]
    return server, host, port


def _post(url, body, headers=None, timeout=10):
    data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers or {})
    # bypass any ambient HTTP proxy — this is a loopback call
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _raw_http(host, port, raw_request: bytes, read_timeout=10):
    """Send a hand-crafted request (so we can lie about Content-Length in ways
    urllib refuses to) and return the raw response bytes (empty on timeout)."""
    s = socket.create_connection((host, port), timeout=read_timeout)
    try:
        s.sendall(raw_request)
        s.settimeout(read_timeout)
        buf = b""
        while b"\r\n\r\n" not in buf:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
        return buf
    finally:
        s.close()


def _status_of(resp: bytes) -> int:
    if not resp:
        return 0
    try:
        return int(resp.split(b"\r\n", 1)[0].split(b" ")[1])
    except (IndexError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# 0. the caps/timeout/ceiling are module constants (documents the fix)
# ---------------------------------------------------------------------------

def test_hardening_constants_present_and_sane():
    assert srv.MAX_JSON_BODY == 16 * 1024 * 1024        # 16 MiB JSON-body cap
    assert srv.MAX_UPLOAD_BODY == 64 * 1024 * 1024      # 64 MiB upload cap
    assert srv.MAX_UPLOAD_BODY > srv.MAX_JSON_BODY      # uploads get the larger cap
    assert srv.SOCKET_TIMEOUT_S == 30.0                 # per-recv read timeout
    assert srv.MAX_REQUEST_BODY_SECONDS == 30.0         # wall-clock total-body deadline
    assert srv.MAX_CONCURRENT_REQUESTS == 64            # worker-thread ceiling


# ---------------------------------------------------------------------------
# 1. request-body size cap → 413 (not OOM)
# ---------------------------------------------------------------------------

def test_oversize_json_body_is_413_not_oom(tmp_path, monkeypatch):
    # Shrink the cap so we prove the behaviour without allocating 16 MiB. A body
    # over the cap must be refused with 413 — on revert _body() reads it whole
    # and /brain/ask answers 200.
    monkeypatch.setattr(srv, "MAX_JSON_BODY", 4096)
    server, host, port = _serve(Brain(tmp_path))
    try:
        oversize = b'{"query":"' + b"a" * 8000 + b'"}'   # ~8 KiB > 4 KiB cap
        status, _ = _post(f"http://{host}:{port}/dreamlayer/brain/ask", oversize)
        assert status == 413
    finally:
        server.shutdown(); server.server_close()


def test_within_cap_json_body_still_answers(tmp_path, monkeypatch):
    # a body under the cap is unaffected — the guard is a ceiling, not a wall.
    monkeypatch.setattr(srv, "MAX_JSON_BODY", 4096)
    server, host, port = _serve(Brain(tmp_path))
    try:
        status, body = _post(f"http://{host}:{port}/dreamlayer/brain/ask",
                             {"query": "hi"})
        assert status == 200
        assert "text" in json.loads(body)               # a normal Answer payload
    finally:
        server.shutdown(); server.server_close()


def test_declared_huge_content_length_refused_without_reading(tmp_path):
    # PROVES "do not allocate the whole body first": a request that *declares* a
    # gigabyte via Content-Length but sends almost nothing is rejected on the
    # header alone (413), promptly, without the server trying to read a GiB.
    server, host, port = _serve(Brain(tmp_path))
    try:
        raw = (b"POST /dreamlayer/brain/ask HTTP/1.1\r\n"
               b"Host: 127.0.0.1\r\n"
               b"Content-Type: application/json\r\n"
               b"Content-Length: 999999999\r\n"
               b"\r\n"
               b'{"q":1}')                               # only a few real bytes
        start = time.time()
        resp = _raw_http(host, port, raw, read_timeout=5)
        elapsed = time.time() - start
        assert _status_of(resp) == 413
        assert elapsed < 4.0                             # rejected on the header, not hung
    finally:
        server.shutdown(); server.server_close()


def test_upload_oversize_is_413(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "MAX_UPLOAD_BODY", 4096)
    brain = Brain(tmp_path)
    brain.reindex = lambda *a, **k: None                 # isolate the cap from indexing
    server, host, port = _serve(brain)
    try:
        q = urllib.parse.urlencode({"folder": str(tmp_path), "name": "big.bin"})
        status, _ = _post(f"http://{host}:{port}/dreamlayer/upload?{q}",
                          b"x" * 8192)                    # 8 KiB > 4 KiB upload cap
        assert status == 413
    finally:
        server.shutdown(); server.server_close()


def test_upload_uses_larger_cap_than_json(tmp_path, monkeypatch):
    # A payload larger than the JSON cap but under the upload cap is accepted on
    # the upload route yet rejected on a JSON route — proving the two caps are
    # distinct and _write_upload gets the bigger one.
    monkeypatch.setattr(srv, "MAX_JSON_BODY", 1024)
    monkeypatch.setattr(srv, "MAX_UPLOAD_BODY", 1 << 20)
    watched = tmp_path / "drop"
    watched.mkdir()
    brain = Brain(tmp_path)
    brain.config.folders = [str(watched)]                # a folder the Brain watches
    brain.reindex = lambda *a, **k: None
    server, host, port = _serve(brain)
    try:
        payload = b"y" * 4096                            # > 1 KiB JSON cap, < 1 MiB upload cap
        q = urllib.parse.urlencode({"folder": str(watched), "name": "f.txt"})
        up_status, up_body = _post(
            f"http://{host}:{port}/dreamlayer/upload?{q}", payload)
        assert up_status == 200                          # accepted under the upload cap
        assert json.loads(up_body)["ok"] is True
        assert (watched / "f.txt").read_bytes() == payload

        json_status, _ = _post(
            f"http://{host}:{port}/dreamlayer/brain/ask", payload)
        assert json_status == 413                        # same size, JSON cap, refused
    finally:
        server.shutdown(); server.server_close()


# ---------------------------------------------------------------------------
# 2. malformed Content-Length → 400 (not 500/traceback)
# ---------------------------------------------------------------------------

def test_malformed_content_length_is_400(tmp_path):
    server, host, port = _serve(Brain(tmp_path))
    try:
        raw = (b"POST /dreamlayer/brain/ask HTTP/1.1\r\n"
               b"Host: 127.0.0.1\r\n"
               b"Content-Type: application/json\r\n"
               b"Content-Length: not-a-number\r\n"
               b"\r\n"
               b'{"query":"hi"}')
        resp = _raw_http(host, port, raw, read_timeout=5)
        # fixed: a clean 400. reverted: int("not-a-number") raises, the handler
        # dies and the connection closes with no valid status line (→ 0).
        assert _status_of(resp) == 400
    finally:
        server.shutdown(); server.server_close()


# ---------------------------------------------------------------------------
# 3. socket timeout → slowloris can't pin a worker forever
# ---------------------------------------------------------------------------

def test_handler_carries_read_timeout(tmp_path):
    server, _, _ = _serve(Brain(tmp_path))
    try:
        assert server.RequestHandlerClass.timeout == srv.SOCKET_TIMEOUT_S
    finally:
        server.shutdown(); server.server_close()


def test_slowloris_connection_is_timed_out(tmp_path, monkeypatch):
    # Set a short read timeout (picked up at Handler-class definition inside
    # make_brain_server), then open a connection that promises a body and never
    # sends it. The server's read must time out and drop the worker well before
    # our generous client deadline. Reverted: no timeout, the read blocks
    # forever and the client hangs until its own 6 s deadline.
    monkeypatch.setattr(srv, "SOCKET_TIMEOUT_S", 0.5)
    server, host, port = _serve(Brain(tmp_path))
    try:
        s = socket.create_connection((host, port), timeout=6)
        s.sendall(b"POST /dreamlayer/brain/ask HTTP/1.1\r\n"
                  b"Host: 127.0.0.1\r\n"
                  b"Content-Length: 100\r\n\r\n")        # headers, then no body
        s.settimeout(6)
        start = time.time()
        try:
            chunk = s.recv(4096)                         # server closes on its read timeout
        except socket.timeout:
            chunk = b""
        elapsed = time.time() - start
        s.close()
        assert chunk == b""                              # server dropped the stalled worker
        assert elapsed < 5.0                             # via the 0.5 s timeout, not a hang
    finally:
        server.shutdown(); server.server_close()


# ---------------------------------------------------------------------------
# 4. bounded concurrency → no thread-exhaustion
# ---------------------------------------------------------------------------

def test_server_has_bounded_worker_semaphore(tmp_path):
    server, host, port = _serve(Brain(tmp_path))
    try:
        slots = getattr(server, "_slots", None)
        assert isinstance(slots, threading.BoundedSemaphore)
        assert slots._value == srv.MAX_CONCURRENT_REQUESTS
        # drive a burst, then confirm every acquired slot was released (no leak).
        errs = []

        def hit():
            try:
                st, _ = _post(f"http://{host}:{port}/dreamlayer/brain/ask",
                              {"query": "x"})
                if st != 200:
                    errs.append(st)
            except Exception as exc:                     # noqa: BLE001
                errs.append(str(exc))

        threads = [threading.Thread(target=hit) for _ in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errs == []
        # a worker releases its slot in a finally that runs just after the
        # client has its response, so poll briefly for the pool to drain.
        deadline = time.time() + 3.0
        while slots._value != srv.MAX_CONCURRENT_REQUESTS and time.time() < deadline:
            time.sleep(0.01)
        assert slots._value == srv.MAX_CONCURRENT_REQUESTS   # every slot returned, none leaked
    finally:
        server.shutdown(); server.server_close()


def test_concurrency_is_actually_capped(tmp_path, monkeypatch):
    # With the ceiling forced to 2, at most 2 handlers may run at once even
    # under 8 simultaneous requests — the accept loop blocks on the semaphore.
    # Reverted (thread-per-connection, no cap) all 8 run at once → cap exceeded.
    monkeypatch.setattr(srv, "MAX_CONCURRENT_REQUESTS", 2)
    brain = Brain(tmp_path)
    lock = threading.Lock()
    state = {"in_flight": 0, "max": 0}

    def slow_ask(*_a, **_k):
        with lock:
            state["in_flight"] += 1
            state["max"] = max(state["max"], state["in_flight"])
        time.sleep(0.15)
        with lock:
            state["in_flight"] -= 1
        return None                                      # → _answer_json(None), a 200

    brain.ask = slow_ask
    server, host, port = _serve(brain)
    try:
        errs = []

        def hit():
            try:
                st, _ = _post(f"http://{host}:{port}/dreamlayer/brain/ask",
                              {"query": "x"}, timeout=15)
                if st != 200:
                    errs.append(st)
            except Exception as exc:                     # noqa: BLE001
                errs.append(str(exc))

        threads = [threading.Thread(target=hit) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errs == []                                # every request still completed
        assert state["max"] <= 2                         # never more than the ceiling in flight
        assert state["max"] >= 1
    finally:
        server.shutdown(); server.server_close()


# ---------------------------------------------------------------------------
# 5. egress counter is synchronized → no lost increments
# ---------------------------------------------------------------------------

class _SlowInt(int):
    """An int whose addition sleeps, releasing the GIL *inside* the counter's
    read-modify-write window. This makes an unlocked ``x += 1`` lose updates
    deterministically (two threads read the same value, both store value+1) —
    while a lock around the increment still serializes to the exact total. It
    turns the concurrency bug into a reproducible one instead of a rare race."""

    def __add__(self, other):
        time.sleep(0.0005)                               # widen the RMW window, drop the GIL
        return _SlowInt(int(self) + int(other))

    __radd__ = __add__


def test_cloud_calls_counter_has_no_lost_increments(tmp_path, monkeypatch):
    import dreamlayer.ai_brain.server.backends as backends
    brain = Brain(tmp_path)
    # isolate the increment primitive: stub the network + the surrounding
    # activity-log/save I/O so concurrent asks race only on the counter.
    monkeypatch.setattr(backends, "cloud_chat", lambda cfg, q: "")
    brain.activity.add = lambda *a, **k: None
    brain.save = lambda *a, **k: None
    brain.config.cloud_calls = _SlowInt(0)               # deterministic RMW window

    n_threads, per = 8, 60

    def worker():
        for _ in range(per):
            brain._ask_cloud("q")                        # the real egress path

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # locked: exact. reverted (bare +=): the sleeping RMW window guarantees lost
    # updates, so the ledger undercounts and this fails.
    assert brain.config.cloud_calls == n_threads * per


def test_bump_cloud_calls_is_the_locked_primitive(tmp_path):
    # The helper exists, uses a dedicated lock (not the store lock), and is
    # atomic under contention.
    brain = Brain(tmp_path)
    assert brain._egress_lock is not brain._store_lock
    brain.config.cloud_calls = _SlowInt(0)

    n_threads, per = 8, 60

    def worker():
        for _ in range(per):
            brain.bump_cloud_calls()

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert brain.config.cloud_calls == n_threads * per


# ---------------------------------------------------------------------------
# 6. wall-clock body deadline → a byte-dribbling slow-POST can't pin a worker
# ---------------------------------------------------------------------------

def test_slow_post_body_cut_off_by_wall_clock_cap(tmp_path, monkeypatch):
    # A slow-POST that dribbles bytes FASTER than the per-recv socket timeout
    # (so that inactivity timeout never fires) but SLOWER than the total-body
    # deadline must be aborted by the wall-clock cap — reclaiming the worker and
    # its semaphore slot. The per-recv timeout is left at its generous 30 s to
    # make the point: it never trips here, yet the request is still cut off.
    # Reverted (no wall-clock cap): _read_capped's read(n) blocks reading the
    # whole body, each dribbled byte resetting the per-recv clock, so the request
    # runs the full ~12 s the dribble takes and the worker stays pinned.
    monkeypatch.setattr(srv, "MAX_REQUEST_BODY_SECONDS", 1.0)
    monkeypatch.setattr(srv, "MAX_CONCURRENT_REQUESTS", 4)
    brain = Brain(tmp_path)
    brain.reindex = lambda *a, **k: None
    server, host, port = _serve(brain)
    slots = server._slots
    try:
        body_len = 400                                   # dribbled 1/0.03 s ≈ 12 s total
        s = socket.create_connection((host, port), timeout=30)
        s.sendall(b"POST /dreamlayer/brain/ask HTTP/1.1\r\n"
                  b"Host: 127.0.0.1\r\n"
                  b"Content-Type: application/json\r\n"
                  b"Content-Length: " + str(body_len).encode() + b"\r\n\r\n")

        stop = threading.Event()

        def dribble():
            try:
                for _ in range(body_len):
                    if stop.is_set():
                        return
                    s.sendall(b"a")
                    time.sleep(0.03)
            except OSError:
                pass                                     # server closed on us — expected

        d = threading.Thread(target=dribble, daemon=True)
        start = time.time()
        d.start()
        s.settimeout(8)
        try:
            resp = s.recv(4096)                          # the 408, or a close/reset on abort
        except socket.timeout:
            resp = b"__timeout__"
        except OSError:
            resp = b"__reset__"
        elapsed = time.time() - start
        stop.set()
        s.close()
        d.join(timeout=2)

        # fixed: the 1 s wall-clock cap aborts the read well before the ~12 s the
        # full dribble would take — we never hang until our own 8 s recv deadline.
        assert resp != b"__timeout__"
        assert elapsed < 6.0
        if resp.startswith(b"HTTP"):
            assert _status_of(resp) == 408               # aborted → 408 Request Timeout
        # the worker released its semaphore slot when it aborted (no leak)
        deadline = time.time() + 3.0
        while slots._value != 4 and time.time() < deadline:
            time.sleep(0.01)
        assert slots._value == 4
    finally:
        server.shutdown(); server.server_close()


# ---------------------------------------------------------------------------
# 7. undelimitable body (chunked, no Content-Length) → 411, no 0-byte artifact
# ---------------------------------------------------------------------------

def test_chunked_upload_without_length_is_411_no_zero_byte_file(tmp_path):
    # A POST with Transfer-Encoding: chunked and no Content-Length. Python's
    # http.server does not decode chunked bodies, so on revert _read_capped
    # returns b"" and /upload writes a 0-byte file into the watched folder and
    # answers 200 ok. Fixed: rejected with 411 (Length Required) and no artifact.
    watched = tmp_path / "drop"
    watched.mkdir()
    brain = Brain(tmp_path)
    brain.config.folders = [str(watched)]                # a folder the Brain watches
    brain.reindex = lambda *a, **k: None
    server, host, port = _serve(brain)
    try:
        q = urllib.parse.quote(str(watched))
        raw = (b"POST /dreamlayer/upload?folder=" + q.encode() +
               b"&name=evil.txt HTTP/1.1\r\n"
               b"Host: 127.0.0.1\r\n"
               b"Content-Type: application/octet-stream\r\n"
               b"Transfer-Encoding: chunked\r\n"
               b"\r\n"
               b"5\r\nhello\r\n0\r\n\r\n")               # a real, undecoded chunked body
        resp = _raw_http(host, port, raw, read_timeout=5)
        assert _status_of(resp) in (411, 400)            # rejected, not silently empty
        assert not (watched / "evil.txt").exists()       # no 0-byte artifact written
    finally:
        server.shutdown(); server.server_close()


def test_empty_body_post_without_transfer_encoding_still_ok(tmp_path):
    # The finding-7 guard must reject ONLY a body it can't length-delimit — a
    # genuinely empty POST (no Transfer-Encoding, absent Content-Length) is still
    # a valid empty body for a route that allows it. Proves no over-rejection.
    brain = Brain(tmp_path)
    brain.reindex = lambda *a, **k: None                 # isolate from real indexing
    server, host, port = _serve(brain)
    try:
        raw = (b"POST /dreamlayer/reindex HTTP/1.1\r\n"
               b"Host: 127.0.0.1\r\n"
               b"\r\n")                                   # no Content-Length, no body
        resp = _raw_http(host, port, raw, read_timeout=5)
        assert _status_of(resp) == 200
    finally:
        server.shutdown(); server.server_close()
