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
        # the denser Live Lens QR must render at a comfortable scanning size
        assert ".qrbox.live svg{width:300px" in html

    def test_panel_explains_the_token_cannot_be_typed(self):
        html = render_panel("tok")
        assert "meant to be scanned, not typed" in html
        assert "#t=" in html   # the fragment is named so a typist keeps it


class TestLivePageGuidance:
    def test_no_token_notice_explains_why(self):
        from dreamlayer.ai_brain.server.live import render_live
        page = render_live("nonce")
        # the on-load 401 notice must name the missing-token cause, not just
        # "scan the QR"
        assert "without its pairing token" in page
        assert "SCAN THE QR TO CONNECT" in page
        # it still points the wearer at the panel path
        assert "Connections" in page and "Live Lens" in page
