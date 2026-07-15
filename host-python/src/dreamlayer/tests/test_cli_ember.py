"""test_cli_ember.py — `dreamlayer ember` through cli.main (exit codes + output).

`log --answers` additionally prints the verbatim ANSWER each cue guards, so it is
veil-gated exactly like `memories browse`: reading answers is reading memory. An
active veil ($DREAMLAYER_VEIL or a veil.lock beside the db) must block it, and no
answer may leak to stdout when refused. The veil tests fail on revert of the
cmd_ember_log gate."""
from __future__ import annotations

from dreamlayer import cli
from dreamlayer.ember import EmberStore

NOW = 1_700_000_000.0
CUE = "What did Maya say?"
ANSWER = "Maya said her first full sentence in Spanish"


def _store_beside(tmp_path):
    """A memory db plus its <db>.ember sidecar holding one engram (cue + answer),
    the layout cmd_ember_log resolves from --db."""
    db = tmp_path / "dreamlayer.db"
    db.write_bytes(b"SQLite format 3\x00")
    EmberStore(str(db) + ".ember").keep("k1", CUE, ANSWER, NOW)
    return db


def test_ember_log_is_cues_only_by_default(tmp_path, capsys):
    db = _store_beside(tmp_path)
    rc = cli.main(["ember", "log", "--db", str(db)])
    out = capsys.readouterr().out
    assert rc == 0 and CUE in out and ANSWER not in out


def test_ember_log_answers_prints_the_answer(tmp_path, capsys):
    db = _store_beside(tmp_path)
    rc = cli.main(["ember", "log", "--answers", "--db", str(db)])
    out = capsys.readouterr().out
    assert rc == 0 and CUE in out and ANSWER in out


def test_ember_log_answers_refuses_under_veil_env(tmp_path, capsys, monkeypatch):
    db = _store_beside(tmp_path)
    monkeypatch.setenv("DREAMLAYER_VEIL", "1")
    rc = cli.main(["ember", "log", "--answers", "--db", str(db)])
    cap = capsys.readouterr()
    assert rc == 2 and "veil" in cap.err.lower()
    assert ANSWER not in cap.out, "an answer must not leak when the veil refuses"


def test_ember_log_answers_refuses_under_veil_lockfile(tmp_path, capsys):
    db = _store_beside(tmp_path)
    (tmp_path / "veil.lock").write_text("up", encoding="utf-8")   # veil beside the db
    rc = cli.main(["ember", "log", "--answers", "--db", str(db)])
    cap = capsys.readouterr()
    assert rc == 2 and "veil" in cap.err.lower()
    assert ANSWER not in cap.out, "an answer must not leak when the veil refuses"
