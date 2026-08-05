"""Every page this project serves is parsed by a real JavaScript engine.

Three surfaces are assembled as JavaScript inside Python strings — the control
panel (~174k characters), the Live Lens (~200k, the phone's entire surface) and
the simulator. A syntax error anywhere in one of them takes out EVERY control
on that page, not the section that introduced it, and nothing noticed: the
render function returns a string either way, so Python is happy and the page is
dead.

The nine landing pages are here for the same reason and were found by asking
the same question of the rest of the repository: they carry ~208k characters of
JavaScript inline in their HTML — more than the control panel — and no workflow
read any of it. The two landing modules that are real .js files are at least
named in registry.yml's path filter; the inline blocks were checked by nothing
at all, on the public site.

The card-parity tests read `live._PAGE` and search it for renderer names. Those
searches pass just as well on JavaScript that cannot parse, which is the shape
of check this repo keeps finding: green, and answering a narrower question than
it appears to.

Written after hand-editing the panel blob to add the consent section (#610) —
the edit that could have caused exactly this — and generalised to the other two
because the risk is not specific to the file I happened to touch.

TWO THINGS THIS FILE LEARNED THE HARD WAY
-----------------------------------------
**Render, do not read the module.** `live.py` writes `<script__NONCE__>`, a
placeholder substituted at render time so a strict CSP can stamp a nonce. Parse
the module source and an HTML parser sees a tag called `script__nonce__`, finds
no script bodies at all, and a "does it parse?" test over zero characters
passes. `_extract` therefore takes rendered output only, and `test_the_scan_is_
not_vacuous` pins that it found something substantial.

**Both nonce shapes.** `render_live("")` and `render_live(nonce)` differ in the
script tag itself, which is precisely where a substitution bug would live.
"""
from __future__ import annotations

import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from dreamlayer.ai_brain.server.live import render_live
from dreamlayer.ai_brain.server.panel import render_panel
from dreamlayer.simulator.page import PAGE as SIMULATOR_PAGE


def _find_node():
    for cand in ("/opt/node22/bin/node", "node", "nodejs"):
        if "/" in cand:
            if Path(cand).exists():
                return cand
        else:
            found = shutil.which(cand)
            if found:
                return found
    return None


class _ScriptBodies(HTMLParser):
    """Every <script> body in a page.

    Not a regex. `re.findall(r"<script[^>]*>(.*?)</script>", ...)` was the first
    draft and CodeQL flagged it py/bad-tag-filter (high) for missing `<SCRIPT>`.
    `re.I` would close the case half and leave `</script >` and attributes
    containing `>` for the next person. HTMLParser puts script content in CDATA
    mode and hands it over whole, which is what the regex approximated —
    verified byte-identical to the regex on the real panel page before the
    swap.
    """

    #: Script types whose body is JavaScript. A `type` naming anything else —
    #: application/ld+json, importmap, text/template — is data or markup that a
    #: JS parser is right to reject, so feeding it to `node --check` would fail
    #: the build on correct pages. Empty means "no type attribute".
    JS_TYPES = {"", "text/javascript", "application/javascript",
                "text/ecmascript", "application/ecmascript", "module"}

    def __init__(self):
        super().__init__()
        self.bodies: list[str] = []
        self.modules: list[bool] = []
        self._buf: list[str] | None = None
        self._is_module = False

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        # An external script has no body to check — including it added an empty
        # string to `bodies`, which inflates a count that is used as evidence
        # the scan found something.
        if "src" in a:
            return
        kind = a.get("type", "").strip().lower()
        if kind not in self.JS_TYPES:
            return
        self._buf = []
        self._is_module = kind == "module"

    def handle_endtag(self, tag):
        if tag == "script" and self._buf is not None:
            self.bodies.append("".join(self._buf))
            self.modules.append(self._is_module)
            self._buf = None

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)


def _extract(html: str) -> list[str]:
    p = _ScriptBodies()
    p.feed(html)
    p.close()
    return p.bodies


def _extract_typed(html: str) -> list[tuple[str, bool]]:
    """As `_extract`, but keeping whether each body is an ES module.

    `node --check` picks a goal symbol from --input-type, and `import`/`export`
    at the top level is a syntax error under `commonjs`. Checking a module as a
    script would fail a correct page, which is the way a parse gate gets turned
    off rather than fixed.
    """
    p = _ScriptBodies()
    p.feed(html)
    p.close()
    return list(zip(p.bodies, p.modules))


#: (name, rendered html, floor). The floor is a non-vacuity guard, not a size
#: policy: it fails if the extraction silently stopped finding the page's code,
#: which is the way a parse test goes quietly useless.
def _pages():
    return [
        ("panel", render_panel(token="unused-by-this-test"), 50_000),
        ("live-lens", render_live(), 50_000),
        ("live-lens (CSP nonce)", render_live("test-nonce"), 50_000),
        ("simulator", SIMULATOR_PAGE, 500),
    ]


@pytest.mark.parametrize("name,html,floor",
                         _pages(), ids=[p[0] for p in _pages()])
def test_the_served_javascript_parses(name, html, floor):
    node = _find_node()
    if not node:
        pytest.skip("no node runtime to parse the served JS")
    bodies = _extract(html)
    js = "\n".join(bodies)
    out = subprocess.run([node, "--check", "-"], input=js,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, (
        f"the {name} page's JavaScript does not parse — every control on it is "
        f"dead, not just the newest one:\n{out.stderr}")


@pytest.mark.parametrize("name,html,floor",
                         _pages(), ids=[p[0] for p in _pages()])
def test_the_scan_is_not_vacuous(name, html, floor):
    """The parse test above is only worth anything if it found the code.

    `node --check` on an empty string exits 0. So does it on the three
    characters left over when an extractor stops matching — which is exactly
    what happened when an earlier draft read `live.py`'s SOURCE instead of its
    rendered output and found no `<script>` at all, because the tag is spelled
    `<script__NONCE__>` until render time.
    """
    bodies = _extract(html)
    assert bodies, f"no <script> found in the {name} page — has it moved?"
    assert sum(len(b) for b in bodies) > floor, (
        f"the {name} page yielded only {sum(len(b) for b in bodies)} characters "
        f"of JavaScript — the extractor has probably stopped matching rather "
        f"than the page having shrunk")


def test_the_nonce_does_not_change_the_code():
    """A CSP nonce stamps the tag, never the script body.

    If substitution ever leaked into the code, the nonce-less shape every test
    here uses would stop representing what a browser actually runs under CSP.
    """
    assert _extract(render_live()) == _extract(render_live("test-nonce"))


# --- the public site, which is served too ------------------------------------
#: The landing pages carry ~208k characters of JavaScript INLINE in their HTML —
#: more than the control panel above — and nothing parsed any of it. The two
#: landing modules that are real .js files (figment.js, search.js) are at least
#: named in registry.yml's path filter; the inline blocks are in nine .html
#: files that no workflow reads. A syntax error in one takes out every control
#: on that page, exactly as it would on the panel, and the page still serves.
LANDING = Path(__file__).parents[4] / "landing"


def _landing_pages() -> list[Path]:
    return sorted(p for p in LANDING.rglob("*.html")
                  if _extract_typed(p.read_text(encoding="utf-8", errors="replace")))


class TestThePublicSiteParsesToo:
    def test_the_scan_actually_reaches_the_landing_pages(self):
        """The floor, again, for the reason it is always here: `rglob` on a
        missing directory yields nothing, the parametrised test below collapses
        to zero cases, and pytest reports success over a site it never opened.
        """
        assert LANDING.is_dir(), f"the landing site is not at {LANDING}"
        pages = _landing_pages()
        assert len(pages) >= 8, (
            f"only {len(pages)} landing pages carry inline script — the "
            f"extractor has probably stopped matching rather than the site "
            f"having been rewritten")
        total = sum(len(b) for p in pages
                    for b, _ in _extract_typed(p.read_text(encoding="utf-8")))
        assert total > 100_000, (
            f"only {total} characters of inline JavaScript found across the "
            f"landing site — it was ~208k when this was written")

    @pytest.mark.parametrize("page", _landing_pages(),
                             ids=[p.name for p in _landing_pages()])
    def test_a_landing_page_javascript_parses(self, page):
        node = _find_node()
        if not node:
            pytest.skip("no node runtime to parse the landing JS")
        for i, (body, is_module) in enumerate(
                _extract_typed(page.read_text(encoding="utf-8"))):
            if len(body.strip()) < 5:
                continue
            out = subprocess.run(
                [node, "--input-type=module" if is_module else
                 "--input-type=commonjs", "--check", "-"],
                input=body, capture_output=True, text=True, timeout=60)
            assert out.returncode == 0, (
                f"{page.name} script block {i} does not parse — every control "
                f"on that page is dead, not just the newest one:\n{out.stderr}")
