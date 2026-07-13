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


def test_burn_already_gone_is_ok(tmp_path):
    assert cli.main(["memories", "burn", "--db", str(tmp_path / "gone.db"), "--yes"]) == 0
