"""test_bug_report.py — in-app "Report a problem" (fast-follow 2026-07-19).

A wearer can file a bug from inside the app: the Brain assembles their words
plus a STRICTLY sanitized diagnostic summary (version, OS, capability counts,
seam failures — never a path, query, endpoint, key, or any PII) and a prefilled
GitHub-issue link. Nothing is sent automatically; the panel shows the text and
the wearer opens the issue or copies it. Revert-failing.
"""
from __future__ import annotations

import json
import threading
import urllib.request

import dreamlayer.ai_brain.server.server as srv
from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.panel import render_panel


def test_report_body_carries_words_and_sanitized_diagnostics(tmp_path):
    brain = Brain(tmp_path)
    r = srv._build_bug_report(brain, "QR won't scan", "nothing happened", include_diag=True)
    assert r["title"] == "QR won't scan"
    assert "nothing happened" in r["body"]
    assert "Diagnostics" in r["body"] and "DreamLayer" in r["body"]
    assert r["github_url"].startswith(
        "https://github.com/LetsGetToWorkBro/dreamlayer/issues/new?")


def test_report_never_leaks_pii(tmp_path):
    brain = Brain(tmp_path)
    brain.config.token = "SECRET-TOKEN-xyz"
    brain.config.folders = ["/home/alice/Private/Diaries"]
    brain.config.api_base_url = "https://alice-secret-endpoint.example/v1"
    brain.config.api_key = "sk-alicekey"
    r = srv._build_bug_report(brain, "help", "the thing broke", include_diag=True)
    for leak in ("SECRET-TOKEN", "alice", "Diaries", "/home/", "sk-alicekey",
                 "alice-secret-endpoint"):
        assert leak not in r["body"], f"PII leak: {leak}"


def test_report_diag_can_be_omitted(tmp_path):
    r = srv._build_bug_report(Brain(tmp_path), "s", "d", include_diag=False)
    assert "Diagnostics" not in r["body"]


def test_report_url_is_capped_but_body_keeps_full_text(tmp_path):
    brain = Brain(tmp_path)
    r = srv._build_bug_report(brain, "big", "y" * 9000, include_diag=True)
    assert len(r["github_url"]) <= 6000          # under browser/GitHub URL limits
    assert len(r["body"]) > 8000                 # the copy-to-clipboard text is full


def test_report_diagnostics_are_pii_free_counts_only(tmp_path):
    diag = srv._report_diagnostics(Brain(tmp_path))
    assert "DreamLayer" in diag and "model:" in diag
    assert "/" not in diag.split("·")[0]         # no path in the version line


def _serve(brain):
    server = make_brain_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_report_endpoint_returns_prepared_report_on_loopback(tmp_path):
    server, port = _serve(Brain(tmp_path))
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/dreamlayer/report",
            data=json.dumps({"summary": "hi", "detail": "there"}).encode(),
            headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=5) as r:
            body = json.loads(r.read())
        assert body["title"] == "hi"
        assert body["github_url"].startswith("https://github.com/")
    finally:
        server.shutdown(); server.server_close()


def test_panel_carries_report_ui():
    html = render_panel("tok")
    assert "Report a problem" in html
    assert "prepReport" in html and "copyReport" in html
    assert 'id="repSummary"' in html
