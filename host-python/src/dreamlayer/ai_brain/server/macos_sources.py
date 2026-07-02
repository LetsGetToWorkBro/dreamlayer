"""ai_brain/server/macos_sources.py — read (and, with approval, send) Mail
and iMessage on a Mac mini.

These feed the Brain's index as extra "documents" so "ask your stuff" also
covers your messages and mail. Reading is local: iMessage from the Messages
SQLite db, Mail from the on-disk .emlx files. Nothing leaves the machine.

The parsing is pure and unit-tested against fixture data; the actual file/db
access only happens on macOS with the databases present (returns [] anywhere
else). Sending is deliberately gated: a draft is built, and it is only
dispatched through `send_message(draft, approved=True)` — an outbound action
is never taken silently.
"""
from __future__ import annotations

import email
import platform
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# default locations on macOS
IMESSAGE_DB = "~/Library/Messages/chat.db"
MAIL_ROOT = "~/Library/Mail"


# ---------------------------------------------------------------------------
# iMessage (SQLite)
# ---------------------------------------------------------------------------

def imessage_documents(db_path: str = IMESSAGE_DB, limit: int = 300
                       ) -> list[tuple[str, str]]:
    """Recent iMessages grouped by contact into (name, text) documents."""
    p = Path(db_path).expanduser()
    if not p.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT h.id, m.is_from_me, m.text "
            "FROM message m LEFT JOIN handle h ON m.handle_id = h.ROWID "
            "WHERE m.text IS NOT NULL "
            "ORDER BY m.date DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
    except sqlite3.Error:
        return []
    return _group_messages(rows)


def _group_messages(rows) -> list[tuple[str, str]]:
    """rows: (handle_id, is_from_me, text), newest first."""
    convos: dict[str, list[str]] = {}
    for handle, is_from_me, text in rows:
        who = handle or "unknown"
        line = ("Me: " if is_from_me else f"{who}: ") + (text or "").strip()
        convos.setdefault(who, []).append(line)
    docs = []
    for who, lines in convos.items():
        docs.append((f"iMessage · {who}", "\n".join(reversed(lines))))
    return docs


# ---------------------------------------------------------------------------
# Mail (.emlx)
# ---------------------------------------------------------------------------

def parse_emlx(raw: bytes) -> dict:
    """Parse one Apple Mail .emlx: a byte-count line, then an RFC-822 message."""
    nl = raw.find(b"\n")
    body = raw[nl + 1:] if nl != -1 and raw[:nl].strip().isdigit() else raw
    msg = email.message_from_bytes(body)
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                text = part.get_payload(decode=True) or b""
                text = text.decode(part.get_content_charset() or "utf-8",
                                   "ignore")
                break
    else:
        payload = msg.get_payload(decode=True)
        text = (payload or b"").decode(msg.get_content_charset() or "utf-8",
                                       "ignore")
    return {"from": msg.get("From", ""), "subject": msg.get("Subject", ""),
            "date": msg.get("Date", ""), "body": text.strip()}


def mail_documents(mail_root: str = MAIL_ROOT, limit: int = 200
                   ) -> list[tuple[str, str]]:
    root = Path(mail_root).expanduser()
    if not root.is_dir():
        return []
    files = sorted(root.rglob("*.emlx"),
                   key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
    docs = []
    for f in files:
        try:
            m = parse_emlx(f.read_bytes())
        except OSError:
            continue
        header = f"From {m['from']} — {m['subject']}"
        docs.append((f"Mail · {m['subject'][:40] or f.name}",
                     header + "\n" + m["body"]))
    return docs


def collect_documents(config) -> list[tuple[str, str]]:
    """All macOS message/mail documents for the Brain index. [] off macOS."""
    if platform.system() != "Darwin":
        return []
    docs = []
    docs += imessage_documents()
    docs += mail_documents()
    return docs


# ---------------------------------------------------------------------------
# Sending — draft → approve → send (never silent)
# ---------------------------------------------------------------------------

@dataclass
class MessageDraft:
    to: str
    text: str
    channel: str = "imessage"          # "imessage" | "email"
    subject: str = ""


def build_send_script(draft: MessageDraft) -> str:
    """The AppleScript that would send this draft (pure, testable)."""
    to = _osa_quote(draft.to)
    body = _osa_quote(draft.text)
    if draft.channel == "email":
        subj = _osa_quote(draft.subject)
        return (f'tell application "Mail"\n'
                f'  set m to make new outgoing message with properties '
                f'{{subject:{subj}, content:{body}, visible:false}}\n'
                f'  tell m to make new to recipient at end of to recipients '
                f'with properties {{address:{to}}}\n'
                f'  tell m to send\n'
                f'end tell')
    return (f'tell application "Messages"\n'
            f'  set svc to 1st service whose service type = iMessage\n'
            f'  send {body} to buddy {to} of svc\n'
            f'end tell')


def send_message(draft: MessageDraft, approved: bool,
                 executor: Optional[Callable[[str], None]] = None,
                 dry_run: bool = False) -> dict:
    """Dispatch a draft — only when explicitly approved.

    Nothing is sent unless approved is True. `executor(script)` runs the
    AppleScript (default: osascript on macOS); dry_run/off-macOS returns the
    script without running it, so you can preview exactly what would happen.
    """
    if not approved:
        raise PermissionError("draft not approved — outbound is never silent")
    script = build_send_script(draft)
    if dry_run or (executor is None and platform.system() != "Darwin"):
        return {"sent": False, "reason": "preview", "script": script}
    run = executor or _osascript
    run(script)
    return {"sent": True, "channel": draft.channel, "to": draft.to}


def _osascript(script: str) -> None:
    import subprocess
    subprocess.run(["osascript", "-e", script], check=True, timeout=15)


def _osa_quote(s: str) -> str:
    return '"' + re.sub(r'(["\\])', r'\\\1', s or "") + '"'
