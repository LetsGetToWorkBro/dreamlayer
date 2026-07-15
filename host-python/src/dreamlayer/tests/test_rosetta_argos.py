"""test_rosetta_argos.py — the offline Argos backend for RosettaLens.

Audit 2026-07-14 (rosetta +argos): "all of ArgosTranslator.translate is
untested (only the absent-lib identity fallback is exercised)." We do NOT install
the heavy optional dep; instead we drive the translate logic with fake installed
languages so the happy path, the pair-missing passthrough, and the engine-error
passthrough are all covered — plus the genuine lazy-import identity fallback.
"""
from __future__ import annotations

import logging

from dreamlayer import rosetta_argos
from dreamlayer.rosetta_argos import ArgosTranslator, make_translate_fn, _HAS_ARGOS


# -- fakes standing in for argostranslate's installed-language objects --------

class _FakeTranslation:
    def __init__(self, out):
        self._out = out

    def translate(self, text):
        return self._out


class _FakeLang:
    def __init__(self, code, out=None, raises=False):
        self.code = code
        self._out = out
        self._raises = raises

    def get_translation(self, _dst):
        if self._raises:
            raise RuntimeError("no translation path")
        return _FakeTranslation(self._out)


# -- the optional-dep guard --------------------------------------------------

def test_available_reflects_the_optional_dep():
    assert ArgosTranslator.available == _HAS_ARGOS


def test_make_translate_fn_is_identity_safe_without_argos():
    fn = make_translate_fn()
    assert callable(fn)
    if not _HAS_ARGOS:
        # lazy-import guard: absent the dep, the callable is identity passthrough
        # — exactly what RosettaLens does with translate_fn=None.
        assert fn("hola, gracias", "en") == "hola, gracias"


def test_translate_identity_when_langs_absent():
    tr = ArgosTranslator()
    tr._langs = None                      # simulates the lib/load-failed state
    assert tr.translate("hola", "en") == "hola"


def test_translate_empty_text_is_passthrough():
    tr = ArgosTranslator()
    tr._langs = [_FakeLang("es")]
    assert tr.translate("", "en") == ""


# -- the translate logic, driven with fake installed languages ---------------

def test_translate_uses_an_installed_pair(monkeypatch):
    tr = ArgosTranslator()
    tr._langs = [_FakeLang("es", out="the check, please"), _FakeLang("en")]
    monkeypatch.setattr(rosetta_argos, "_detect_source", lambda _t: "es")
    assert tr.translate("la cuenta, por favor", "en") == "the check, please"


def test_translate_passthrough_when_source_equals_target(monkeypatch):
    tr = ArgosTranslator()
    tr._langs = [_FakeLang("en", out="SHOULD NOT RUN")]
    monkeypatch.setattr(rosetta_argos, "_detect_source", lambda _t: "en")
    assert tr.translate("hello there", "en") == "hello there"


def test_translate_passthrough_when_pair_not_installed(monkeypatch):
    tr = ArgosTranslator()
    tr._langs = [_FakeLang("es", out="x")]            # no 'en' target installed
    monkeypatch.setattr(rosetta_argos, "_detect_source", lambda _t: "es")
    assert tr.translate("la cuenta", "en") == "la cuenta"


def test_translate_passthrough_on_engine_error(monkeypatch, caplog):
    tr = ArgosTranslator()
    tr._langs = [_FakeLang("es", raises=True), _FakeLang("en")]
    monkeypatch.setattr(rosetta_argos, "_detect_source", lambda _t: "es")
    with caplog.at_level(logging.WARNING, logger="dreamlayer.rosetta_argos"):
        out = tr.translate("la cuenta", "en")
    assert out == "la cuenta"                          # identity on failure
    assert any("translate failed" in r.message for r in caplog.records)


def test_detect_source_reuses_the_host_detector():
    assert rosetta_argos._detect_source("hola, gracias por la mesa") == "es"
    assert rosetta_argos._detect_source("this is a menu") == "en"
