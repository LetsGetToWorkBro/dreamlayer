"""World-lens (Live Lens, no-app) connect UX — the QR-scanning path.

User reports: the QR "doesn't pop up" and, when the URL is typed by hand, the
camera opens but the lenses never work. Root cause: the QR was hidden behind a
"Get the link" button, and the pairing token rides the URL fragment (#t=…),
which manual typing drops — so every look 401s. These pin the fixes:
- the Live Lens QR auto-loads when Connections opens (no button hunt);
- the QR renders larger so a phone camera locks on;
- both the panel and the live page explain that the token can't be typed and
  the whole link (incl. #t=…) is required.
"""
from __future__ import annotations

from dreamlayer.ai_brain.server.panel import render_panel


class TestPanelConnectUX:
    def test_live_qr_autoloads_on_connections(self):
        html = render_panel("tok")
        # showPage('reach') kicks liveLink() once, so the QR is present without
        # the user finding a button
        assert "_liveAutoLoaded" in html
        assert 'id==="reach"' in html and "liveLink()" in html

    def test_qr_rendered_large_enough_to_scan(self):
        html = render_panel("tok")
        # the Live Lens QR (now the sparse short-code payload) must render at a
        # comfortable scanning size — bigger modules lock on off a glossy screen
        assert ".qrbox.live svg{width:340px" in html

    def test_panel_explains_the_token_cannot_be_typed(self):
        html = render_panel("tok")
        assert "meant to be scanned, not typed" in html
        assert "#t=" in html   # the fragment is named so a typist keeps it


class TestLivePageGuidance:
    def test_no_token_notice_explains_why(self):
        from dreamlayer.ai_brain.server.live import render_live
        page = render_live("nonce")
        # the on-load notice must name the missing-token cause and offer the
        # code fallback, not just "scan the QR"
        assert "without its pairing token" in page
        assert "CONNECT THIS PHONE" in page
        # it still points the wearer at the panel path
        assert "Connections" in page and "Live Lens" in page

    def test_code_redeem_ui_and_call_present(self):
        from dreamlayer.ai_brain.server.live import render_live
        page = render_live("nonce")
        # the typeable-code fallback: an input + the redeem call to the endpoint
        assert "pairCode" in page and "redeemCode" in page
        assert "/dreamlayer/live/redeem" in page
        # a redeemed token is stored the same way a scanned one is
        assert 'sessionStorage.setItem("dl-live-token"' in page


class TestPanelShowsCode:
    def test_panel_renders_the_short_code_block(self):
        from dreamlayer.ai_brain.server.panel import render_panel
        html = render_panel("tok")
        assert "livecode" in html and "codebig" in html
        assert "Can't scan?" in html
        assert "r.code" in html   # the code from /live/link is surfaced
