"""ai_brain/server/windows_sources.py — read local mail and calendar feeds on
a Windows PC, in the image of macos_sources.py.

Windows has no Apple Mail and no iMessage, and this module never pretends
otherwise: **Messages is honestly unavailable** (recent_messages carries only
mail; there is no message store to read and nothing here fakes one), and mail
comes only from a local **Thunderbird** profile when one exists — read-only,
parsed from the on-disk mbox files, nothing leaves the machine. Outlook is
deliberately not touched: scraping it silently via COM automation would break
the "you can see exactly what the Brain reads" contract; an Outlook seam, if
one ever lands, must be opt-in and surfaced in the panel like Mail/Messages
are on macOS.

Calendar mirrors the macOS injectable-seam design with the portable answer:
standard **.ics** files. Sources are ``<state dir>/calendars/*.ics`` (drop an
export or a subscription file in) plus any paths or ``http(s)`` URLs listed in
``config.calendar_ics``. URL feeds are fetched read-only and **never while
Incognito** (``network_mode == "lan_only"``) — adding one is a deliberate user
act, same as wiring any remote endpoint.

The parsing is pure and unit-tested against fixture data; the actual
file/profile access only happens on Windows with the files present (returns
[] anywhere else). Reader seams are injectable so tests run everywhere.
"""
from __future__ import annotations

import email
import email.utils
import os
import platform
import re
import time
from pathlib import Path
from typing import Callable, Optional, cast

# default Thunderbird profile root on Windows (%APPDATA%\Thunderbird\Profiles)
THUNDERBIRD_PROFILES = r"~\AppData\Roaming\Thunderbird\Profiles"

# never slurp a multi-GB mbox: read at most this many bytes from the tail
# (mbox appends, so the newest messages live at the end)
MBOX_TAIL_BYTES = 8_000_000


def _thunderbird_root() -> Path:
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        return Path(appdata) / "Thunderbird" / "Profiles"
    return Path(THUNDERBIRD_PROFILES).expanduser()


# ---------------------------------------------------------------------------
# Mail (Thunderbird mbox) — pure parsing
# ---------------------------------------------------------------------------

def _body_text(msg) -> str:
    """The text/plain body of an email.message.Message (same walk as the
    macOS parse_emlx)."""
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                raw = cast(bytes, part.get_payload(decode=True) or b"")
                text = raw.decode(part.get_content_charset() or "utf-8",
                                  "ignore")
                break
    else:
        raw = cast(bytes, msg.get_payload(decode=True) or b"")
        text = raw.decode(msg.get_content_charset() or "utf-8", "ignore")
    return text.strip()


def parse_mbox(raw: bytes, limit: int = 200) -> list[dict]:
    """Parse an mbox byte blob into the newest `limit` messages, oldest
    first: {from, subject, date, body, ts}. Pure.

    Messages are split on the classic ``From `` separator line; body lines
    the writer escaped as ``>From`` are unescaped (mboxrd). A leading partial
    message (from reading only the tail of a big file) is dropped by
    construction — everything before the first separator is ignored.
    """
    parts = re.split(rb"(?:^|\r?\n)From [^\n]*\n", raw)[1:]
    out: list[dict] = []
    for chunk in parts[-limit:]:
        # mboxrd: ">From ..." at line start was an escaped body line
        body_bytes = re.sub(rb"(?m)^>(>*From )", rb"\1", chunk)
        try:
            msg = email.message_from_bytes(body_bytes)
        except Exception:
            continue
        date = msg.get("Date", "")
        try:
            dt = email.utils.parsedate_to_datetime(date)
            ts = dt.timestamp() if dt else 0.0
        except (TypeError, ValueError):
            ts = 0.0
        out.append({"from": msg.get("From", ""),
                    "subject": msg.get("Subject", ""),
                    "date": date, "body": _body_text(msg), "ts": ts})
    return out


def _mbox_files(root: Path) -> list[Path]:
    """Thunderbird's mbox stores: every extensionless file that has a .msf
    index sibling (INBOX + INBOX.msf, under Mail/ and ImapMail/), newest
    activity first."""
    if not root.is_dir():
        return []
    boxes = []
    try:
        for msf in root.rglob("*.msf"):
            box = msf.with_suffix("")
            if box.is_file():
                boxes.append(box)
    except OSError:
        return []
    boxes.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return boxes


def _read_tail(path: Path, cap: int = MBOX_TAIL_BYTES) -> bytes:
    with path.open("rb") as f:
        size = path.stat().st_size
        if size > cap:
            f.seek(size - cap)
        return f.read()


def mail_documents(profiles_root: str | Path | None = None, limit: int = 200
                   ) -> list[tuple[str, str]]:
    """Recent Thunderbird mail as (name, text) documents for the index.
    [] when no profile exists."""
    root = Path(profiles_root) if profiles_root else _thunderbird_root()
    docs: list[tuple[str, str]] = []
    remaining = limit
    for box in _mbox_files(root):
        if remaining <= 0:
            break
        try:
            msgs = parse_mbox(_read_tail(box), remaining)
        except OSError:
            continue
        for m in reversed(msgs):                     # newest first
            header = f"From {m['from']} — {m['subject']}"
            docs.append((f"Mail · {m['subject'][:40] or box.name}",
                         header + "\n" + m["body"]))
            remaining -= 1
            if remaining <= 0:
                break
    return docs


def collect_documents(config) -> list[tuple[str, str]]:
    """All Windows mail documents for the Brain index. [] off Windows.

    The honest Windows counterpart of macos_sources.collect_documents:
    Thunderbird mail only — there is no iMessage store on Windows, so
    nothing is invented for it.
    """
    if platform.system() != "Windows":
        return []
    return mail_documents()


# ---------------------------------------------------------------------------
# Live feed — recent mail for the glasses/phone to surface. Mail only:
# iMessage does not exist on Windows and is reported honestly absent
# (no imessage-channel items are ever fabricated here).
# ---------------------------------------------------------------------------

def recent_messages(config=None, limit: int = 20) -> list[dict]:
    """Newest Thunderbird mail as structured items: {channel:"email", who,
    from_me, subject, text, ts}. [] off Windows."""
    if platform.system() != "Windows":
        return []
    out: list[dict] = []
    for box in _mbox_files(_thunderbird_root())[:8]:
        try:
            msgs = parse_mbox(_read_tail(box), limit)
        except OSError:
            continue
        for m in msgs:
            out.append({"channel": "email", "who": m["from"], "from_me": False,
                        "subject": m["subject"], "text": m["body"][:280],
                        "ts": m["ts"] or box.stat().st_mtime})
    out.sort(key=lambda m: m.get("ts", 0), reverse=True)
    return out[:limit]


# ---------------------------------------------------------------------------
# Calendar — .ics files/URLs → agenda, through the same start_calendar_sync()
# seam the macOS Calendar.app reader uses. Parsing is pure; the source list
# (`reader` seam) is injectable for tests.
# ---------------------------------------------------------------------------

def _default_calendar_dir() -> Path:
    """<state dir>/calendars — drop .ics files here and they're synced."""
    base = os.environ.get("DREAMLAYER_DIR", str(Path.home() / ".dreamlayer"))
    return Path(base) / "calendars"


def _unescape_ics(s: str) -> str:
    return (s.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\"))


def _unfold(text: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with SPACE/TAB continues the
    previous one."""
    lines: list[str] = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_ics_dt(value: str, params: str) -> float | None:
    """One DTSTART value → a unix timestamp. Handles UTC (Z suffix),
    floating/TZID-local (treated as local clock time — honest approximation,
    stated in the docs), and all-day VALUE=DATE. None when unparseable."""
    v = value.strip()
    try:
        if re.fullmatch(r"\d{8}", v):                       # all-day
            return time.mktime(time.strptime(v, "%Y%m%d"))
        if v.endswith("Z"):
            from calendar import timegm
            return float(timegm(time.strptime(v, "%Y%m%dT%H%M%SZ")))
        return time.mktime(time.strptime(v, "%Y%m%dT%H%M%S"))
    except ValueError:
        return None


def ics_events(text: str, calendar: str = "", now: float | None = None,
               days_ahead: int = 14) -> list[dict]:
    """Upcoming VEVENTs in one .ics payload as {title, ts, place, calendar},
    sorted by time. Pure — fixture-tested.

    Only events inside [now, now + days_ahead] are returned, matching the
    macOS reader's window. Recurring events (RRULE) contribute only their
    literal DTSTART — honest scope, stated in the Windows docs.
    """
    t0 = time.time() if now is None else now
    horizon = t0 + days_ahead * 86400
    cal_name = calendar
    events: list[dict] = []
    cur: dict | None = None
    for line in _unfold(text):
        key, _, value = line.partition(":")
        name, _, params = key.partition(";")
        name = name.upper().strip()
        if name == "X-WR-CALNAME" and not calendar:
            cal_name = _unescape_ics(value.strip()) or cal_name
        elif name == "BEGIN" and value.strip().upper() == "VEVENT":
            cur = {"title": "", "ts": None, "place": ""}
        elif cur is not None:
            if name == "SUMMARY":
                cur["title"] = _unescape_ics(value.strip())
            elif name == "LOCATION":
                cur["place"] = _unescape_ics(value.strip())
            elif name == "DTSTART":
                cur["ts"] = _parse_ics_dt(value, params)
            elif name == "END" and value.strip().upper() == "VEVENT":
                ts = cur.get("ts")
                if cur["title"] and ts is not None and t0 - 3600 <= ts <= horizon:
                    events.append({"title": cur["title"], "ts": float(ts),
                                   "place": cur["place"],
                                   "calendar": cal_name or "Calendar"})
                cur = None
    events.sort(key=lambda e: e["ts"])
    return events


def _fetch_ics_url(url: str, timeout: float = 10.0) -> str:
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def _calendar_source_name(src: str) -> str:
    """A human name for one source: the file stem, or the URL's last path
    piece / host."""
    if src.startswith(("http://", "https://")):
        from urllib.parse import urlparse
        u = urlparse(src)
        leaf = Path(u.path).stem
        return leaf or u.netloc or src
    return Path(src).stem


def load_ics_sources(config=None,
                     fetcher: Optional[Callable[[str], str]] = None
                     ) -> list[tuple[str, str]]:
    """Every configured calendar source as (name, ics_text).

    Sources: ``<state dir>/calendars/*.ics`` plus config.calendar_ics
    (paths or URLs). URL feeds are skipped entirely while the network
    posture is lan_only (Incognito) — a private stretch fetches nothing.
    """
    out: list[tuple[str, str]] = []
    lan_only = bool(getattr(config, "lan_only", False))
    fetch = fetcher or _fetch_ics_url
    paths: list[str] = []
    cal_dir = _default_calendar_dir()
    if cal_dir.is_dir():
        paths += sorted(str(p) for p in cal_dir.glob("*.ics"))
    paths += [s for s in (getattr(config, "calendar_ics", []) or [])]
    seen = set()
    for src in paths:
        if src in seen:
            continue
        seen.add(src)
        try:
            if src.startswith(("http://", "https://")):
                if lan_only:
                    continue            # Incognito: no fetches, period
                text = fetch(src)
            else:
                text = Path(src).expanduser().read_text(errors="ignore")
        except Exception:
            continue
        out.append((_calendar_source_name(src), text))
    return out


def read_calendar_events(config=None, days_ahead: int = 14,
                         reader: Optional[Callable[[], list[tuple[str, str]]]] = None
                         ) -> list[dict]:
    """Upcoming events from every .ics source as {title, ts, place, calendar}.

    Restricted to `config.calendar_names` when that list is non-empty (empty =
    all calendars) — identical semantics to the macOS reader. [] off Windows
    unless a `reader` is injected (tests).
    """
    if reader is None and platform.system() != "Windows":
        return []
    days = int(getattr(config, "calendar_days", days_ahead) or days_ahead)
    try:
        sources = reader() if reader is not None else load_ics_sources(config)
    except Exception:
        return []
    selected = {n for n in (getattr(config, "calendar_names", []) or [])}
    out: list[dict] = []
    for name, text in sources:
        for e in ics_events(text, calendar=name, days_ahead=days):
            if selected and e["calendar"] not in selected:
                continue
            out.append(e)
    out.sort(key=lambda e: e["ts"])
    return out


def list_calendars(reader: Optional[Callable[[], list[tuple[str, str]]]] = None,
                   config=None) -> list[str]:
    """The names of every configured .ics source (for the panel's picker).
    [] off Windows unless a `reader` is injected (tests)."""
    if reader is None and platform.system() != "Windows":
        return []
    try:
        sources = reader() if reader is not None else load_ics_sources(config)
    except Exception:
        return []
    names: list[str] = []
    for name, text in sources:
        # prefer the calendar's own name when the payload declares one
        evs_name = name
        for line in _unfold(text):
            if line.upper().startswith("X-WR-CALNAME"):
                evs_name = _unescape_ics(line.partition(":")[2].strip()) or name
                break
        if evs_name not in names:
            names.append(evs_name)
    return names
