"""DreamShell — the terminal ported into the desktop panel.

Asserts the terminal ships, is wired to the REAL Brain (not the site's fakes),
carries the dream adventure + the Easter eggs, and — since panel.py is a raw
string — that its embedded JS has no doubled escape sequences (the raw-string
trap that would render `\\n` instead of a newline).
"""
from __future__ import annotations

from dreamlayer.ai_brain.server.panel import render_panel


def _panel() -> str:
    return render_panel("tok")


class TestTerminalShips:
    def test_section_and_engine_present(self):
        h = _panel()
        for needle in ('id="term"', 'id="termScr"', 'id="termCmd"', "DreamShell 8.1",
                       "function shellExec", "termFocus"):
            assert needle in h, f"missing {needle}"

    def test_terminal_is_a_nav_page(self):
        h = _panel()
        assert '{id:"terminal",label:"Terminal"' in h
        assert 'id==="terminal"&&typeof termFocus' in h   # boots + focuses on open


class TestWiredToRealBrain:
    def test_real_commands_hit_real_endpoints(self):
        h = _panel()
        # ask/status/caps/history talk to THIS Brain, not a canned reply
        assert '/dreamlayer/brain/ask' in h
        assert '/dreamlayer/config' in h
        assert '/dreamlayer/capabilities' in h
        assert '/dreamlayer/history' in h

    def test_veil_gates_the_ask(self):
        h = _panel()
        # an ask made under the veil sends no_cloud, matching the wearer's posture
        seg = h.split('if(c==="ask")', 1)[1][:600]
        assert "no_cloud:term.classList.contains(\"veiled\")" in seg


class TestEasterEggsAndDream:
    def test_dream_adventure_ported(self):
        h = _panel()
        for needle in ("function startDream", "function dreamExec", "veil bridge",
                       "kept. not uploaded"):
            assert needle in h, f"dream game missing {needle}"

    def test_the_eggs_are_here(self):
        h = _panel()
        for egg in ('c==="matrix"', 'c==="glitch"', 'c==="sudo"', 'c==="hack"',
                    'c==="moof"', 'c==="42"', "konami", "CHEAT UNLOCKED"):
            assert egg in h, f"missing easter egg {egg}"

    def test_juno_speaks_from_bundled_clips(self):
        h = _panel()
        assert "/panel-assets/juno_hey.mp3" in h and "junoSpeak" in h


class TestRawStringEscapesAreClean:
    def test_no_doubled_js_escapes_in_the_terminal_block(self):
        h = _panel()
        start = h.index("=================== DreamShell")
        block = h[start:h.index("})();", start)]
        # panel.py is r"""...""" — a doubled backslash here would reach the
        # browser as a literal \n / ’ instead of the intended escape
        assert "\\\\n" not in block, "doubled newline escape in terminal JS"
        assert "\\\\u" not in block, "doubled unicode escape in terminal JS"
