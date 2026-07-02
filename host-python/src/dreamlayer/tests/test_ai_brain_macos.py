"""test_ai_brain_macos.py — the Mac mini extras: message/mail reading, the
draft→approve send gate, extra-document indexing, and auto-reindex."""
from __future__ import annotations

import sqlite3
from email.message import EmailMessage
from pathlib import Path

import pytest

from dreamlayer.ai_brain.server import BrainConfig, FileIndex, Brain
from dreamlayer.ai_brain.server.macos_sources import (
    imessage_documents, parse_emlx, mail_documents,
    MessageDraft, build_send_script, send_message,
)


# ---------------------------------------------------------------------------
# iMessage (fixture SQLite shaped like chat.db)
# ---------------------------------------------------------------------------

def _chat_db(path: Path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
    conn.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, "
                 "handle_id INT, is_from_me INT, text TEXT, date INT)")
    conn.execute("INSERT INTO handle VALUES (1, '+15551234'), (2, 'maya@x.com')")
    conn.executemany(
        "INSERT INTO message (handle_id, is_from_me, text, date) VALUES (?,?,?,?)",
        [(1, 0, "you around?", 30), (1, 1, "yep", 40),
         (2, 0, "bring the signed contract", 20)])
    conn.commit(); conn.close()


class TestIMessage:
    def test_reads_and_groups_by_contact(self, tmp_path):
        db = tmp_path / "chat.db"; _chat_db(db)
        docs = dict(imessage_documents(str(db)))
        assert "iMessage · +15551234" in docs
        convo = docs["iMessage · +15551234"]
        assert "you around?" in convo and "Me: yep" in convo
        assert "signed contract" in docs["iMessage · maya@x.com"]

    def test_missing_db_is_empty(self, tmp_path):
        assert imessage_documents(str(tmp_path / "nope.db")) == []


# ---------------------------------------------------------------------------
# Mail (.emlx)
# ---------------------------------------------------------------------------

def _emlx(subject, frm, body) -> bytes:
    m = EmailMessage()
    m["From"] = frm; m["Subject"] = subject; m["Date"] = "Mon, 1 Jan 2026"
    m.set_content(body)
    raw = m.as_bytes()
    return f"{len(raw)}\n".encode() + raw


class TestMail:
    def test_parse_emlx(self):
        m = parse_emlx(_emlx("Lunch?", "Maya <maya@x.com>", "Let's do Friday."))
        assert m["subject"] == "Lunch?" and "Friday" in m["body"]
        assert "maya@x.com" in m["from"]

    def test_mail_documents(self, tmp_path):
        (tmp_path / "a.emlx").write_bytes(
            _emlx("Invoice", "billing@co.com", "Amount due: 240."))
        docs = mail_documents(str(tmp_path))
        assert docs and "240" in docs[0][1] and "Invoice" in docs[0][0]


# ---------------------------------------------------------------------------
# Sending — the approve gate
# ---------------------------------------------------------------------------

class TestSend:
    def test_imessage_script(self):
        s = build_send_script(MessageDraft(to="+15551234", text='hi "there"'))
        assert "Messages" in s and "buddy" in s and '\\"there\\"' in s

    def test_email_script_has_subject(self):
        s = build_send_script(MessageDraft(
            to="a@b.com", text="body", channel="email", subject="Re: lease"))
        assert "Mail" in s and "Re: lease" in s

    def test_never_sends_without_approval(self):
        with pytest.raises(PermissionError):
            send_message(MessageDraft("x", "y"), approved=False)

    def test_preview_when_dry_run(self):
        out = send_message(MessageDraft("x", "y"), approved=True, dry_run=True)
        assert out["sent"] is False and "Messages" in out["script"]

    def test_approved_send_calls_executor_once(self):
        ran = []
        out = send_message(MessageDraft("x", "hello"), approved=True,
                           executor=lambda s: ran.append(s))
        assert out["sent"] is True and len(ran) == 1 and "hello" in ran[0]


# ---------------------------------------------------------------------------
# Index extras + auto-reindex
# ---------------------------------------------------------------------------

class TestExtraDocsAndWatch:
    def test_add_documents_are_searchable(self, tmp_path):
        idx = FileIndex(BrainConfig(folders=[]))
        idx.reindex()
        idx.add_documents([("iMessage · Maya", "Maya: bring the contract")])
        ans = idx.ask("who is bringing the contract")
        assert ans is not None and ans.sources == ["iMessage · Maya"]

    def test_email_docs_folded_into_the_brain(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(email_enabled=True).save(cfg)
        brain = Brain(cfg, sources_fn=lambda c: [
            ("iMessage · Maya", "Maya: the door code is 4417")])
        ans = brain.ask("what's the door code")
        assert ans is not None and "4417" in ans.text

    def test_poll_reindexes_on_change(self, tmp_path):
        watch = tmp_path / "w"; watch.mkdir()
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(folders=[str(watch)]).save(cfg)
        brain = Brain(cfg)
        assert brain.poll() is False               # nothing changed yet
        (watch / "new.md").write_text("Rent is 2400.")
        assert brain.poll() is True                # picked up the new file
        assert brain.ask("rent") is not None
        assert brain.poll() is False               # settled again
