"""test_windows_hygiene.py — the cross-platform sweep for the Windows Brain.

Silent POSIX assumptions the appliance would trip over on Windows, fixed with
tests: glibc-only strftime flags (%-I raises ValueError there), console-less
logging (a windowed exe has sys.stderr = None), the SO_REUSEADDR port-stealing
semantics, and utf-8 indexing regardless of the locale codepage.
"""
from __future__ import annotations

import logging
import os
import time

from dreamlayer.logging_setup import configure_logging
from dreamlayer.reality_compiler.v2.native import clock12


# -- the spoken clock: no glibc-only strftime ----------------------------------

def test_clock12_matches_the_old_glibc_format():
    # 14:05 → "2:05 PM", 00:07 → "12:07 AM" — exactly what %-I:%M %p printed
    two_pm = time.mktime((2026, 7, 16, 14, 5, 0, 0, 0, -1))
    assert clock12(two_pm) == "2:05 PM"
    past_midnight = time.mktime((2026, 7, 16, 0, 7, 0, 0, 0, -1))
    assert clock12(past_midnight) == "12:07 AM"
    noon = time.mktime((2026, 7, 16, 12, 0, 0, 0, 0, -1))
    assert clock12(noon) == "12:00 PM"


def test_no_glibc_strftime_flags_remain_in_the_engine():
    # %-I / %-d raise ValueError on Windows strftime; the engine must not
    # use them anywhere the Windows Brain runs
    import inspect
    import dreamlayer.ai_brain.server.server as srv
    import dreamlayer.ai_brain.server.brain_rc as rc
    import dreamlayer.orchestrator.orchestrator as orch
    for mod in (srv, rc, orch):
        assert "%-" not in inspect.getsource(mod), mod.__name__


def test_brain_memories_when_column_is_portable(tmp_path):
    # the memories view formats real timestamps; the old glibc-only
    # no-pad strftime flags crashed it on Windows — exercise a same-day
    # row (bare clock) and a far-out one (the month-day branch) end to end
    import json
    from dreamlayer.ai_brain.server import Brain
    cfg = tmp_path / "cfg"; cfg.mkdir()
    (cfg / "reminders.json").write_text(json.dumps(
        [{"title": "Renew the lease", "ts": time.time() + 30 * 86400,
          "list": "Home"}]))
    brain = Brain(cfg)
    brain.waypath_stash("bike", "the north rack")
    rows = brain.memories()["memories"]
    bike = next(r for r in rows if "bike" in r["summary"])
    assert ("AM" in bike["createdAt"]) or ("PM" in bike["createdAt"])
    lease = next(r for r in rows if "lease" in r["summary"])
    # "Jul 16, 2:05 PM" — month name + unpadded day, built portably
    assert any(m in lease["createdAt"] for m in
               ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
                "Sep", "Oct", "Nov", "Dec"))


# -- console-less logging: a windowed exe has no stderr -------------------------

def _dl_handlers():
    return [h for h in logging.getLogger().handlers
            if getattr(h, "_dreamlayer_handler", False)]


def test_explicit_log_file_wins(tmp_path, monkeypatch):
    target = tmp_path / "logs" / "brain.log"
    monkeypatch.setenv("DL_LOG_FILE", str(target))
    try:
        configure_logging()
        (h,) = _dl_handlers()
        assert isinstance(h, logging.handlers.RotatingFileHandler)
        assert h.baseFilename == str(target)
        logging.getLogger("dreamlayer.test").warning("hello file")
        h.flush()
        assert "hello file" in target.read_text()
    finally:
        monkeypatch.delenv("DL_LOG_FILE")
        for h in _dl_handlers():
            h.close()
        configure_logging()      # restore the plain stream handler


def test_windowed_process_logs_to_the_state_dir(tmp_path, monkeypatch):
    # pythonw / PyInstaller --windowed: sys.stderr is None. Nothing may
    # crash, and records must land under the state dir.
    import sys
    monkeypatch.setenv("DREAMLAYER_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "stderr", None)
    try:
        configure_logging()
        (h,) = _dl_handlers()
        assert isinstance(h, logging.handlers.RotatingFileHandler)
        assert h.baseFilename == str(tmp_path / "brain.log")
        logging.getLogger("dreamlayer.test").warning("no console")
        h.flush()
        assert "no console" in (tmp_path / "brain.log").read_text()
    finally:
        for h in _dl_handlers():
            h.close()
    monkeypatch.undo()
    configure_logging()


def test_console_processes_keep_stream_logging():
    configure_logging()
    (h,) = _dl_handlers()
    assert type(h) is logging.StreamHandler


# -- port-in-use fails loudly on Windows ----------------------------------------

def test_brain_server_reuse_address_is_posix_only(tmp_path):
    from dreamlayer.ai_brain.server import Brain
    from dreamlayer.ai_brain.server.server import make_brain_server
    import os
    cfg = tmp_path / "cfg"; cfg.mkdir()
    brain = Brain(cfg)
    srv = make_brain_server(brain, host="127.0.0.1", port=0)
    try:
        # POSIX keeps the TIME_WAIT-rebind convenience; on Windows
        # SO_REUSEADDR would let a second Brain steal a LISTENING :7777,
        # so there it must stay off and a busy port must fail loudly.
        assert srv.allow_reuse_address == (os.name != "nt")
    finally:
        srv.server_close()


# -- atomic store writes survive Windows share-mode contention -------------------

def test_replace_atomic_retries_through_reader_contention(tmp_path, monkeypatch):
    # On Windows, os.replace raises PermissionError while a reader holds the
    # destination open (no FILE_SHARE_DELETE). Caught live by the Windows CI
    # leg: the first such error killed a writer thread and lost every later
    # write. The store must ride out the transient and land the write.
    from dreamlayer.ai_brain.server import store as st
    src = tmp_path / "a.tmp"; src.write_text("new")
    dst = tmp_path / "a.json"; dst.write_text("old")
    real_replace, tries = os.replace, []

    def flaky(a, b):
        tries.append(1)
        if len(tries) < 3:                    # reader still has it open…
            raise PermissionError(5, "Access is denied")
        real_replace(a, b)                    # …then it lets go
    monkeypatch.setattr(st.os, "replace", flaky)
    st.replace_atomic(src, dst, delay=0.001)
    assert dst.read_text() == "new" and len(tries) == 3


def test_replace_atomic_fails_loudly_when_never_released(tmp_path, monkeypatch):
    from dreamlayer.ai_brain.server import store as st
    import pytest
    src = tmp_path / "a.tmp"; src.write_text("new")

    def always_denied(a, b):
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(st.os, "replace", always_denied)
    with pytest.raises(PermissionError):      # a real ACL problem still surfaces
        st.replace_atomic(src, tmp_path / "a.json", attempts=3, delay=0.001)


# -- indexing is utf-8 regardless of the locale codepage -------------------------

def test_index_reads_utf8_notes(tmp_path):
    from dreamlayer.ai_brain.server import BrainConfig, FileIndex
    notes = tmp_path / "notes"; notes.mkdir()
    (notes / "café.md").write_text("The café rendezvous — naïve résumé at 9.",
                                   encoding="utf-8")
    idx = FileIndex(BrainConfig(folders=[str(notes)]))
    idx.reindex()
    ans = idx.ask("when is the rendezvous")
    assert ans is not None and "café" in ans.text
