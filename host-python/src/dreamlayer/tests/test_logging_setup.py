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
