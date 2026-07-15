"""test_rosetta.py — the Rosetta "eye": detection + the translate seam.

Audit 2026-07-14 graded rosetta B+ but Test Coverage C+: the exception->error
branch and the RosettaLens.read paths were untested. These unit tests drive
read() directly (no orchestrator) so every branch is covered.
"""
from __future__ import annotations

import logging


def test_detect_language_handles_non_latin_scripts():
    """Audit 2026-07-14: non-Latin scripts were misread as English and never
    translated. A single CJK/Arabic/Cyrillic char is now decisive."""
    from dreamlayer.rosetta import detect_language
    assert detect_language("これはメニューです") == "ja"
    assert detect_language("这是菜单") == "zh"
    assert detect_language("هذه قائمة") == "ar"
    assert detect_language("это меню") == "ru"
    assert detect_language("this is a menu") == "en"


def test_detect_language_uses_latin_function_words():
    from dreamlayer.rosetta import detect_language
    assert detect_language("hola, gracias por la mesa") == "es"
    assert detect_language("bonjour, merci pour le menu") == "fr"
    assert detect_language("danke für das essen") == "de"
    assert detect_language("ciao, grazie per il conto") == "it"
    assert detect_language("") == "en"                 # nothing to go on -> en


def test_read_translates_when_source_differs_from_target():
    from dreamlayer.rosetta import RosettaLens
    lens = RosettaLens(translate_fn=lambda t, tgt: "the check, please",
                       engine="test")
    r = lens.read("la cuenta, por favor", target="en")
    assert r.translated == "the check, please"
    assert r.source_lang == "es" and r.target_lang == "en"
    assert r.engine == "test" and r.changed() is True


def test_read_passes_through_same_language():
    from dreamlayer.rosetta import RosettaLens
    lens = RosettaLens(translate_fn=lambda t, tgt: "SHOULD NOT RUN")
    r = lens.read("this is a menu", target="en")
    assert r.translated == "this is a menu" and r.engine == "none"
    assert r.changed() is False


def test_read_without_a_model_is_passthrough():
    from dreamlayer.rosetta import RosettaLens
    r = RosettaLens().read("hola, gracias", target="en")
    assert r.translated == "hola, gracias" and r.engine == "none"


def test_read_empty_text_is_passthrough():
    from dreamlayer.rosetta import RosettaLens
    lens = RosettaLens(translate_fn=lambda t, tgt: "x")
    r = lens.read("   ", target="en")
    assert r.engine == "none" and r.translated == "   "


def test_read_empty_translation_falls_back_to_source():
    from dreamlayer.rosetta import RosettaLens
    lens = RosettaLens(translate_fn=lambda t, tgt: "", engine="test")
    r = lens.read("hola, gracias", target="en")
    assert r.translated == "hola, gracias"             # `out or text`
    assert r.engine == "test"


def test_read_failing_translator_degrades_and_logs(caplog):
    """The exception branch: engine='error', passthrough result, and a warning
    logged (audit flagged it as silent — no observability, no test)."""
    from dreamlayer.rosetta import RosettaLens

    def boom(_text, _target):
        raise RuntimeError("model unavailable")

    lens = RosettaLens(translate_fn=boom, engine="test")
    with caplog.at_level(logging.WARNING, logger="dreamlayer.rosetta"):
        r = lens.read("hola, gracias", target="en")
    assert r.engine == "error" and r.translated == "hola, gracias"
    assert any("translate failed" in rec.message for rec in caplog.records)


def test_custom_detect_fn_is_honoured():
    from dreamlayer.rosetta import RosettaLens
    lens = RosettaLens(translate_fn=lambda t, tgt: "translated",
                       detect_fn=lambda _t: "xx", engine="test")
    r = lens.read("whatever", target="en")
    assert r.source_lang == "xx" and r.translated == "translated"
