"""ai_brain/server/lexicon_live.py — a rare word heard in conversation, defined.

Someone says "undulating" mid-conversation and a quiet one-line definition
appears on the glass. The vocabulary half of the live fact-checker, and it hangs
off the same place: `EarHost.ingest_caption` (`ai_brain/server/ear.py`), which is
where transcribed lines actually arrive on the shipped Brain.

NOT `Orchestrator.ingest_caption`, deliberately. That is where the fact-check and
answer-ahead SIBLINGS live in the Orchestrator, and it is the obvious-looking
address — but nothing in the shipped Brain ever constructs an Orchestrator
(`decisions/0001`, and `ear.py`'s own header), so a Lexicon wired there would be
a feature no wearer could reach. The ear's caption path is the reachable one, and
it arrives with two properties this feature needs that the Orchestrator path
would have had to be taught: the Veil has already been applied, and the text has
already been through `default_redactor()`.

THE THREE THINGS THIS MODULE IS CAREFUL ABOUT
---------------------------------------------

**The word is taken from the REDACTED text.** `ingest_caption` runs the PII
scrub before anything downstream sees the utterance, and `note_transcript` is
called after it, like captions and the fact-checker are. Taking the word earlier
would mean a contact identifier could be handed to a third-party dictionary API
— the one thing this feature must never do.

**The rarity gate needs no model and no network.** It is a tokenizer, a length
test, a capitalisation test and a membership test against a bundled word list
(`assets/common_words.txt`). Pure logic, unit-testable, and it runs identically
on a Brain with nothing installed. In particular it does NOT consult
`object_lens/person_guard.label_is_a_person`: that layer is Presidio/spaCy-backed
(`person_guard.py:106`), i.e. a model, and a gate that only works when an
optional NLP pack is installed is a gate that is off on most machines. The
model-free stand-in is stricter than the model would be — see `is_rare`.

**Only the single word goes on the wire, never the utterance.** Enforced twice:
here, by only ever passing one token to the connector, and in the connector
itself, which refuses any query that is not a single lowercase alphabetic word
(`plugins/dictionaryapi.py:build_query`).

WHERE EACH GATE LIVES, AND WHY NOT ALL OF THEM ARE HERE
-------------------------------------------------------

* **Opt-in** (`lexicon_enabled`, default False) — read here, like the ear's other
  riders (`captions_enabled`, `fact_check_enabled`, `answer_ahead_enabled`).
  Reading it fails CLOSED: an unreadable config means the feature the wearer
  never switched on does not egress.
* **The Veil / the egress shield** — `Brain.incognito_now()`, re-checked here
  even though `ingest_caption` already returned on it, exactly as
  `note_speech_audio` re-checks the pipeline's own door: the caller may be
  something else tomorrow, and this is the check that must not be missed.
  Brain-side that ONE call is both gates the issue names — it is True while
  LAN-only (the egress shield), in quiet hours, and inside a private zone
  (`server.py:1735`) — so there is no second posture to consult and no second
  posture to fall out of step with. Fails CLOSED.
* **Focus** — NOT a check of its own. `Brain.push_event` is the one funnel every
  card goes through and where `focus_mode` is enforced (`FOCUS_HUSHED`), and the
  codebase's stated reason for keeping it there is that a parallel mechanism is
  "a second thing to keep in step". So `lexicon` is added to that set instead,
  and what this module does is consult the SAME predicate early
  (`_may_interrupt`) so a card that is certain to be hushed does not spend a
  network request first. Same mechanism, no drift, and it fails OPEN like every
  preference.
* **Fail quiet** — offline, no entry, a hostile body, a broken connector: no
  card, and never an error card. A missing definition is not an event.
"""
from __future__ import annotations

import logging
import pathlib
import re

log = logging.getLogger("dreamlayer.lexicon")

#: A candidate has to be at least this long. Zipf plus length does most of the
#: work: short words are overwhelmingly common ones, and a wearer being told
#: what "amber" means is the failure mode that makes a feature get switched off.
MIN_LEN = 8

#: …and no longer than this. Past it the token is far more likely to be an ASR
#: run-on or a compound the dictionary has no entry for than a word worth
#: defining, and it also bounds what can reach the connector.
MAX_LEN = 24

#: Words, keeping case (the capitalisation test needs it) and splitting on
#: everything else — so "mid-conversation" is two tokens and "don't" is one
#: non-alphabetic token that the alphabetic test then drops.
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z']*")

#: Endings stripped before the common-word test, so one list entry covers a whole
#: family — inflectional ("questions" → "question") and the productive
#: derivational ones English piles on top ("installation" → "install",
#: "attendance" → "attend", "historical" → "history").
#:
#: NOT a stemmer, and it never has to be RIGHT: it generates candidates, and a
#: candidate is only consulted, never trusted. Over-stripping is safe — "undulate"
#: is not on the list however it is cut. The only way this hurts is if a rare word
#: strips down to a common one, which is precisely the case where it IS a common
#: word wearing an ending, i.e. the case it exists to catch.
_SUFFIXES = ("ation", "ition", "ical", "ness", "ment", "less", "able", "ally",
             "ance", "ence", "ship", "ing", "est", "ful", "ies", "ous", "ive",
             "ist", "ion", "al", "ed", "er", "ly", "es", "s")

_ASSET = pathlib.Path(__file__).with_name("assets") / "common_words.txt"

_COMMON: frozenset = frozenset()


def common_words() -> frozenset:
    """The bundled common-word list, read once and cached.

    An unreadable or missing asset yields an EMPTY set, and the consequence is
    stated rather than hidden: with no list every long lowercase word looks
    rare, so `LexiconRead` refuses to run at all when the list is empty
    (`enabled`). Failing loud-but-silent that way is the only safe direction —
    a rarity gate that has lost its list would otherwise ship every long word a
    wearer says to a third party.
    """
    global _COMMON
    if _COMMON:
        return _COMMON
    try:
        raw = _ASSET.read_text(encoding="utf-8")
    except OSError as exc:                           # noqa: BLE001
        log.warning("[lexicon] word list unreadable: %s", type(exc).__name__)
        return _COMMON
    words = set()
    for line in raw.splitlines():
        w = line.strip().lower()
        if w and not w.startswith("#"):
            words.add(w)
    _COMMON = frozenset(words)
    return _COMMON


def tokens(text: str) -> list:
    """The utterance as words, case preserved. Never raises."""
    return _TOKEN_RE.findall(text or "")


def stems(word: str) -> list:
    """`word` plus the plausible bases it inflects from, nearest first.

    Two rounds, because English stacks endings: "wonderfully" needs
    -ly → "wonderful" → -ful → "wonder". Each strip also offers the two spelling
    repairs that matter — a restored silent -e ("moving" → "mov" → "move") and
    -i- back to -y ("companies" → "compan" → "company") — plus an undoubled
    final consonant ("running" → "runn" → "run").
    """
    out = [word]
    seen = {word}
    frontier = [word]
    for _round in range(2):
        nxt = []
        for w in frontier:
            for suf in _SUFFIXES:
                if len(w) <= len(suf) + 2 or not w.endswith(suf):
                    continue
                base = w[:-len(suf)]
                cands = [base, base + "e", base + "y"]
                if len(base) > 3 and base[-1] == base[-2]:
                    cands.append(base[:-1])
                for cand in cands:
                    if cand not in seen:
                        seen.add(cand)
                        nxt.append(cand)
                        out.append(cand)
        frontier = nxt
    return out


def is_common(word: str) -> bool:
    """Is this word — or any base it plausibly inflects from — on the list?"""
    known = common_words()
    if not known:
        return False
    return any(s in known for s in stems((word or "").lower()))


def is_rare(token: str) -> bool:
    """Is this RAW token (case as heard) worth offering a definition for?

    Four deterministic tests, and the second one is the name guard:

      * alphabetic — drops "don't", "3pm", hyphen fragments;
      * ALL LOWERCASE — a token with any capital is refused. That covers the
        proper nouns the issue asks to skip (a name, a place, a brand) and
        acronyms, without a model. It also refuses a legitimately rare word that
        happens to open a sentence, and that trade is deliberate and cheap: at
        most one lookup happens per utterance anyway, so declining the first
        token costs a card the wearer will get the next time the word is used
        mid-sentence — while the other direction would put a surname on the wire;
      * length, `MIN_LEN`..`MAX_LEN`;
      * not on the common-word list, after inflection stripping.

    An ASR that emits no capitalisation at all defeats the second test, which is
    why it is not the only defence: what reaches here has already been through
    the PII scrub, and only ever one word leaves the device.
    """
    t = token or ""
    if not t.isalpha() or t != t.lower():
        return False
    if not (MIN_LEN <= len(t) <= MAX_LEN):
        return False
    return not is_common(t)


def rare_word(text: str) -> str:
    """The ONE word in this utterance worth defining, or "".

    At most one per utterance by construction — a line with three unusual words
    is a line the wearer needs to follow, not three cards. The first one wins:
    it is the one they heard first and are still holding.
    """
    for token in tokens(text):
        if is_rare(token):
            return token
    return ""


class LexiconRead:
    """The Lexicon feature for ONE ear: the gate, the lookup and the card.

    Per-ear rather than per-Brain, like `TruthRead`, because the dedupe set is
    conversation state: the Mac's microphone and a phone streaming in are two
    different rooms, and a word already explained in one has not been explained
    in the other.
    """

    #: How many words to remember as already-defined. A long conversation should
    #: not grow this without bound; forgetting the oldest is the right failure
    #: (an hour later, a second card for the same word is reasonable).
    DEDUPE_MAX = 256

    def __init__(self, brain, define=None):
        self.brain = brain
        # The connector seam. None means "build the shipped one on first use" —
        # lazily, so importing this module never touches urllib and a Brain that
        # never enables Lexicon never builds a fetcher. Tests inject their own.
        self._define = define
        self._seen: dict = {}
        self.defined_count = 0
        self._proved = False

    # -- the switch --------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """The wearer's opt-in AND a usable word list.

        Both, because the second one is not a detail: with no list every long
        lowercase word reads as rare (`common_words`), so a Brain whose asset is
        missing must do nothing rather than define everything.
        """
        try:
            on = bool(getattr(self.brain.config, "lexicon_enabled", False))
        except Exception:                            # noqa: BLE001 — unreadable
            return False                             # → treat as off, never egress
        return on and bool(common_words())

    @property
    def proved(self) -> bool:
        """True only once a definition has genuinely reached the glass on this
        process — the same honesty bit `TruthRead.proved` and
        `EarHost._interpret_ok` carry. Wired is not working."""
        return self._proved

    def status(self) -> dict:
        return {"on": self.enabled, "proved": self._proved,
                "defined": self.defined_count}

    # -- the caption hook --------------------------------------------------

    def note_transcript(self, text: str) -> int:
        """One heard utterance → at most one definition card. Returns the number
        of surfaces the card reached (0 when nothing was drawn), so a caller can
        tell "looked, found nothing" from "never ran". Never raises.

        Called from `EarHost.ingest_caption` AFTER the PII scrub, so the word
        that can leave the device is a word that survived redaction.
        """
        if not self.enabled:
            return 0
        # The Veil, re-checked. `ingest_caption` already returned while veiled;
        # this is the check that has to hold if anything else ever calls here.
        # FAILS CLOSED — an unreadable posture is a veiled one, and this is the
        # one path in the ear that can put a word on the network.
        try:
            if bool(self.brain.incognito_now()):
                return 0
        except Exception:                            # noqa: BLE001
            return 0
        word = rare_word(text)
        if not word:
            return 0
        if word in self._seen:                       # already explained this session
            return 0
        # The interruption preference, read from the funnel's own predicate
        # BEFORE the lookup rather than after it. `push_event` would drop the
        # card anyway (`lexicon` is in `FOCUS_HUSHED`); asking first means Focus
        # does not silently cost a request per unusual word. Fails OPEN, like
        # every preference — an unreadable one must not silence the feature.
        try:
            if not self.brain._may_interrupt("lexicon"):
                return 0
        except Exception:                            # noqa: BLE001
            pass
        entry = self._lookup(word)
        sense = str((entry or {}).get("sense") or "").strip()
        # Mark it seen either way. A word with no entry is not worth asking about
        # twice in one conversation, and this is what keeps a proper noun that
        # slipped the capitalisation test from being sent more than once.
        self._remember(word)
        if not sense:
            return 0                                 # fail quiet: never an error card
        return self._draw(word, sense, str((entry or {}).get("part_of_speech") or ""))

    # -- internals ---------------------------------------------------------

    def _lookup(self, word: str) -> dict:
        """Define `word` through the connector seam, or `{}`.

        The shipped connector is built lazily and held, so its TTL cache
        survives across utterances — the same reason `world_lens` holds
        `off_barcode_fn` rather than rebuilding it per look.
        """
        # The consent gate, at the last point before anything can leave. The
        # feature's own `lexicon_enabled` switch is what the gate READS for this
        # sink, so this is not a second opt-in — it is the same one, asked from
        # the one place that also carries the Veil, counts what actually went
        # out, and puts this lookup on `/dreamlayer/status` beside every other
        # thing that can reach off-device. Checked HERE rather than only in
        # `note_transcript` so a future second caller cannot route around it.
        from .consent_gate import consent
        if not consent(self.brain).check("lexicon"):
            return {}
        if self._define is None:
            try:
                from ...plugins.dictionaryapi import _default_fetch, define_fn
                self._define = define_fn(_default_fetch)
            except Exception as exc:                 # noqa: BLE001
                log.warning("[lexicon] connector unavailable: %s",
                            type(exc).__name__)
                return {}
        try:
            got = self._define(word)
        except Exception as exc:                     # noqa: BLE001 — offline, a
            log.warning("[lexicon] lookup failed: %s",   # hostile body, anything
                        type(exc).__name__)
            return {}
        consent(self.brain).note("lexicon")          # a word genuinely left
        return got if isinstance(got, dict) else {}

    def _remember(self, word: str) -> None:
        self._seen[word] = True
        while len(self._seen) > self.DEDUPE_MAX:
            self._seen.pop(next(iter(self._seen)))

    def _draw(self, word: str, sense: str, part_of_speech: str) -> int:
        """Draw it. `veil_ok=False`: this card exists because of something the
        room said, so it has no business piercing the shield.

        NOT named `_push`, deliberately, and the reason is a tool rather than
        taste: `scripts/hud_reachability.py` reads any method named `_push` or
        `push_event` in a module as that module's card pusher, and infers WHICH
        argument holds the card from its arity. A three-argument `_push(word,
        sense, pos)` would make the checker resolve `sense` as the card, fail,
        and file this line on its "unresolved push site" list — a real blind
        spot manufactured out of a name. The card is built inline at the
        `push_event` call for the same reason: that is the shape the checker can
        read, and it is what `_answer_ahead` in `ear.py` already does.
        """
        try:
            from ...hud import cards
            pushed = self.brain.push_event("lexicon", cards.lexicon(
                word=word, sense=sense, part_of_speech=part_of_speech),
                veil_ok=False)
        except Exception as exc:                     # noqa: BLE001 — a definition
            log.warning("[lexicon] push failed: %s", type(exc).__name__)  # must
            return 0                                 # never cost the utterance
        if pushed:
            self._proved = True
            self.defined_count += 1
        return pushed
