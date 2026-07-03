"""Build the DreamLayer knowledge base (docs/gitbook/) into a static site.

    python scripts/build_gitbook_site.py [out_dir]

Reads SUMMARY.md for the navigation tree, converts every chapter with
python-markdown, wraps it in the Meridian-styled template below, rewrites
.md links to .html, and copies the assets tree. Pure python-markdown +
stdlib; the CI Pages workflow runs exactly this.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "docs" / "gitbook"
SITE_NAME = "DreamLayer"
TAGLINE = "A memory layer for the real world"
REPO_URL = "https://github.com/LetsGetToWorkBro/dreamlayer"


# ---------------------------------------------------------------- nav model

def gh_slugify(value: str, separator: str = "-") -> str:
    """GitHub-style heading slugs (each space becomes a dash, runs kept)."""
    value = value.strip().lower()
    value = re.sub(r"[^\w\- ]", "", value)
    return value.replace(" ", separator)


def parse_summary() -> list[tuple[str, list[tuple[str, str]]]]:
    """SUMMARY.md -> [(section_title, [(page_title, md_path), ...]), ...]."""
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    current = ("", [])
    sections.append(current)
    for line in (BOOK / "SUMMARY.md").read_text().splitlines():
        m = re.match(r"^##\s+(.*)", line)
        if m:
            current = (m.group(1).strip(), [])
            sections.append(current)
            continue
        m = re.match(r"^\s*-\s*\[([^\]]+)\]\(([^)]+)\)", line)
        if m:
            current[1].append((m.group(1).strip(), m.group(2).strip()))
    return [s for s in sections if s[1]]


def out_name(md_path: str) -> str:
    if md_path == "README.md":
        return "index.html"
    return re.sub(r"\.md$", ".html", md_path)


# ---------------------------------------------------------------- template

CSS = """
:root {
  --bg: #04080a;
  --surface: #0b1214;
  --surface-2: #0e1618;
  --border: #1c2a2e;
  --border-soft: #141f22;
  --ink: #ecf0f1;
  --ink-2: #a8b8c0;
  --ink-3: #6d7f87;
  --teal: #2cc79a;
  --teal-bright: #43e6b8;
  --teal-dim: #1a7a60;
  --attention: #e06b52;
  --mono: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto,
          "Helvetica Neue", Arial, sans-serif;
  --sidebar-w: 288px;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--ink-2);
  font: 16px/1.7 var(--sans);
  -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
}
body::before {
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background:
    radial-gradient(900px 420px at 18% -8%, rgba(44,199,154,.10), transparent 60%),
    radial-gradient(720px 380px at 92% 0%, rgba(224,107,82,.05), transparent 60%);
}

/* ------------------------------------------------------------- sidebar */
#nav-toggle { display: none; }
.sidebar {
  position: fixed; z-index: 40; top: 0; left: 0; bottom: 0;
  width: var(--sidebar-w); overflow-y: auto; overscroll-behavior: contain;
  background: rgba(8,13,15,.92); backdrop-filter: blur(10px);
  border-right: 1px solid var(--border-soft);
  padding: 22px 18px 40px;
}
.sidebar::-webkit-scrollbar { width: 8px; }
.sidebar::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
.brand {
  display: flex; align-items: center; gap: 11px;
  padding: 4px 8px 16px; margin-bottom: 10px;
  border-bottom: 1px solid var(--border-soft);
  text-decoration: none;
}
.brand svg { flex: none; }
.brand .name {
  color: var(--ink); font-weight: 700; font-size: 17px; letter-spacing: .2px;
}
.brand .tag {
  display: block; color: var(--ink-3); font-size: 11px; font-weight: 400;
  letter-spacing: .3px; margin-top: 1px;
}
.nav-section {
  margin: 20px 8px 6px; font-size: 10.5px; font-weight: 700;
  letter-spacing: .14em; text-transform: uppercase; color: var(--teal);
  opacity: .85;
}
.sidebar a.page {
  display: block; padding: 6px 10px; margin: 1px 0;
  color: var(--ink-2); text-decoration: none; font-size: 13.5px;
  border-radius: 8px; border-left: 2px solid transparent;
}
.sidebar a.page:hover { color: var(--ink); background: rgba(44,199,154,.06); }
.sidebar a.page.active {
  color: var(--teal-bright); background: rgba(44,199,154,.09);
  border-left-color: var(--teal);
}
.sidebar .repo {
  margin: 26px 8px 0; font-size: 12.5px;
}
.sidebar .repo a { color: var(--ink-3); text-decoration: none; }
.sidebar .repo a:hover { color: var(--teal); }

/* ------------------------------------------------------------- topbar */
.topbar {
  display: none; position: sticky; top: 0; z-index: 30;
  align-items: center; gap: 12px;
  background: rgba(4,8,10,.9); backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border-soft); padding: 12px 16px;
}
.topbar label {
  display: inline-flex; flex-direction: column; gap: 4px; cursor: pointer;
  padding: 6px;
}
.topbar label span {
  display: block; width: 20px; height: 2px; background: var(--ink-2);
  border-radius: 2px;
}
.topbar .t-name { color: var(--ink); font-weight: 700; font-size: 15px; }

/* ------------------------------------------------------------- content */
.main { position: relative; z-index: 1; margin-left: var(--sidebar-w); }
.page-wrap { max-width: 828px; margin: 0 auto; padding: 52px 40px 40px; }
.crumb {
  font-size: 11px; font-weight: 700; letter-spacing: .16em;
  text-transform: uppercase; color: var(--teal); margin: 0 0 10px;
}
article h1 {
  color: var(--ink); font-size: 37px; line-height: 1.15; letter-spacing: -.5px;
  margin: 0 0 18px; font-weight: 750;
}
article h2 {
  color: var(--ink); font-size: 23px; letter-spacing: -.2px;
  margin: 44px 0 12px; padding-top: 18px;
  border-top: 1px solid var(--border-soft); font-weight: 700;
}
article h3 { color: var(--ink); font-size: 17.5px; margin: 30px 0 8px; font-weight: 650; }
article h4 { color: var(--ink); font-size: 15px; margin: 24px 0 6px; }
article p { margin: 0 0 14px; }
article a { color: var(--teal); text-decoration: none; border-bottom: 1px solid rgba(44,199,154,.3); }
article a:hover { color: var(--teal-bright); border-bottom-color: var(--teal-bright); }
article strong { color: var(--ink); font-weight: 650; }
article ul, article ol { padding-left: 26px; margin: 0 0 14px; }
article li { margin: 5px 0; }
article li::marker { color: var(--teal-dim); }
article hr { border: none; border-top: 1px solid var(--border-soft); margin: 32px 0; }
article blockquote {
  margin: 20px 0; padding: 14px 20px;
  border-left: 3px solid var(--teal);
  background: linear-gradient(90deg, rgba(44,199,154,.07), transparent 70%);
  border-radius: 0 10px 10px 0; color: var(--ink);
}
article blockquote p { margin: 6px 0; }
article code {
  font-family: var(--mono); font-size: .85em;
  background: var(--surface-2); border: 1px solid var(--border-soft);
  border-radius: 6px; padding: 1.5px 6px; color: #9fe8cf;
}
article pre {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 16px 18px; overflow-x: auto;
  margin: 18px 0; line-height: 1.55;
}
article pre code { background: none; border: none; padding: 0; color: #c9dbd4; font-size: 13px; }

article img {
  max-width: 100%; height: auto; border-radius: 14px;
  border: 1px solid var(--border);
  background: #000; display: block; margin: 6px auto;
  box-shadow: 0 8px 40px rgba(0,0,0,.5), 0 0 0 1px rgba(44,199,154,.04);
}
article p > img:only-child { margin: 20px auto; }
article p:has(> img:only-child) + p > em:only-child,
article img + em { color: var(--ink-3); font-size: 13px; }

article table {
  width: 100%; border-collapse: collapse; margin: 18px 0; font-size: 14px;
  display: block; overflow-x: auto;
}
article th {
  text-align: left; color: var(--teal); font-size: 11.5px;
  text-transform: uppercase; letter-spacing: .08em;
  border-bottom: 1px solid var(--border); padding: 8px 14px 8px 0;
  white-space: nowrap;
}
article td {
  border-bottom: 1px solid var(--border-soft);
  padding: 9px 14px 9px 0; vertical-align: top;
}
article td img { margin: 4px 0; min-width: 130px; }
article tr:last-child td { border-bottom: none; }

/* ------------------------------------------------------------- footer nav */
.pagenav {
  display: flex; gap: 14px; margin-top: 56px;
  border-top: 1px solid var(--border-soft); padding-top: 22px;
}
.pagenav a {
  flex: 1; display: block; padding: 14px 18px; text-decoration: none;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; transition: border-color .15s ease;
}
.pagenav a:hover { border-color: var(--teal-dim); }
.pagenav .dir { font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--ink-3); }
.pagenav .ttl { color: var(--ink); font-weight: 600; font-size: 14.5px; margin-top: 3px; }
.pagenav a.next { text-align: right; }
.foot {
  margin: 44px 0 0; color: var(--ink-3); font-size: 12.5px;
  border-top: 1px solid transparent; padding-top: 8px;
}
.foot a { color: var(--ink-3); }
.foot a:hover { color: var(--teal); }

/* ------------------------------------------------------------- mobile */
@media (max-width: 980px) {
  .topbar { display: flex; }
  .sidebar { transform: translateX(-100%); transition: transform .22s ease; }
  #nav-toggle:checked ~ .sidebar { transform: translateX(0); }
  .main { margin-left: 0; }
  .page-wrap { padding: 30px 20px 28px; }
  article h1 { font-size: 29px; }
  .pagenav { flex-direction: column; }
}
"""

FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Ccircle cx='16' cy='16' r='12' fill='none' stroke='%232cc79a' stroke-width='2.6'"
    " stroke-dasharray='56 20' stroke-linecap='round'/%3E"
    "%3Ccircle cx='16' cy='4' r='3' fill='%232cc79a'/%3E%3C/svg%3E"
)

LOGO = (
    "<svg width='30' height='30' viewBox='0 0 32 32' aria-hidden='true'>"
    "<circle cx='16' cy='16' r='12' fill='none' stroke='#2cc79a' stroke-width='2.4'"
    " stroke-dasharray='56 20' stroke-linecap='round'/>"
    "<circle cx='16' cy='4' r='3' fill='#43e6b8'/></svg>"
)

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - {site}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title} - {site}">
<meta property="og:description" content="{desc}">
<link rel="icon" href="{favicon}">
<style>{css}</style>
</head>
<body>
<input type="checkbox" id="nav-toggle">
<nav class="sidebar">
  <a class="brand" href="{root}index.html">{logo}
    <span><span class="name">{site}</span>
    <span class="tag">{tagline}</span></span></a>
  {nav}
  <div class="repo"><a href="{repo}">Source on GitHub</a></div>
</nav>
<div class="main">
  <div class="topbar">
    <label for="nav-toggle" aria-label="Menu"><span></span><span></span><span></span></label>
    <span class="t-name">{site}</span>
  </div>
  <div class="page-wrap">
    <p class="crumb">{crumb}</p>
    <article>
{content}
    </article>
    <div class="pagenav">{prevlink}{nextlink}</div>
    <p class="foot">DreamLayer knowledge base. Every image is rendered by the
    product's own pipeline. <a href="{repo}">Repository</a> ·
    <a href="{repo}/tree/main/docs/gitbook">Markdown source</a></p>
  </div>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------- build

def rewrite_links(html: str, depth: int) -> str:
    def sub(m: re.Match) -> str:
        href = m.group(1)
        if href.startswith(("http://", "https://", "#", "mailto:")):
            return m.group(0)
        path, _, frag = href.partition("#")
        if path.endswith(".md"):
            if path.rsplit("/", 1)[-1] == "README.md":
                path = path[: -len("README.md")] + "index.html"
            else:
                path = path[:-3] + ".html"
        return f'href="{path}{"#" + frag if frag else ""}"'

    return re.sub(r'href="([^"]+)"', sub, html)


def nav_html(nav, active_out: str, root: str) -> str:
    parts = []
    for section, pages in nav:
        if section:
            parts.append(f'<div class="nav-section">{section}</div>')
        for title, md in pages:
            out = out_name(md)
            cls = "page active" if out == active_out else "page"
            parts.append(f'<a class="{cls}" href="{root}{out}">{title}</a>')
    return "\n  ".join(parts)


def first_paragraph(text: str) -> str:
    for block in text.split("\n\n"):
        block = block.strip()
        if block and not block.startswith(("#", "!", ">", "|", "-", "```")):
            plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", block)
            plain = re.sub(r"[*`_]", "", plain).replace('"', "'")
            return " ".join(plain.split())[:280]
    return TAGLINE


def build(out_dir: Path) -> int:
    nav = parse_summary()
    flat = [(t, p) for _, pages in nav for (t, p) in pages]
    section_of = {p: (s or SITE_NAME) for s, pages in nav for (_, p) in pages}

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    shutil.copytree(BOOK / "assets", out_dir / "assets")

    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc"],
        extension_configs={"toc": {"slugify": gh_slugify, "anchorlink": False}},
    )

    for i, (title, md_path) in enumerate(flat):
        src = (BOOK / md_path).read_text()
        depth = md_path.count("/")
        root = "../" * depth
        md.reset()
        body = rewrite_links(md.convert(src), depth)

        prev_html = next_html = ""
        if i > 0:
            pt, pp = flat[i - 1]
            prev_html = (f'<a class="prev" href="{root}{out_name(pp)}">'
                         f'<span class="dir">Previous</span>'
                         f'<span class="ttl">{pt}</span></a>')
        if i < len(flat) - 1:
            nt, np_ = flat[i + 1]
            next_html = (f'<a class="next" href="{root}{out_name(np_)}">'
                         f'<span class="dir">Next</span>'
                         f'<span class="ttl">{nt}</span></a>')

        html = PAGE.format(
            title=title, site=SITE_NAME, tagline=TAGLINE, desc=first_paragraph(src),
            favicon=FAVICON, css=CSS, logo=LOGO, repo=REPO_URL, root=root,
            nav=nav_html(nav, out_name(md_path), root),
            crumb=section_of.get(md_path, SITE_NAME),
            content=body, prevlink=prev_html, nextlink=next_html,
        )
        dest = out_dir / out_name(md_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html)
    print(f"built {len(flat)} pages -> {out_dir}")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site"
    raise SystemExit(build(target))
