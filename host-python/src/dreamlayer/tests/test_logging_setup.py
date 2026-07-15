"""The opt-in structured-logging setup: JSON mode is one line per record with
extras, plain mode is unchanged, and configure_logging is idempotent."""
import json
import logging

from dreamlayer.logging_setup import JsonLineFormatter, configure_logging


def _record(msg="hello", **extra):
    rec = logging.LogRecord("dreamlayer.test", logging.INFO, __file__, 1,
                            msg, None, None)
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


class TestJsonFormatter:
    def test_emits_one_json_object(self):
        line = JsonLineFormatter().format(_record("boot", seam="cloud"))
        obj = json.loads(line)              # single valid JSON object
        assert obj["msg"] == "boot"
        assert obj["level"] == "INFO"
        assert obj["logger"] == "dreamlayer.test"
        assert obj["seam"] == "cloud"       # extras ride alongside

    def test_non_serialisable_extra_is_repr(self):
        obj = json.loads(JsonLineFormatter().format(_record(obj=object())))
        assert "object object" in obj["obj"]

    def test_exception_included(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            rec = logging.LogRecord("x", logging.ERROR, __file__, 1,
                                    "failed", None, sys.exc_info())
        obj = json.loads(JsonLineFormatter().format(rec))
        assert "ValueError: boom" in obj["exc"]

    def test_sensitive_extras_are_redacted(self):
        """Regression (privacy): sensitive extras (names/embeddings/etc.) must
        NOT be serialised verbatim into the log line — a caller passing PII in
        extra={} would otherwise leak it if logs ship. Benign keys survive.
        FAILS ON REVERT of the redaction pass in logging_setup.JsonLineFormatter.

        NB: the bare key ``name`` is a *reserved* LogRecord attribute (the
        logger name); real ``logger.info(msg, extra={"name": ...})`` raises
        KeyError and setattr'ing it here would just overwrite the logger field.
        The genuine leak surface is the *non-reserved* extras below — a
        name-family key (``user_name``) and a raw ``embedding`` vector."""
        line = JsonLineFormatter().format(_record(
            "event",
            user_name="Alice",      # name-family PII (caught via *_name rule)
            embedding=[0.1, 0.2],   # raw vector PII
            seam="cloud",           # benign, must survive unchanged
        ))
        # The raw plaintext / raw vector must be absent from the serialised line.
        assert "Alice" not in line
        assert "0.1" not in line and "0.2" not in line
        obj = json.loads(line)
        # Sensitive keys are still present as keys, but with a redacted marker.
        assert obj["user_name"] != "Alice"
        assert obj["user_name"].startswith("<redacted")
        assert obj["embedding"] != [0.1, 0.2]
        assert isinstance(obj["embedding"], str)
        assert obj["embedding"].startswith("<redacted")
        # Non-sensitive extras ride through untouched.
        assert obj["seam"] == "cloud"


class TestConfigure:
    def teardown_method(self):
        configure_logging(json_mode=False, level="INFO")  # restore default

    def test_idempotent_single_handler(self):
        configure_logging(json_mode=True)
        configure_logging(json_mode=True)
        ours = [h for h in logging.getLogger().handlers
                if getattr(h, "_dreamlayer_handler", False)]
        assert len(ours) == 1               # not stacked

    def test_json_mode_toggles_formatter(self):
        configure_logging(json_mode=True)
        h = next(h for h in logging.getLogger().handlers
                 if getattr(h, "_dreamlayer_handler", False))
        assert isinstance(h.formatter, JsonLineFormatter)
        configure_logging(json_mode=False)
        h = next(h for h in logging.getLogger().handlers
                 if getattr(h, "_dreamlayer_handler", False))
        assert not isinstance(h.formatter, JsonLineFormatter)

    def test_falsy_env_spellings_disable_json(self, monkeypatch):
        """Audit 2026-07-14: DL_LOG_JSON=False/FALSE/off/no must DISABLE json,
        not enable it (the old case-sensitive check let 'False' through)."""
        import dreamlayer.logging_setup as ls
        for val in ("False", "FALSE", "off", "No", "0", ""):
            monkeypatch.setenv("DL_LOG_JSON", val)
            configure_logging()
            h = next(h for h in logging.getLogger().handlers
                     if getattr(h, "_dreamlayer_handler", False))
            assert not isinstance(h.formatter, ls.JsonLineFormatter), val
        for val in ("1", "true", "yes", "on"):
            monkeypatch.setenv("DL_LOG_JSON", val)
            configure_logging()
            h = next(h for h in logging.getLogger().handlers
                     if getattr(h, "_dreamlayer_handler", False))
            assert isinstance(h.formatter, ls.JsonLineFormatter), val
