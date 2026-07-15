"""Render the Brain control panel to a standalone HTML file for demo capture.

The shoot_panel*.js scripts serve this file and drive it with a fake cursor.
Usage:  python render_panel_html.py [/tmp/panel_demo.html]
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "host-python/src"))
from dreamlayer.ai_brain.server.panel import render_panel  # noqa: E402

html = render_panel("DEMO-TOKEN")
# Normalize over-escaped sequences inside the page's inline <script> (\\' / \\d /
# \\. render as literal double-backslashes and break the parser in a browser).
# No-op if the panel source is already clean.
html = html.replace("\\\\'", "\\'").replace("\\\\d", "\\d").replace("\\\\.", "\\.")

out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/panel_demo.html")
out.write_text(html)
print(f"wrote {out} ({len(html)} bytes)")
