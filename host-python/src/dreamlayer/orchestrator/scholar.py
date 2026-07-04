"""orchestrator/scholar.py — Scholar: read a question, a form, or dense text.

Look at a test question and the answer is on the glass; look at a form and each
field tells you what to write; look at a page of legal or technical language and
it comes back in plain words. Three faces of one move — capture the frame, hand
its text and your intent to the Brain, read back a tight, glanceable card —
differing only in *what* you ask for.

Privacy and tiering ride on the Brain seam: the read runs on your local vision
model first, the cloud only when opted in, never while incognito. `read_fn` is
injected (pure here) so the whole lens is testable offline; with no vision tier
it returns a clear "needs a brain" state rather than guessing.

The reply grammar is tight so the parse is unambiguous and the card is honest:

  answer   ANSWER: <the answer>
           WHY: <one short line of working>            (optional)

  form     SUMMARY: <what this form is, in a line>     (optional)
           FIELD: <label> — <exactly what to write>    (one per field)

  explain  GIST: <2–3 plain sentences>
           - <key point>                               (optional bullets)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as _field
from typing import Callable, Optional

from ..hud import cards

# read_fn(frame, prompt) -> the model's raw reply, or None when no tier can read.
ReadFn = Callable[[object, str], Optional[str]]

_ANSWER_PROMPT = (
    "You are helping someone read a question through smart glasses. Read the "
    "question visible in the image and answer it correctly and concisely. If it "
    "is multiple choice, give the correct option. Reply in exactly this form:\n"
    "ANSWER: <the answer>\n"
    "WHY: <one short line of reasoning>\n"
    "Add nothing else.{q}"
)

_FORM_PROMPT = (
    "You are helping someone fill out a form they are looking at through smart "
    "glasses{purpose}. Read the form and, for each field the person must fill in, "
    "say plainly what to write there — resolve confusing or legal wording into "
    "concrete guidance. Reply in this form:\n"
    "SUMMARY: <what this form is, one line>\n"
    "FIELD: <field label> — <exactly what to write, or how to decide>\n"
    "One FIELD line per field. Add nothing else."
)

_EXPLAIN_PROMPT = (
    "You are helping someone understand dense text they are looking at through "
    "smart glasses — legal, technical, or jargon-heavy. Summarize what it means "
    "in plain, simple language a non-expert grasps at a glance, and flag anything "
    "that commits them or carries risk. Reply in this form:\n"
    "GIST: <2 to 3 plain sentences>\n"
    "- <key point or watch-out>\n"
    "Add a few bullet lines only if they add something. Nothing else."
)


@dataclass
class ScholarResult:
    """What Scholar read back. `ok` is False when no tier could read the frame
    (offline / no vision brain) — the card then says so instead of guessing."""
    mode: str                         # "answer" | "form" | "explain"
    ok: bool
    primary: str                      # the answer / gist / form summary
    detail: str = ""                  # the "why", or a one-line note
    items: list = _field(default_factory=list)   # form fields / key points
    confidence: float = 0.0
    card: Optional[dict] = None


class Scholar:
    """Reads what you look at and hands it back understood.

    `read_fn(frame, prompt)` is the vision seam — your Brain's vision tier,
    injected by the hub. Pure and deterministic here so tests pin the reply.
    """

    def __init__(self, read_fn: Optional[ReadFn] = None):
        self.read_fn = read_fn

    # -- the three reads --------------------------------------------------

    def answer(self, frame, question: str = "") -> ScholarResult:
        """Answer the question in view (or a spoken one about it)."""
        q = f'\n\nThe person also asked: "{question.strip()}"' if question and question.strip() else ""
        raw = self._read(frame, _ANSWER_PROMPT.format(q=q))
        if raw is None:
            return self._unavailable("answer")
        ans = _tagged(raw, "ANSWER") or _first_line(raw)
        why = _tagged(raw, "WHY")
        if not ans:
            return self._unavailable("answer")
        conf = 0.85 if not _is_hedged(ans) else 0.55
        card = cards.scholar("answer", primary=ans, detail=why)
        return ScholarResult("answer", True, ans, why, [], conf, card)

    def form(self, frame, purpose: str = "") -> ScholarResult:
        """Read a form and say what to write in each field."""
        p = f' for this purpose: "{purpose.strip()}"' if purpose and purpose.strip() else ""
        raw = self._read(frame, _FORM_PROMPT.format(purpose=p))
        if raw is None:
            return self._unavailable("form")
        summary = _tagged(raw, "SUMMARY")
        fields = []
        for line in raw.splitlines():
            m = re.match(r"\s*FIELD\s*:\s*(.+)", line, re.IGNORECASE)
            if not m:
                continue
            body = m.group(1).strip()
            label, _, guide = body.partition("—")
            if not guide:
                label, _, guide = body.partition(" - ")
            if not guide:
                label, _, guide = body.partition(":")
            fields.append({"label": label.strip(" -:"), "guidance": guide.strip()})
        if not fields and not summary:
            return self._unavailable("form")
        primary = summary or f"{len(fields)} field{'s' if len(fields) != 1 else ''} to fill"
        card = cards.scholar("form", primary=primary,
                             items=[f"{f['label']}: {f['guidance']}" if f['guidance']
                                    else f['label'] for f in fields])
        return ScholarResult("form", True, primary, "", fields, 0.8, card)

    def explain(self, frame) -> ScholarResult:
        """Summarize dense text in plain language."""
        raw = self._read(frame, _EXPLAIN_PROMPT)
        if raw is None:
            return self._unavailable("explain")
        gist = _tagged(raw, "GIST") or _first_line(raw)
        if not gist:
            return self._unavailable("explain")
        points = [re.sub(r"^\s*[-•]\s*", "", ln).strip()
                  for ln in raw.splitlines()
                  if re.match(r"\s*[-•]\s+", ln)]
        card = cards.scholar("explain", primary=gist, items=points)
        return ScholarResult("explain", True, gist, "", points, 0.8, card)

    # -- internal ---------------------------------------------------------

    def _read(self, frame, prompt: str) -> Optional[str]:
        if self.read_fn is None:
            return None
        try:
            out = self.read_fn(frame, prompt)
        except Exception:
            return None
        out = (out or "").strip()
        return out or None

    def _unavailable(self, mode: str) -> ScholarResult:
        note = "Connect a Brain to read this"
        return ScholarResult(mode, False, "", note, [], 0.0,
                             cards.scholar(mode, primary="", detail=note,
                                           unavailable=True))


# --- parsing helpers ---------------------------------------------------------

def _tagged(text: str, tag: str) -> str:
    """The text after a leading 'TAG:' line, else ''."""
    m = re.search(rf"^\s*{tag}\s*:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else ""


def _first_line(text: str) -> str:
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if ln:
            return ln
    return ""


_HEDGE_WORDS = ("might", "maybe", "possibly", "perhaps", "unclear", "not sure",
                "i think", "probably", "roughly", "approximately", "unsure",
                "hard to say")


def _is_hedged(s: str) -> bool:
    low = (s or "").lower()
    return any(h in low for h in _HEDGE_WORDS)
