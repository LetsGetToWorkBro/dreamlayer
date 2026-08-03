"""One ONNX engine behind every voice seam — `onnx_speech`, Brain-side.

WHAT WAS MISSING
----------------
`orchestrator/sherpa_backend.py` is a complete, tested wrapper around
sherpa-onnx: ASR, VAD, speaker embedding, keyword spotting, diarization and
audio tagging, six drop-in adapters for the seams the capture pipeline already
takes. Nothing constructed it. Its only intended consumer was the `Orchestrator`
the shipped Brain never builds (`decisions/0001`).

The report's own reading of this was subtler than the usual case and worth
recording. `onnx_speech` sits in `EAR_CAPS`, so it LOOKS driven — but `ear.py`
says so itself, in a comment older than this file: *"make_asr picks Moonshine
XOR faster-whisper (never sherpa/onnx), so onnx_speech is never on the ear's
path"*. `EAR_CAPS` is the set the ear FILTERS against, not the set it claims,
and the ear was honest throughout. The capability simply had no rung.

WHAT THIS ADDS, AND WHERE IT SITS IN EACH LADDER
------------------------------------------------
A wearer who points the Brain at one sherpa model directory gets whichever of
the six the directory actually contains. Each is offered as a FALLBACK, never a
displacement:

    ASR       Moonshine  →  faster-whisper  →  **sherpa**
    VAD       silero     →  **sherpa**
    wake      openWakeWord → **sherpa KWS**   (see the licence note below)
    tagger    PANNs      →  **sherpa** (already, via `sound_events`)
    speaker   ECAPA      →  **sherpa**

Fallback rather than preference is the floor rule applied to a whole stack:
installing sherpa must never take a working purpose-built engine away from a
wearer who already had one. It fills gaps, and on a machine with none of the
dedicated wheels it fills all of them from a single install — which is the
capability's actual pitch.

THE TRAP THIS FILE EXISTS TO AVOID
----------------------------------
Every adapter in `sherpa_backend` degrades to a null when its handle is absent:
`SherpaASR.transcribe` returns "", `SherpaWakeWord.detect` returns
`(False, 0.0)` — and `SherpaVAD.is_speech` returns **True**, which is the seam
rule (no gate means do not drop audio) and would silently disable voice
activity detection for the whole session if handed to the pipeline.

So an adapter is only ever offered when its model handle genuinely LOADED.
`SherpaSpeech` builds all six unconditionally and leaves the unloadable ones
holding `_impl=None`; handing one of those to the ear would be a seam that can
only ever return its own null, reported as an engine. Same test `_diarizer` and
`_wake_engine` apply, for the same reason.

LICENCE
-------
`SherpaWakeWord`'s own docstring notes the difference and it is not cosmetic:
sherpa-onnx is Apache-2.0 while openWakeWord is non-commercial. That is a
reason a shipping product might want the sherpa rung FIRST for wake rather than
second — a decision for whoever ships this, not one to make silently here, so
the ladder keeps the existing engine first and this note is the flag.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("dreamlayer.sherpa_live")

#: Env fallback for the model directory, matching `$DL_MOONSHINE_DIR` and
#: `$DL_AUDIO_TAG_DIR`. `config.sherpa_model_dir` wins — the bundled .app has no
#: environment of its own to edit, which is the same gap `dream_model_path` was
#: added to close.
ENV_DIR = "DL_SHERPA_DIR"

#: Filenames inside the model directory, per capability. Nothing is bundled or
#: fetched: the wearer drops a standard sherpa-onnx export in and whichever
#: capabilities are complete light up. A partial directory disables only its own
#: rung — never half-loads one, which is what `find_moonshine_dir` already does
#: for its export.
LAYOUT = {
    "asr": ("tokens.txt", "encoder.onnx", "decoder.onnx", "joiner.onnx"),
    "vad": ("silero_vad.onnx",),
    "speaker": ("speaker.onnx",),
    "kws": ("kws-tokens.txt", "kws-encoder.onnx", "kws-decoder.onnx",
            "kws-joiner.onnx", "keywords.txt"),
    "tag": ("tag.onnx", "tag-labels.csv"),
}


def _dir(brain) -> str:
    got = ""
    try:
        got = (getattr(brain.config, "sherpa_model_dir", "") or "").strip()
    except Exception:                                # noqa: BLE001
        got = ""
    return got or (os.environ.get(ENV_DIR, "") or "").strip()


def _have(root: str, group: str) -> bool:
    """Whether every file this capability needs is present."""
    from pathlib import Path
    d = Path(root)
    try:
        return all((d / f).is_file() for f in LAYOUT[group])
    except OSError:
        return False


def build_config(root: str):
    """A `SherpaConfig` naming only the models the directory actually holds.

    Fields left None disable their own adapter inside `SherpaSpeech`, so a
    directory with just a VAD model produces a stack offering exactly one thing
    — which is the honest result and not an error.
    """
    from pathlib import Path

    from ...orchestrator.sherpa_backend import SherpaConfig
    d = Path(root)
    cfg = SherpaConfig()
    if _have(root, "asr"):
        cfg.asr_tokens = str(d / "tokens.txt")
        cfg.asr_encoder = str(d / "encoder.onnx")
        cfg.asr_decoder = str(d / "decoder.onnx")
        cfg.asr_joiner = str(d / "joiner.onnx")
    if _have(root, "vad"):
        cfg.vad_model = str(d / "silero_vad.onnx")
    if _have(root, "speaker"):
        cfg.speaker_model = str(d / "speaker.onnx")
    if _have(root, "kws"):
        cfg.kws_tokens = str(d / "kws-tokens.txt")
        cfg.kws_encoder = str(d / "kws-encoder.onnx")
        cfg.kws_decoder = str(d / "kws-decoder.onnx")
        cfg.kws_joiner = str(d / "kws-joiner.onnx")
        cfg.kws_keywords_file = str(d / "keywords.txt")
    if _have(root, "tag"):
        cfg.tag_model = str(d / "tag.onnx")
        cfg.tag_labels = str(d / "tag-labels.csv")
    return cfg


class SherpaStack:
    """The Brain's one sherpa engine, built on first use and held."""

    def __init__(self, brain, _stack=None):
        self.brain = brain
        self._stack = _stack
        self._built = _stack is not None
        self.root = ""
        #: Outputs a sherpa adapter genuinely produced. The promotion proof —
        #: a loaded model is not a model that answered, and every adapter here
        #: has a null it can return forever.
        self.outputs = 0

    # ----------------------------------------------------------------- build

    def stack(self):
        if not self._built:
            self._built = True
            self.root = _dir(self.brain)
            if not self.root:
                return None                      # nothing configured; not a fault
            try:
                from ...orchestrator.sherpa_backend import SherpaSpeech
                s = SherpaSpeech(build_config(self.root))
                self._stack = s if s.available else None
            except Exception as exc:             # noqa: BLE001
                log.info("[sherpa] engine unavailable: %s", type(exc).__name__)
                self._stack = None
        return self._stack

    def _loaded(self, name: str):
        """The named adapter, ONLY if its model handle is really there.

        `SherpaSpeech` builds all six whatever the directory held, leaving the
        unloadable ones with `_impl=None`. Those are not engines — they are
        nulls wearing an engine's contract, and `SherpaVAD` in that state
        answers True to everything, which would disable voice detection for the
        session while every status surface reported a VAD running.
        """
        s = self.stack()
        if s is None:
            return None
        got = getattr(s, name, None)
        return got if getattr(got, "_impl", None) is not None else None

    # ------------------------------------------------------- the seam rungs

    def asr(self):
        return self._counted(self._loaded("asr"), "transcribe")

    def vad(self):
        return self._counted(self._loaded("vad"), "is_speech")

    def wake(self):
        return self._counted(self._loaded("wake"), "detect")

    def speaker(self):
        """The embedding extractor — LOADABLE, and deliberately not consumed.

        This is the one rung left unwired, and the reason is not effort. A
        voiceprint is only meaningful against prints from the SAME model: an
        ECAPA embedding and a sherpa embedding are vectors in unrelated spaces,
        and `voice_guard`'s cosine similarity would compare them anyway. So
        slotting this under `_voice_seam` would, for a wearer with people
        already enrolled, silently stop matching everyone they know — or worse,
        match the wrong person at a threshold tuned for a different model.

        Doing it properly means storing which model produced each print and
        re-enrolling on a change, which is a migration with its own consent
        surface, not a ladder rung. It is exposed and tested here so the work is
        a wiring job when somebody takes it on, and left out of `offers()` so no
        surface reports a rung nothing consumes.
        """
        return self._counted(self._loaded("speaker"), "embed")

    def tagger(self):
        # `SherpaSpeech` calls this handle `tagger`; `LAYOUT` calls its file
        # group `tag`. Two namespaces, and passing the wrong one silently
        # returns None for a model that loaded fine.
        return self._counted(self._loaded("tagger"), "tag")

    def _counted(self, adapter, method: str):
        """Wrap one call so a REAL answer moves the proof counter.

        Counted at the adapter rather than at each call site because the call
        sites are five different ladders in three files, and a counter that any
        one of them could forget to bump is a counter that reports the engine
        dormant on a machine where it is doing all the work.

        Only a non-empty answer counts. Every adapter's null — "", [], False,
        (False, 0.0) — is exactly what it returns with no model, so counting
        those would put us back at "the wheel is installed".
        """
        if adapter is None:
            return None
        real = getattr(adapter, method)

        # `functools.wraps` is load-bearing, not tidiness. `CapturePipeline._tag`
        # probes the tagger's SIGNATURE to decide whether to pass `sample_rate=`
        # — written precisely because `SherpaAudioTagger.tag` does not take one
        # — and a bare `(*a, **kw)` wrapper advertises `**kwargs`, so the probe
        # would start passing an argument the real method rejects. `wraps` sets
        # `__wrapped__`, which `inspect.signature` follows, so the wrapper keeps
        # answering for the method underneath it.
        import functools

        @functools.wraps(real)
        def _call(*a, **kw):
            got = real(*a, **kw)
            if _is_answer(method, got):
                self.outputs += 1
            return got

        try:
            setattr(adapter, method, _call)
        except AttributeError:                   # a __slots__ adapter
            return adapter
        return adapter

    # ---------------------------------------------------------------- report

    #: The rungs a seam actually consumes. `speaker` is loadable and absent
    #: here on purpose — see `SherpaStack.speaker`.
    RUNGS = ("asr", "vad", "wake", "tagger")

    def offers(self) -> list:
        """Which rungs this directory can actually fill, for status surfaces."""
        return sorted(n for n in self.RUNGS if self._loaded(n) is not None)

    def driving(self) -> bool:
        return self.outputs > 0

    def status(self) -> dict:
        return {"configured": bool(_dir(self.brain)), "offers": self.offers(),
                "outputs": self.outputs, "live": self.driving()}


def _is_answer(method: str, got) -> bool:
    """Did this adapter say something, or return its own null?"""
    if method == "detect":                       # (hit, score)
        try:
            return bool(got[0])
        except (TypeError, IndexError):
            return False
    if method == "is_speech":
        # A VAD legitimately answers False, and False is ALSO what a broken one
        # never says (the null is True — "no gate, keep the audio"). So a
        # negative verdict is the only unambiguous proof a real model ran.
        return got is False
    return bool(got)                             # "" / [] are the nulls


def stack(brain) -> SherpaStack:
    got = getattr(brain, "_sherpa_stack", None)
    if got is None:
        got = SherpaStack(brain)
        brain._sherpa_stack = got
    return got
