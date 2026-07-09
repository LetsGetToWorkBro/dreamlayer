"""rosetta_argos.py — an offline translation backend for `RosettaLens`.

ADD-alongside: `rosetta.py` (RosettaLens, detect_language) is untouched.
RosettaLens already exposes the clean seam `RosettaLens(translate_fn=...)`
where `translate_fn(text, target)->str`. This module provides such a callable
backed by Argos Translate (fully offline neural MT), plus a `make_translate_fn`
factory so wiring it is one line:

    from dreamlayer.rosetta import RosettaLens
    from dreamlayer.rosetta_argos import make_translate_fn
    lens = RosettaLens(translate_fn=make_translate_fn())

argostranslate is optional (extras group `platform`). When it is absent (or a
language pair is not installed) the returned callable falls back to identity —
it returns the source text unchanged, which is exactly what `RosettaLens` does
with `translate_fn=None`, so behaviour is unchanged.
"""
from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("dreamlayer.rosetta_argos")

try:
    from argostranslate import translate as _argos_translate  # type: ignore
    _HAS_ARGOS = True
except ImportError:
    _HAS_ARGOS = False


def _detect_source(text: str) -> str:
    # Reuse the host's lightweight detector so we agree with RosettaLens.
    try:
        from dreamlayer.rosetta import detect_language
        return detect_language(text)
    except Exception:
        return "auto"


class ArgosTranslator:
    available = _HAS_ARGOS

    def __init__(self):
        self._langs = None
        if _HAS_ARGOS:
            try:
                self._langs = _argos_translate.get_installed_languages()
            except Exception as exc:
                log.warning("[rosetta_argos] load failed: %s; identity", exc)
                self._langs = None

    def _lang(self, code: str):
        for lang in (self._langs or []):
            if getattr(lang, "code", None) == code:
                return lang
        return None

    def translate(self, text: str, target: str = "en") -> str:
        if not text or self._langs is None:
            return text
        src_code = _detect_source(text)
        if src_code in ("auto", target):
            return text
        src, dst = self._lang(src_code), self._lang(target)
        if src is None or dst is None:
            return text                      # pair not installed -> passthrough
        try:
            return src.get_translation(dst).translate(text)
        except Exception as exc:
            log.warning("[rosetta_argos] translate failed: %s; identity", exc)
            return text


def make_translate_fn() -> Callable[[str, str], str]:
    """Return a `translate_fn(text, target)->str` for RosettaLens. Always safe:
    identity passthrough when Argos or a language pair is unavailable."""
    tr = ArgosTranslator()
    return lambda text, target="en": tr.translate(text, target)
