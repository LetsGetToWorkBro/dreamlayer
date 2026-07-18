"""nlp_setup.py — the one spaCy model the NLP capabilities need, and how to get it.

The `privacy` extra ships presidio-analyzer and the `intelligence` extra ships
spaCy, but neither pulls a spaCy *model* — models aren't pip dependencies, they
are a separate download. Presidio's out-of-the-box `AnalyzerEngine()` wants the
~560 MB ``en_core_web_lg``; ``social_lens/ner_spacy.py`` already uses the ~12 MB
``en_core_web_sm``. Rather than carry two models, DreamLayer standardises on the
small one: ONE ``en_core_web_sm`` download lights up all three model-backed NLP
capabilities — ``pii_redaction`` and ``stranger_defense`` (both presidio) and
``nlp`` (spaCy NER).

`dreamlayer setup models` (cli.py) calls :func:`download`; the adapters call
:func:`analyzer_engine` to build a presidio engine pinned to that model. Every
function here is fail-safe: a missing dep or a missing model degrades to the
adapter's own non-model fallback (presidio → regex, ner_spacy → heuristic), it
never raises into a caller.
"""
from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys

log = logging.getLogger("dreamlayer.nlp_setup")

# The single spaCy model the project standardises on (small, on-device friendly).
SPACY_MODEL = "en_core_web_sm"


def _spacy_installed() -> bool:
    """True when the spaCy library itself is importable (the model download and
    the presidio NlpEngine both need it). Never raises."""
    try:
        return importlib.util.find_spec("spacy") is not None
    except BaseException:
        return False


def model_present(model: str = SPACY_MODEL) -> bool:
    """True when `model` is already installed (so a bootstrap can skip it).
    Fail-safe: spaCy absent or any probe error → False."""
    try:
        import spacy  # noqa: F401
        return bool(spacy.util.is_package(model))
    except BaseException:
        return False


def download(model: str = SPACY_MODEL, *, runner=subprocess.run) -> tuple[bool, str]:
    """Download `model` via ``python -m spacy download`. Idempotent (a
    present model is a no-op success). Returns ``(ok, human_message)`` and never
    raises — the CLI turns it into an exit code. `runner` is injectable so the
    command construction is unit-tested without a real network download."""
    if not _spacy_installed():
        return False, ("spaCy isn't installed — run "
                       "`pip install 'dreamlayer[intelligence]'` (or `[privacy]`) first")
    if model_present(model):
        return True, f"{model} is already installed"
    try:
        result = runner([sys.executable, "-m", "spacy", "download", model],
                        capture_output=True, text=True)
    except Exception as exc:                       # runner couldn't even start
        return False, f"could not start the spaCy download: {exc}"
    if getattr(result, "returncode", 1) == 0:
        return True, f"downloaded {model}"
    stderr = (getattr(result, "stderr", "") or "").strip()
    return False, f"spaCy download exited {result.returncode}: {stderr[:200]}"


def analyzer_engine(model: str = SPACY_MODEL):
    """Build a Presidio ``AnalyzerEngine`` pinned to `model`, so presidio uses the
    same small model the bootstrap installs instead of demanding its ~560 MB
    default. Resolution order, all fail-safe:

      1. presidio with `model` (e.g. en_core_web_sm) — the standard path;
      2. presidio's own default engine — honours an operator who installed
         en_core_web_lg instead;
      3. ``None`` — the caller falls back (presidio → regex, guard → deterministic).

    Never raises into the caller."""
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
    except BaseException:                          # presidio absent / broken native dep
        return None
    try:
        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": model}],
        })
        return AnalyzerEngine(nlp_engine=provider.create_engine(),
                              supported_languages=["en"])
    except Exception as exc:                        # `model` not downloaded, or config quirk
        log.debug("[nlp_setup] presidio with %s unavailable (%s); trying the default",
                  model, exc)
    try:
        from presidio_analyzer import AnalyzerEngine
        return AnalyzerEngine()                     # presidio default (en_core_web_lg)
    except Exception as exc:
        log.debug("[nlp_setup] presidio default engine unavailable: %s", exc)
        return None
