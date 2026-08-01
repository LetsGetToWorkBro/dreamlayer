"""nlp_setup — the one-model bootstrap the presidio/spaCy capabilities need.

Pins the fail-safe contract (every function degrades cleanly when spaCy /
presidio / the model are absent — this env) and that `download` builds the right
`python -m spacy download` command without a real network fetch, plus the
`dreamlayer setup models` CLI wiring.
"""
from __future__ import annotations

import sys

import pytest

from dreamlayer import nlp_setup


class _R:
    """A stand-in for subprocess.CompletedProcess."""
    def __init__(self, returncode: int, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr


def test_model_present_is_false_and_safe_without_the_model(monkeypatch):
    """The fail-safe contract, not the machine it runs on (#556).

    This used to be `assert nlp_setup.model_present() is False`, which asserts
    that the optional model is ABSENT — true in CI, and false for any
    contributor who followed `nlp_setup`'s own instructions and ran
    `python -m spacy download en_core_web_sm`. The function was right; the test
    was pinning the environment.

    What is actually promised is "spaCy absent or any probe error → False", and
    that is checkable everywhere: force the import to fail and require False.
    """
    monkeypatch.setitem(sys.modules, "spacy", None)   # `import spacy` now raises
    assert nlp_setup.model_present() is False


def test_model_present_answers_truthfully_when_spacy_is_there():
    """The other half, and the half the old assertion made unreachable: when
    spaCy IS importable the answer must track reality rather than being
    hard-coded either way. Skips when the extra is absent, which is what a
    test about installed behaviour should do."""
    spacy = pytest.importorskip("spacy")
    got = nlp_setup.model_present()
    assert got is bool(spacy.util.is_package(nlp_setup.SPACY_MODEL))
    assert isinstance(got, bool)


def test_analyzer_engine_is_none_and_safe_without_presidio(monkeypatch):
    """Same correction, same reason. Asserting `is None` unconditionally pins
    "presidio is not installed", which stops being true the moment anyone runs
    `pip install 'dreamlayer[privacy]'`. The contract is that a missing or
    broken presidio yields None instead of raising into the caller."""
    monkeypatch.setitem(sys.modules, "presidio_analyzer", None)
    assert nlp_setup.analyzer_engine() is None


def test_analyzer_engine_never_raises_whatever_is_installed():
    """The environment-independent invariant: this function is documented as
    "Never raises into the caller", so call it as-is and require only that it
    returns something or nothing without blowing up."""
    nlp_setup.analyzer_engine()          # must not raise, whatever is present


def test_download_reports_missing_spacy(monkeypatch):
    monkeypatch.setattr(nlp_setup, "_spacy_installed", lambda: False)
    ok, msg = nlp_setup.download(runner=lambda *a, **k: _R(0))
    assert ok is False and "spaCy isn't installed" in msg


def test_download_is_a_noop_when_the_model_is_present(monkeypatch):
    monkeypatch.setattr(nlp_setup, "_spacy_installed", lambda: True)
    monkeypatch.setattr(nlp_setup, "model_present", lambda m=nlp_setup.SPACY_MODEL: True)
    calls = []
    ok, msg = nlp_setup.download(runner=lambda *a, **k: calls.append(a) or _R(0))
    assert ok is True and "already installed" in msg
    assert calls == []                              # never shelled out


def test_download_runs_the_right_command_and_reports(monkeypatch):
    monkeypatch.setattr(nlp_setup, "_spacy_installed", lambda: True)
    monkeypatch.setattr(nlp_setup, "model_present", lambda m=nlp_setup.SPACY_MODEL: False)
    seen = {}

    def fake_runner(cmd, **kw):
        seen["cmd"] = cmd
        return _R(0)

    ok, msg = nlp_setup.download(runner=fake_runner)
    assert ok is True and "downloaded" in msg
    assert seen["cmd"] == [sys.executable, "-m", "spacy", "download", nlp_setup.SPACY_MODEL]


def test_download_surfaces_a_nonzero_exit(monkeypatch):
    monkeypatch.setattr(nlp_setup, "_spacy_installed", lambda: True)
    monkeypatch.setattr(nlp_setup, "model_present", lambda m=nlp_setup.SPACY_MODEL: False)
    ok, msg = nlp_setup.download(runner=lambda *a, **k: _R(1, "boom"))
    assert ok is False and "exited 1" in msg and "boom" in msg


def test_cli_setup_models_invokes_download(monkeypatch, capsys):
    from dreamlayer import cli
    calls = {}

    def fake_download(model=nlp_setup.SPACY_MODEL, **kw):
        calls["model"] = model
        return True, f"downloaded {model}"

    monkeypatch.setattr(nlp_setup, "download", fake_download)
    assert cli.main(["setup", "models"]) == 0
    assert calls["model"] == nlp_setup.SPACY_MODEL      # default = the standard small model
    out = capsys.readouterr().out
    assert "pii_redaction" in out and "stranger_defense" in out


def test_cli_setup_models_is_nonzero_on_failure(monkeypatch):
    from dreamlayer import cli
    monkeypatch.setattr(nlp_setup, "download",
                        lambda *a, **k: (False, "spaCy isn't installed — ..."))
    assert cli.main(["setup", "models"]) == 1
