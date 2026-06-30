"""pytest tests for halo_lab.py — pure unit tests, no emulator required."""
import json
import sys
import struct
import io
from pathlib import Path

from PIL import Image, ImageSequence

# halo_lab is safe to import without halo_emulator installed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from halo_lab import (
    ble_frame,
    validate_scenario,
    step_label,
    make_contact_sheet,
    make_gif,
    CARD_REQUIRED,
    VALID_ACTIONS,
    BUTTON_VALUES,
)

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"


# ---------------------------------------------------------------------------
# BLE framing
# ---------------------------------------------------------------------------

class TestBleFrame:
    def test_length_prefix_correct(self):
        framed = ble_frame({"t": "connect"})
        assert struct.unpack(">I", framed[:4])[0] == len(framed)

    def test_payload_round_trips(self):
        msg = {"t": "card", "payload": {"type": "ObjectRecallCard", "object": "KEYS"}}
        assert json.loads(ble_frame(msg)[4:]) == msg

    def test_connect_frame_size(self):
        assert len(ble_frame({"t": "connect"})) == 20


# ---------------------------------------------------------------------------
# Scenario validation
# ---------------------------------------------------------------------------

class TestValidateScenario:
    def _load(self, name):
        p = SCENARIO_DIR / f"{name}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def test_valid_mindblow(self):
        s = self._load("mindblow_demo")
        if s:
            assert validate_scenario(s) == []

    def test_valid_all_cards(self):
        s = self._load("all_cards")
        if s:
            assert validate_scenario(s) == []

    def test_valid_button_flow(self):
        s = self._load("button_flow")
        if s:
            assert validate_scenario(s) == []

    def test_valid_privacy_flow(self):
        s = self._load("privacy_flow")
        if s:
            assert validate_scenario(s) == []

    def test_valid_puente_caption(self):
        s = self._load("puente_caption")
        if s:
            assert validate_scenario(s) == []

    def test_missing_name(self):
        assert any("name" in e for e in validate_scenario({"steps": []}))

    def test_missing_steps(self):
        assert any("steps" in e for e in validate_scenario({"name": "x"}))

    def test_unknown_action(self):
        errs = validate_scenario({"name": "x", "steps": [{"action": "teleport"}]})
        assert any("teleport" in e for e in errs)

    def test_card_missing_required_fields(self):
        errs = validate_scenario({"name": "x", "steps": [
            {"action": "card", "card_type": "ObjectRecallCard", "payload": {}}
        ]})
        assert len(errs) == len(CARD_REQUIRED["ObjectRecallCard"])

    def test_invalid_button_kind(self):
        errs = validate_scenario({"name": "x", "steps": [
            {"action": "button", "kind": "quadruple"}
        ]})
        assert any("kind" in e for e in errs)

    def test_unknown_card_type(self):
        errs = validate_scenario({"name": "x", "steps": [
            {"action": "card", "card_type": "WeatherCard", "payload": {}}
        ]})
        assert any("WeatherCard" in e for e in errs)

    def test_all_card_types_have_schema(self):
        for ct, req in CARD_REQUIRED.items():
            assert isinstance(req, list)


# ---------------------------------------------------------------------------
# step_label
# ---------------------------------------------------------------------------

class TestStepLabel:
    def test_card_label(self):
        lbl = step_label(0, {"action": "card", "card_type": "ObjectRecallCard",
                             "payload": {"object": "KEYS"}})
        assert lbl.startswith("00_") and "objectrecall" in lbl and "keys" in lbl

    def test_button_label(self):
        assert step_label(3, {"action": "button", "kind": "single"}) == "03_btn_single"

    def test_command_label(self):
        assert step_label(5, {"action": "command", "kind": "ask"}) == "05_cmd_ask"

    def test_connect_label(self):
        assert step_label(1, {"action": "connect"}) == "01_connect"


# ---------------------------------------------------------------------------
# make_contact_sheet
# ---------------------------------------------------------------------------

def _fake_frames(n):
    return [(f"{i:02d}_step_{i}", Image.new("RGB", (256, 256), (0, 0, 0)))
            for i in range(n)]


class TestContactSheet:
    def test_returns_image(self):
        assert isinstance(make_contact_sheet(_fake_frames(4), "test"), Image.Image)

    def test_correct_width_4cols(self):
        assert make_contact_sheet(_fake_frames(4), "test", cols=4).size[0] == 4 * (256 + 8) + 8

    def test_empty_returns_placeholder(self):
        assert make_contact_sheet([], "test").size == (256, 256)

    def test_8_frames_2_rows(self):
        one = make_contact_sheet(_fake_frames(4), "test", cols=4)
        two = make_contact_sheet(_fake_frames(8), "test", cols=4)
        assert two.size[1] > one.size[1]


# ---------------------------------------------------------------------------
# make_gif
# ---------------------------------------------------------------------------

class TestMakeGif:
    def test_returns_gif_bytes(self):
        assert make_gif(_fake_frames(3))[:3] == b"GIF"

    def test_empty_returns_empty(self):
        assert make_gif([]) == b""

    def test_single_frame(self):
        assert make_gif(_fake_frames(1))[:3] == b"GIF"

    def test_frame_count(self):
        frames = _fake_frames(5)
        gif    = make_gif(frames)
        img    = Image.open(io.BytesIO(gif))
        n      = sum(1 for _ in ImageSequence.Iterator(img))
        assert n == len(frames)
