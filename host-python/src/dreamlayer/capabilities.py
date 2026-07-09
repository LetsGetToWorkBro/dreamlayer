"""capabilities.py — read-only introspection over the optional-dependency seams.

DreamLayer ships 58 integrations as lazy adapters: each one `try/except`-imports
its library and falls back gracefully, so the core runs with nothing installed
(see docs/INTEGRATIONS.md). This module answers the operational question that
design creates: **on this machine, right now, what is actually switched on?**

Three layers, one file:

  installed   is the library importable?      (probed with find_spec — the
                                               module is never executed, so a
                                               broken native install can't
                                               crash the report)
  enabled     is it allowed?                   (env override: DL_DISABLE_<KEY>=1
                                               turns an installed capability off
                                               without uninstalling it)
  state       active / off / missing /         (what a builder or the panel
              unsupported / external            actually wants to know)

Deployment profiles (pyproject `profile-halo|phone|mac|cloud`) are composed
from the same extras groups the adapters document, so "switching on" a tier is
one command:  pip install -e ".[profile-mac]"  →  python -m dreamlayer.capabilities

Deliberately NOT here: no eager imports, no global registry that call sites
must consult, no second gating mechanism. The adapters keep their own lazy
`_HAS_X` guards as the runtime truth; this is the observability surface over
them. tests/test_capabilities.py asserts this file, the adapters' extras, and
pyproject's profile groups never drift apart.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from importlib.util import find_spec
from typing import Iterable, Optional, Tuple

# --- deployment profiles: which extras each target installs -------------------
# Mirrors [project.optional-dependencies] profile-* in pyproject.toml exactly
# (drift is a test failure, not a runtime surprise).
PROFILES: dict[str, Tuple[str, ...]] = {
    "profile-halo":  ("hardware",),
    "profile-phone": ("memory", "voice", "structured", "llm"),
    "profile-mac":   ("memory", "voice", "asr-extra", "structured", "llm",
                      "intelligence", "vision", "causal", "infra", "privacy",
                      "platform"),
    "profile-cloud": ("structured", "llm", "intelligence", "causal", "privacy"),
}

# kinds: "python"  = a pip library, probed by import name
#        "darwin"  = python, but Apple-silicon/macOS only
#        "service" = an external runtime spoken to over HTTP (nothing to import)
#        "manual"  = python, but deliberately not in any extras group (research
#                    installs with their own instructions)


@dataclass(frozen=True)
class Cap:
    key: str                      # stable id, also the env-flag suffix
    title: str                    # one-line human meaning
    tier: str                     # which family it belongs to (display grouping)
    modules: Tuple[str, ...]      # any-of import names, EXACTLY as the adapter imports them
    extra: Optional[str]          # pyproject extras group ("" concepts use None)
    seam: str                     # the adapter file that consumes it
    kind: str = "python"
    note: str = ""

    @property
    def flag_env(self) -> str:
        return "DL_DISABLE_" + self.key.upper()

    @property
    def profiles(self) -> Tuple[str, ...]:
        """Profiles that install this capability — derived, never hand-listed."""
        if self.extra is None:
            return ()
        return tuple(p for p, extras in PROFILES.items() if self.extra in extras)


CAPABILITIES: Tuple[Cap, ...] = (
    # --- memory ---------------------------------------------------------------
    Cap("vector_search", "Indexed vector recall over memories", "memory",
        ("sqlite_vec", "chromadb", "lancedb", "usearch"), "memory",
        "memory/vector_store.py (+chroma/lance/usearch siblings)"),
    Cap("local_embeddings", "Real semantic embeddings, offline", "memory",
        ("sentence_transformers",), "memory", "memory/embedder_local.py"),
    Cap("memory_dedup", "Dedup + decay over the memory stream", "memory",
        ("mem0",), "memory", "lucid_recall/mem0_layer.py"),
    Cap("typed_docs", "Validated multimodal memory records", "memory",
        ("docarray",), "memory", "memory/doc_schema.py"),
    Cap("social_graph", "Relationship graph algorithms", "memory",
        ("networkx",), "memory", "social_lens/graph.py"),

    # --- voice ------------------------------------------------------------------
    Cap("voice_vad", "Neural speech/noise gating before ASR", "voice",
        ("silero_vad",), "voice", "orchestrator/vad_gate.py"),
    Cap("local_asr", "Local speech-to-text (no cloud audio)", "voice",
        ("faster_whisper",), "voice", "orchestrator/asr_faster_whisper.py"),
    Cap("asr_alignment", "Word-level timestamps for prosody", "voice",
        ("whisperx",), "asr-extra", "truth_lens/prosody_whisperx.py"),
    Cap("diarization", "Live who-is-speaking turns", "voice",
        ("diart",), None, "social_lens/diarize_diart.py", kind="manual",
        note="pip install diart"),

    # --- structured output / llm ------------------------------------------------
    Cap("structured_output", "Schema-constrained LLM intent parsing", "structured",
        ("outlines", "instructor"), "structured",
        "reality_compiler/intent_parser_llm.py"),
    Cap("typed_models", "Veil-as-type-invariant memory records", "structured",
        ("pydantic",), "structured", "memory/models_pydantic.py"),
    Cap("typed_pipeline", "Traced RC stage pipeline", "structured",
        ("pydantic_ai",), "structured", "reality_compiler/pipeline_pydanticai.py"),
    Cap("llm_router", "One interface over ~100 LLM providers", "structured",
        ("litellm",), "llm", "ai_brain/litellm_backend.py"),

    # --- intelligence -------------------------------------------------------------
    Cap("speaker_id", "Real voice fingerprints (ECAPA 192-d)", "intelligence",
        ("speechbrain",), "intelligence", "orchestrator/speaker_ecapa.py"),
    Cap("nlp", "NER + dependency parse for commitments", "intelligence",
        ("spacy",), "intelligence",
        "orchestrator/commitment_nlp.py, social_lens/ner_spacy.py"),
    Cap("online_learning", "Per-user adaptation in real time", "intelligence",
        ("river",), "intelligence",
        "orchestrator/taste_river.py, dream_mode/weather_river.py"),
    Cap("persona_tuning", "Human-in-the-loop persona classifier", "intelligence",
        ("hulearn",), "intelligence", "orchestrator/persona_humanlearn.py"),
    Cap("object_tracking", "Identity-stable multi-object tracking", "intelligence",
        ("supervision",), "intelligence", "dream_mode/track_supervision.py"),
    Cap("facial_aus", "Micro-expression action units", "intelligence",
        ("libreface", "feat", "facetorch"), None, "truth_lens/au_backends.py",
        kind="manual", note="research installs; see adapter docstring"),

    # --- vision -------------------------------------------------------------------
    Cap("vision_classify", "Object recognition (CLIP/YOLO/VLM)", "vision",
        ("ultralytics", "open_clip", "moondream"), "vision",
        "object_lens/classify_backends.py"),
    Cap("coreml_ondevice", "Apple-silicon on-device inference", "vision",
        ("coremltools",), "vision", "object_lens/classify_backends.py",
        kind="darwin"),

    # --- causal ---------------------------------------------------------------------
    Cap("causal_fusion", "Causal inference over credibility channels", "causal",
        ("dowhy",), "causal", "truth_lens/causal_fusion.py"),

    # --- infra ------------------------------------------------------------------------
    Cap("dashboard", "Live TUI status dashboard", "infra",
        ("rich",), "infra", "ai_brain/dashboard_rich.py"),
    Cap("fs_watch", "Instant reaction to file changes", "infra",
        ("watchdog",), "infra", "orchestrator/fs_watch.py"),
    Cap("lan_discovery", "Phone finds the Brain automatically", "infra",
        ("zeroconf",), "infra", "orchestrator/discovery_zeroconf.py"),
    Cap("memory_explorer", "Browsable SQL view of the memory DB", "infra",
        ("datasette",), "infra", "memory/datasette_app.py"),
    Cap("spatial_viz", "Spatial/temporal debug visualization", "infra",
        ("rerun",), "infra", "simulator/rerun_viz.py"),

    # --- privacy ------------------------------------------------------------------------
    Cap("pii_redaction", "ML PII scrubbing before any write", "privacy",
        ("presidio_analyzer",), "privacy", "memory/pii_presidio.py",
        note="regex fallback is always on"),
    Cap("asym_signing", "Ed25519 provenance signatures", "privacy",
        ("cryptography",), "privacy", "reality_compiler/sign_crypto.py",
        note="HMAC fallback is always on"),
    Cap("structured_concurrency", "Veil-stop cancels every task", "privacy",
        ("anyio",), "privacy", "orchestrator/concurrency_anyio.py",
        note="asyncio fallback is always on"),

    # --- platform ----------------------------------------------------------------------
    Cap("plugin_entrypoints", "Plugins distributed as pip packages", "platform",
        ("pluggy",), "platform", "plugins/hookspecs.py",
        note="stdlib entry-point path works without it"),
    Cap("event_bus", "Decoupled pub/sub over mesh traffic", "platform",
        ("pyee",), "platform", "confluence/emitter_pyee.py"),
    Cap("offline_translation", "Neural MT with no network", "platform",
        ("argostranslate",), "platform", "rosetta_argos.py"),
    Cap("skia_render", "GPU-crisp HUD rasterizing", "platform",
        ("skia",), "platform", "hud/render_skia.py"),
    Cap("asgi_server", "Async FastAPI mirror of the Brain", "platform",
        ("fastapi",), "platform", "ai_brain/server_fastapi.py"),
    Cap("frame_glasses", "Brilliant Frame as a second display", "platform",
        ("frame_sdk",), "platform", "bridge/frame_sdk.py"),
    Cap("lsl_streams", "Lab Streaming Layer sensor export", "platform",
        ("pylsl",), "platform", "pipelines/lsl_transport.py"),
    Cap("mlx_train", "Overnight LoRA fine-tune of the local model", "platform",
        ("mlx",), "platform", "rem/nightly_mlx.py", kind="darwin"),

    # --- external runtimes (spoken to over HTTP; nothing to pip-import) -----------------
    Cap("ollama_local", "Local chat/vision/embeddings via Ollama", "services",
        (), None, "ai_brain/server/backends.py, ai_brain/gemma_backend.py",
        kind="service", note="http://127.0.0.1:11434"),
    Cap("exo_cluster", "One model across your machines via exo", "services",
        (), None, "ai_brain/exo_cluster.py",
        kind="service", note="http://127.0.0.1:52415"),
)

_BY_KEY = {c.key: c for c in CAPABILITIES}


# --- probing (read-only; never executes an optional module) ----------------------

def installed(cap: Cap) -> bool:
    """True if any of the capability's import names is resolvable.

    find_spec only consults import machinery metadata — the module body never
    runs, so a half-broken native wheel (the pyo3 PanicException class of
    failure) cannot take the report down with it. The trade-off is honesty in
    the other direction: such a wheel reports installed here while the adapter
    quietly falls back at import time — optimistic, never crashing."""
    for name in cap.modules:
        try:
            if find_spec(name) is not None:
                return True
        except BaseException:       # broken package metadata → treat as absent
            continue
    return False


def disabled(cap: Cap, env: Optional[dict] = None) -> bool:
    """DL_DISABLE_<KEY> ∈ {1,true,yes,on} turns an installed capability off —
    deploy-time control without uninstalling anything. Adapters that want to
    honor it call `enabled(key)`; the report always shows it."""
    val = (env if env is not None else os.environ).get(cap.flag_env, "")
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def supported(cap: Cap) -> bool:
    return cap.kind != "darwin" or sys.platform == "darwin"


def state(cap: Cap, env: Optional[dict] = None) -> str:
    """One word a human can act on:
      active       installed and allowed — the adapter's real path runs
      off          installed but DL_DISABLE_* set — fallback runs by choice
      missing      not installed — fallback runs (install cap's extra to flip)
      unsupported  wrong platform (macOS-only capability elsewhere)
      external     a service, not a library — probe it at runtime (--probe)
    """
    if cap.kind == "service":
        return "external"
    if not supported(cap):
        return "unsupported"
    if not installed(cap):
        return "missing"
    if disabled(cap, env):
        return "off"
    return "active"


def enabled(key: str, env: Optional[dict] = None) -> bool:
    """Single-call check for builders: installed AND not flagged off."""
    return state(_BY_KEY[key], env) == "active"


def report(env: Optional[dict] = None) -> list[dict]:
    return [{
        "key": c.key, "tier": c.tier, "title": c.title, "state": state(c, env),
        "extra": c.extra, "profiles": list(c.profiles), "modules": list(c.modules),
        "seam": c.seam, "kind": c.kind, "flag": c.flag_env, "note": c.note,
    } for c in CAPABILITIES]


def summary(env: Optional[dict] = None) -> dict:
    counts: dict[str, int] = {}
    for c in CAPABILITIES:
        s = state(c, env)
        counts[s] = counts.get(s, 0) + 1
    return counts


# --- optional live probe for the two external runtimes ---------------------------

def probe_service(cap: Cap, timeout: float = 1.5) -> bool:
    """Best-effort HTTP reachability for a `service` capability. Never raises."""
    urls = {
        "ollama_local": "http://127.0.0.1:11434/api/tags",
        "exo_cluster": "http://127.0.0.1:52415/v1/models",
    }
    url = urls.get(cap.key)
    if not url:
        return False
    try:
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout):
            return True
    except Exception:
        return False


# --- CLI: python -m dreamlayer.capabilities ---------------------------------------

_INSTALL_HINT = {
    None: "(manual — see note)",
}


def _hint(cap: Cap) -> str:
    if cap.kind == "service":
        return cap.note
    if cap.extra is None:
        return cap.note or "manual install"
    return f'pip install "dreamlayer[{cap.extra}]"'


def _print_plain(rows: list[dict], env: Optional[dict] = None) -> None:
    s = summary(env)
    order = ("active", "off", "missing", "unsupported", "external")
    line = " · ".join(f"{s.get(k, 0)} {k}" for k in order if s.get(k))
    print(f"DreamLayer capabilities — {line}")
    print(f"{'tier':<12} {'capability':<22} {'state':<12} switch on with")
    print("-" * 78)
    for r in rows:
        cap = _BY_KEY[r["key"]]
        print(f"{r['tier']:<12} {r['key']:<22} {r['state']:<12} {_hint(cap)}")


def _print_rich(rows: list[dict], env: Optional[dict] = None) -> bool:
    """Upgrade the table when the infra extra is present — dogfooding the
    dashboard dependency. Returns False (caller falls back) when rich is absent."""
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        return False
    style = {"active": "green", "off": "yellow", "missing": "dim",
             "unsupported": "dim", "external": "cyan"}
    t = Table(title="DreamLayer capabilities", title_justify="left")
    for col in ("tier", "capability", "state", "switch on with"):
        t.add_column(col)
    for r in rows:
        cap = _BY_KEY[r["key"]]
        t.add_row(r["tier"], r["key"],
                  f"[{style[r['state']]}]{r['state']}[/]", _hint(cap))
    Console().print(t)
    return True


def main(argv: Optional[Iterable[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dreamlayer.capabilities",
        description="Report which optional capabilities are switched on here.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--profile", choices=sorted(PROFILES),
                    help="only capabilities that profile installs")
    ap.add_argument("--probe", action="store_true",
                    help="also HTTP-probe the external runtimes (ollama/exo)")
    args = ap.parse_args(list(argv) if argv is not None else None)

    rows = report()
    if args.profile:
        rows = [r for r in rows if args.profile in r["profiles"]]
    if args.probe:
        for r in rows:
            if r["kind"] == "service":
                r["state"] = "active" if probe_service(_BY_KEY[r["key"]]) else "unreachable"

    if args.json:
        print(json.dumps({"capabilities": rows, "summary": summary(),
                          "profiles": {k: list(v) for k, v in PROFILES.items()}},
                         indent=2))
    else:
        if not _print_rich(rows):
            _print_plain(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
