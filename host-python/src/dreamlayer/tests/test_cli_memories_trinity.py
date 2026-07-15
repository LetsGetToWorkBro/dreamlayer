"""test_cli_memories_trinity.py — `dreamlayer memories export/import/burn`
(INNOVATION_SESSION 3.3): your data is one file — take it, restore it, or destroy
it. Burn is guarded behind --yes; import refuses to clobber without --force."""
from __future__ import annotations


from dreamlayer import cli


def _db(tmp_path, name="dreamlayer.db"):
    p = tmp_path / name
    p.write_bytes(b"SQLite format 3\x00memory")
    return p


def test_export_copies_the_file(tmp_path, capsys):
    db = _db(tmp_path)
    dest = tmp_path / "backup" / "mem.db"
    assert cli.main(["memories", "export", str(dest), "--db", str(db)]) == 0
    assert dest.exists() and dest.read_bytes() == db.read_bytes()
    assert "exported" in capsys.readouterr().out


def test_export_missing_db_guides(tmp_path, capsys):
    rc = cli.main(["memories", "export", str(tmp_path / "o.db"),
                   "--db", str(tmp_path / "nope.db")])
    assert rc == 2 and "no memory file" in capsys.readouterr().err


def test_export_refuses_under_veil_env_and_writes_no_dump(tmp_path, capsys, monkeypatch):
    """A raw copy is a full read of your memory, so it must be veil-gated exactly
    like `memories browse`: under an active veil, export refuses and leaves NO
    dump behind. Without the gate the owner could full-dump the very file that
    `browse` just refused to open. Fails on revert of the cmd_mem_export gate."""
    db = _db(tmp_path)
    dest = tmp_path / "backup" / "mem.db"
    monkeypatch.setenv("DREAMLAYER_VEIL", "1")
    rc = cli.main(["memories", "export", str(dest), "--db", str(db)])
    assert rc == 2 and "veil" in capsys.readouterr().err.lower()
    assert not dest.exists(), "no dump may be written under an active veil"


def test_export_refuses_under_veil_lockfile_and_writes_no_dump(tmp_path, capsys):
    db = _db(tmp_path)
    (tmp_path / "veil.lock").write_text("up", encoding="utf-8")   # veil beside the db
    dest = tmp_path / "backup" / "mem.db"
    rc = cli.main(["memories", "export", str(dest), "--db", str(db)])
    assert rc == 2 and "veil" in capsys.readouterr().err.lower()
    assert not dest.exists(), "no dump may be written under an active veil"


def test_import_restores_and_refuses_to_clobber(tmp_path, capsys):
    src = _db(tmp_path, "source.db")
    db = tmp_path / "dest.db"
    assert cli.main(["memories", "import", str(src), "--db", str(db)]) == 0
    assert db.exists() and db.read_bytes() == src.read_bytes()
    # second import without --force is refused
    assert cli.main(["memories", "import", str(src), "--db", str(db)]) == 2
    assert "already exists" in capsys.readouterr().err
    # with --force it overwrites
    assert cli.main(["memories", "import", str(src), "--db", str(db), "--force"]) == 0


def test_burn_requires_yes(tmp_path, capsys):
    db = _db(tmp_path)
    assert cli.main(["memories", "burn", "--db", str(db)]) == 2
    assert db.exists() and "without --yes" in capsys.readouterr().err
    assert cli.main(["memories", "burn", "--db", str(db), "--yes"]) == 0
    assert not db.exists()


def test_burn_takes_the_sidecars_with_it(tmp_path):
    """A burn must not leave siblings that outlive the memories they point
    at: the .usearch vectors, and the .ember practice file — whose engrams
    hold verbatim ANSWERS (docs/EMBER.md)."""
    db = _db(tmp_path)
    ann = tmp_path / "dreamlayer.db.usearch"
    ann.write_bytes(b"vectors")
    from dreamlayer.ember import EmberStore
    ember = tmp_path / "dreamlayer.db.ember"
    EmberStore(str(ember)).keep(
        "k1", "What did Maya say?",
        "Maya said her first full sentence in Spanish", 1_700_000_000.0)
    assert cli.main(["memories", "burn", "--db", str(db), "--yes"]) == 0
    assert not db.exists() and not ann.exists()
    assert not ember.exists(), "the answers must not outlive the burn"


def test_burn_already_gone_is_ok(tmp_path):
    assert cli.main(["memories", "burn", "--db", str(tmp_path / "gone.db"), "--yes"]) == 0
