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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, cast

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
                # decode=True yields bytes|None for a leaf part; the email
                # stub's return union is broader, so pin it to bytes.
                raw = cast(bytes, part.get_payload(decode=True) or b"")
                text = raw.decode(part.get_content_charset() or "utf-8",
                                  "ignore")
                break
    else:
        raw = cast(bytes, msg.get_payload(decode=True) or b"")
        text = raw.decode(msg.get_content_charset() or "utf-8", "ignore")
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
# Live feed — the recent messages your glasses read hands-free (the Mac is the
# bridge; the reading + reply happen on the glasses, not here).
# ---------------------------------------------------------------------------

def recent_messages(config=None, limit: int = 20) -> list[dict]:
    """Newest Messages + Mail as structured items for the glasses/phone to
    surface: {channel, who, from_me, text, subject?, ts}. [] off macOS."""
    if platform.system() != "Darwin":
        return []
    out = _recent_imessages(limit) + _recent_mail(limit)
    out.sort(key=lambda m: m.get("ts", 0), reverse=True)
    return out[:limit]


# Apple stores message dates as nanoseconds since 2001-01-01.
_APPLE_EPOCH = 978307200


def _recent_imessages(limit: int) -> list[dict]:
    p = Path(IMESSAGE_DB).expanduser()
    if not p.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT h.id, m.is_from_me, m.text, m.date "
            "FROM message m LEFT JOIN handle h ON m.handle_id = h.ROWID "
            "WHERE m.text IS NOT NULL ORDER BY m.date DESC LIMIT ?",
            (limit,)).fetchall()
        conn.close()
    except sqlite3.Error:
        return []
    out = []
    for who, is_me, text, date in rows:
        out.append({"channel": "imessage", "who": who or "unknown",
                    "from_me": bool(is_me), "text": (text or "").strip(),
                    "ts": _APPLE_EPOCH + (date or 0) / 1e9})
    return out


def _recent_mail(limit: int) -> list[dict]:
    root = Path(MAIL_ROOT).expanduser()
    if not root.is_dir():
        return []
    files = sorted(root.rglob("*.emlx"),
                   key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
    out = []
    for f in files:
        try:
            m = parse_emlx(f.read_bytes())
        except OSError:
            continue
        out.append({"channel": "email", "who": m["from"], "from_me": False,
                    "subject": m["subject"], "text": m["body"][:280],
                    "ts": f.stat().st_mtime})
    return out


# ---------------------------------------------------------------------------
# Calendar — sync macOS Calendar.app into the Brain's agenda (read-only).
#
# Same posture as Messages/Mail: local read via AppleScript, [] off macOS, and
# a `reader` seam so the parsing is unit-tested against fixture output without a
# real calendar. The reader returns tab-separated lines; we avoid AppleScript
# date math entirely by asking for *seconds from now*, then adding that to the
# Python clock — no locale-dependent date parsing.
# ---------------------------------------------------------------------------

def _calendar_script(days_ahead: int) -> str:
    """AppleScript that prints upcoming events as
    `title<TAB>seconds_from_now<TAB>location<TAB>calendar` lines."""
    return (
        'set out to ""\n'
        'set nowD to (current date)\n'
        f'set horizon to nowD + ({int(days_ahead)} * days)\n'
        'tell application "Calendar"\n'
        '  repeat with c in calendars\n'
        '    set cname to name of c\n'
        '    set evs to (every event of c whose start date is greater than or '
        'equal to nowD and start date is less than or equal to horizon)\n'
        '    repeat with e in evs\n'
        '      set t to summary of e\n'
        '      set secs to ((start date of e) - nowD)\n'
        '      set loc to ""\n'
        '      try\n'
        '        if location of e is not missing value then set loc to location of e\n'
        '      end try\n'
        '      set out to out & t & tab & (secs as integer) & tab & loc & tab '
        '& cname & linefeed\n'
        '    end repeat\n'
        '  end repeat\n'
        'end tell\n'
        'return out'
    )


def list_calendars(reader: Optional[Callable[[str], str]] = None) -> list[str]:
    """The names of every calendar in Calendar.app. [] off macOS."""
    if reader is None and platform.system() != "Darwin":
        return []
    run = reader or _osascript_out
    try:
        raw = run('tell application "Calendar" to get name of every calendar')
    except Exception:
        return []
    return [n.strip() for n in (raw or "").split(",") if n.strip()]


def read_calendar_events(config=None, days_ahead: int = 14,
                         reader: Optional[Callable[[str], str]] = None
                         ) -> list[dict]:
    """Upcoming Calendar.app events as {title, ts, place, calendar}.

    Restricted to `config.calendar_names` when that list is non-empty (empty =
    all calendars). [] off macOS unless a `reader` is injected (tests).
    """
    if reader is None and platform.system() != "Darwin":
        return []
    run = reader or _osascript_out
    days = int(getattr(config, "calendar_days", days_ahead) or days_ahead)
    try:
        raw = run(_calendar_script(days))
    except Exception:
        return []
    selected = {n for n in (getattr(config, "calendar_names", []) or [])}
    now = time.time()
    out: list[dict] = []
    for line in (raw or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        title, secs, loc, cal = parts[0].strip(), parts[1], parts[2].strip(), parts[3].strip()
        if not title:
            continue
        if selected and cal not in selected:
            continue
        try:
            ts = now + float(secs)
        except ValueError:
            continue
        out.append({"title": title, "ts": ts, "place": loc, "calendar": cal})
    out.sort(key=lambda e: e["ts"])
    return out


def _osascript_out(script: str) -> str:
    import subprocess
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=30)
    return r.stdout


# ---------------------------------------------------------------------------
# Contacts — sync macOS Contacts.app into the People registry (read-only).
# One reader, two homes: the Brain's People registry and (via the hub, when a
# face-embedding fn is present) the on-device face database.
# ---------------------------------------------------------------------------

def _contacts_script() -> str:
    return (
        'set out to ""\n'
        'tell application "Contacts"\n'
        '  repeat with p in people\n'
        '    set nm to name of p\n'
        '    set org to ""\n'
        '    try\n'
        '      if organization of p is not missing value then set org to organization of p\n'
        '    end try\n'
        '    set jt to ""\n'
        '    try\n'
        '      if job title of p is not missing value then set jt to job title of p\n'
        '    end try\n'
        '    set em to ""\n'
        '    try\n'
        '      if (count of emails of p) > 0 then set em to value of email 1 of p\n'
        '    end try\n'
        '    set out to out & nm & tab & org & tab & jt & tab & em & linefeed\n'
        '  end repeat\n'
        'end tell\n'
        'return out'
    )


def read_contacts(config=None, reader: Optional[Callable[[str], str]] = None) -> list[dict]:
    """macOS Contacts as {name, company, role, email}. [] off macOS."""
    if reader is None and platform.system() != "Darwin":
        return []
    run = reader or _osascript_out
    try:
        raw = run(_contacts_script())
    except Exception:
        return []
    out: list[dict] = []
    for line in (raw or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or not parts[0].strip():
            continue
        out.append({"name": parts[0].strip(), "company": parts[1].strip(),
                    "role": parts[2].strip(), "email": parts[3].strip()})
    return out


# ---------------------------------------------------------------------------
# Reminders — sync macOS Reminders.app open to-dos (read-only).
# ---------------------------------------------------------------------------

def _reminders_script() -> str:
    return (
        'set out to ""\n'
        'set nowD to (current date)\n'
        'tell application "Reminders"\n'
        '  repeat with lst in lists\n'
        '    set lname to name of lst\n'
        '    repeat with r in (reminders of lst whose completed is false)\n'
        '      set t to name of r\n'
        '      set secs to ""\n'
        '      try\n'
        '        if due date of r is not missing value then set secs to '
        '((due date of r) - nowD) as integer\n'
        '      end try\n'
        '      set out to out & t & tab & secs & tab & lname & linefeed\n'
        '    end repeat\n'
        '  end repeat\n'
        'end tell\n'
        'return out'
    )


def read_reminders(config=None, reader: Optional[Callable[[str], str]] = None) -> list[dict]:
    """Open macOS reminders as {title, ts, list}. ts is 0 when undated.
    Filtered to `config.reminder_lists` ([] = all). [] off macOS."""
    if reader is None and platform.system() != "Darwin":
        return []
    run = reader or _osascript_out
    try:
        raw = run(_reminders_script())
    except Exception:
        return []
    selected = {n for n in (getattr(config, "reminder_lists", []) or [])}
    now = time.time()
    out: list[dict] = []
    for line in (raw or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[0].strip():
            continue
        title, secs, lst = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if selected and lst not in selected:
            continue
        try:
            ts = now + float(secs) if secs else 0.0
        except ValueError:
            ts = 0.0
        out.append({"title": title, "ts": ts, "list": lst})
    out.sort(key=lambda e: (e["ts"] == 0, e["ts"]))       # dated first, by time
    return out


def list_reminder_lists(reader: Optional[Callable[[str], str]] = None) -> list[str]:
    if reader is None and platform.system() != "Darwin":
        return []
    run = reader or _osascript_out
    try:
        raw = run('tell application "Reminders" to get name of every list')
    except Exception:
        return []
    return [n.strip() for n in (raw or "").split(",") if n.strip()]


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
