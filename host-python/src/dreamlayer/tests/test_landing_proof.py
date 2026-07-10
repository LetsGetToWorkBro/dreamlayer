"""test_landing_proof.py — the proof-carrying trust section on the store page
(B9 surfaced on the website). A cheap guard that the section stays present and
matches the real safety-card copy the gate produces."""
from __future__ import annotations

from pathlib import Path

PLUGINS_HTML = Path(__file__).resolve().parents[4] / "landing" / "plugins.html"


def test_store_page_has_the_proof_carrying_section():
    html = PLUGINS_HTML.read_text(encoding="utf-8")
    assert 'class="proof"' in html
    assert "This behavior CANNOT" in html
    assert "photic-safety cap" in html
    assert "swallow your kill switch" in html
    # closes cleanly before the footer
    assert html.index('class="proof"') < html.index("<footer")
