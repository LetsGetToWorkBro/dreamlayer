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
from pathlib import Path
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
    gain: str = ""                # what improves over the built-in baseline, plainly
    impact: int = 0               # 1..5 — how much better than the fallback this is
    # the same story as `gain`, but as numbers a person can compare at a glance:
    # how well the OUT-OF-THE-BOX fallback does this job vs. with this installed,
    # both out of 5 (halves allowed; 0 = the fallback simply can't do it).
    before: float = 0.0
    after: float = 0.0
    # A build-only extra with no universal wheel (needs a compiler on the user's
    # machine). The rest of its pack is fully usable without it, so it must not
    # keep a pack pinned "partial" forever nor make "Retry the rest" loop.
    optional: bool = False

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
        "memory/vector_store.py (+chroma/lance/usearch siblings)",
        gain="baseline scans every memory linearly; this indexes them — recall stays instant at thousands of memories", impact=4, before=3, after=5),
    Cap("local_embeddings", "Real semantic embeddings, offline", "memory",
        ("sentence_transformers",), "memory", "memory/embedder_local.py",
        gain="baseline embeddings are mock vectors (or cloud); this makes memories truly searchable by meaning, offline", impact=5, before=1.5, after=5),
    Cap("memory_dedup", "Dedup + decay over the memory stream", "memory",
        ("mem0",), "memory", "lucid_recall/mem0_layer.py",
        gain="fallback dedup is exact-match; this merges near-duplicates and decays stale ones", impact=3, before=2.5, after=4),
    Cap("typed_docs", "Validated multimodal memory records", "memory",
        ("docarray",), "memory", "memory/doc_schema.py",
        gain="baseline records are plain dataclasses; this validates every field", impact=2, before=3, after=4),
    Cap("social_graph", "Relationship graph algorithms", "memory",
        ("networkx",), "memory", "social_lens/graph.py",
        gain="baseline graph is a dict of names; this adds paths, mutual friends, communities", impact=3, before=2, after=4),
    Cap("memory_graph", "Temporal knowledge-graph recall (what's connected, and when)", "memory",
        ("lightrag",), "memory-graph", "memory/graph_recall.py",
        note="opt-in; built by your own local model + embedder — nothing leaves the Brain",
        gain="vector recall finds what's similar; this follows entity + time edges, so 'what did the doctor say about my knee in March' resolves by connection, not just cosine", impact=4, before=2.5, after=4.5),
    Cap("memory_rehearsal", "Never forget a name — scheduled rehearsal (FSRS)", "memory",
        ("fsrs",), "srs", "memory/rehearsal_fsrs.py",
        note="the baseline expanding-interval scheduler always works; FSRS sharpens the timing",
        gain="baseline resurfaces a memory on a fixed doubling schedule; FSRS (the scheduler behind modern Anki) times each rehearsal to the real forgetting curve — names, faces, facts come back right before you'd lose them", impact=3, before=2.5, after=4.5),

    # --- voice ------------------------------------------------------------------
    Cap("voice_vad", "Neural speech/noise gating before ASR", "voice",
        ("silero_vad",), "voice", "orchestrator/vad_gate.py",
        gain="baseline gate is a loudness threshold; this tells speech from noise — fewer false wakes, less battery", impact=4, before=2, after=4.5),
    Cap("local_asr", "Local speech-to-text (no cloud audio)", "voice",
        ("faster_whisper",), "voice", "orchestrator/asr_faster_whisper.py",
        gain="baseline has no local transcription at all; this transcribes on-device, audio never uploads", impact=5, before=0, after=5),
    Cap("wake_word", "Acoustic wake-phrase spotting", "voice",
        ("openwakeword",), "voice", "orchestrator/wakeword.py",
        gain="baseline wakes on a regex over the transcript (ASR runs first); this fires on the wake phrase alone, so ASR only runs once addressed", impact=4, before=2.5, after=4.5),
    Cap("mic_capture", "Live microphone → the capture pipeline", "voice",
        ("sounddevice",), "voice", "orchestrator/capture.py",
        gain="baseline has no audio input at all; this reads the mic and drives the VAD→ASR→hub loop", impact=5, before=0, after=5),
    Cap("local_tts", "Juno speaks — on-device neural voice", "voice",
        ("piper",), "voice", "orchestrator/tts_piper.py",
        note="off by default (DL_JUNO_VOICE=1); needs a Piper voice model "
             "($DL_PIPER_VOICE or <cfg>/voices/*.onnx)",
        gain="baseline shows Juno's reply only as text on the glass; this speaks it aloud, offline — no cloud voice, audio never leaves the Brain", impact=4, before=0, after=4.5),
    Cap("kokoro_tts", "Juno's natural on-device voice (Kokoro-82M)", "voice",
        ("kokoro",), "voice", "orchestrator/tts_kokoro.py",
        note="off by default (DL_JUNO_VOICE=1); Kokoro-82M, Apache-2.0 — pick a voice with $DL_KOKORO_VOICE. Preferred over Piper when installed.",
        gain="baseline shows Juno's reply only as text; Kokoro-82M speaks it in a strikingly natural voice — tiny, offline, audio never leaves the Brain (far more lifelike than Piper)", impact=5, before=0, after=5),
    Cap("voice_clone", "Juno speaks in HER OWN voice (cloned, offline)", "voice",
        ("TTS",), "voice-clone", "orchestrator/voice_clone.py",
        note="opt-in (heavy); clones her timbre from the baked juno_*.mp3 clips "
             "via XTTS at inference — no training, no cloud",
        gain="baseline (or local_tts) speaks in a generic voice; this speaks in Juno's own voice, zero-shot cloned on-device from her existing clips", impact=3, before=0, after=4),
    Cap("live_interpret", "A live interpreter in your ear (speech↔speech)", "voice",
        ("transformers",), "interpreter", "rosetta_seamless.py",
        note="opt-in (heavy); SeamlessM4T-v2 on-device — audio never leaves the Brain",
        gain="Rosetta's eye translates text you look at; this translates the conversation you're IN — a foreign speaker's meaning is spoken into your ear, and your reply back in their language, offline", impact=4, before=0, after=4.5),
    Cap("sound_events", "Hear the world — alarms, doorbell, glass (not speech)", "voice",
        ("panns_inference", "sherpa_onnx"), "sound-events", "orchestrator/sound_events.py",
        note="opt-in; classifies sound TYPES, never voiceprints — a smoke alarm has no identity. "
             "Engine ladder: PANNs, else sherpa-onnx tagging ($DL_AUDIO_TAG_DIR)",
        gain="baseline hears nothing but speech; this notices the acoustic world — a smoke alarm, a kettle, a doorbell, glass breaking — and taps you (a safety + Deaf/HoH sense that's inherently privacy-safe)", impact=4, before=0, after=4),
    Cap("asr_moonshine", "Captions-class ASR, wearable-fast (Moonshine)", "voice",
        ("sherpa_onnx",), "voice", "orchestrator/asr_moonshine.py",
        note="Moonshine ONNX via sherpa-onnx — drop the model export in $DL_MOONSHINE_DIR",
        gain="faster-whisper is the accuracy floor; Moonshine beats Whisper-large-v3 at 250M params and runs short windows ~5x faster — the live-caption and voice-ask latency class the glasses need", impact=4, before=3, after=4.5),
    Cap("bird_song", "The world narrates itself — birdsong recognition", "voice",
        ("birdnetlib",), "birds", "orchestrator/bird_lens.py",
        note="opt-in; BirdNET (6,000+ species) on the ambient-audio rung — no human identity in a bird call",
        gain="the glasses hear alarms and doorbells; with BirdNET they also know the Song Sparrow singing over your walk — fully offline, Pi-Zero-sized, pure delight", impact=2, before=0, after=4,
        optional=True),   # birdnetlib has no universal wheel — needs a compiler
    Cap("asr_alignment", "Word-level timestamps for prosody", "voice",
        ("whisperx",), "asr-extra", "truth_lens/prosody_whisperx.py",
        gain="baseline has no word timing; this timestamps every word so tone becomes readable", impact=3, before=0, after=3.5),
    Cap("diarization", "Live who-is-speaking turns", "voice",
        ("diart",), None, "social_lens/diarize_diart.py", kind="manual",
        note="pip install diart",
        gain="baseline can't split speakers live; this tracks who is talking in real time", impact=3, before=0, after=3.5),

    # --- structured output / llm ------------------------------------------------
    Cap("structured_output", "Schema-constrained LLM intent parsing", "structured",
        ("outlines", "instructor"), "structured",
        "reality_compiler/intent_parser_llm.py",
        gain="baseline parses intents with regex on fixed phrasings; this understands free-form speech, schema-safe", impact=4, before=2, after=4.5),
    Cap("typed_models", "Veil-as-type-invariant memory records", "structured",
        ("pydantic",), "structured", "memory/models_pydantic.py",
        gain="baseline guard is a runtime check; this makes a veiled memory impossible to even construct", impact=3, before=3.5, after=5),
    Cap("typed_pipeline", "Traced RC stage pipeline", "structured",
        ("pydantic_ai",), "structured", "reality_compiler/pipeline_pydanticai.py",
        gain="baseline pipeline has no trace; this records what ran and where it failed", impact=2, before=2.5, after=4),
    Cap("llm_router", "One interface over ~100 LLM providers", "structured",
        ("litellm",), "llm", "ai_brain/litellm_backend.py",
        gain="baseline speaks to a few hand-wired providers; this routes across ~100 with fallback", impact=3, before=3, after=4.5),

    # --- intelligence -------------------------------------------------------------
    Cap("speaker_id", "Real voice fingerprints (ECAPA 192-d)", "intelligence",
        ("speechbrain",), "intelligence", "orchestrator/speaker_ecapa.py",
        gain="baseline voice-print is a hash that can't tell people apart; this gives real 192-d fingerprints", impact=4, before=1, after=4.5),
    Cap("nlp", "NER + dependency parse for commitments", "intelligence",
        ("spacy",), "intelligence",
        "orchestrator/commitment_nlp.py, social_lens/ner_spacy.py",
        note="`dreamlayer setup models` downloads the spaCy model this needs",
        gain="baseline pulls names/promises with regex that breaks on real sentences; this parses them properly", impact=5, before=2, after=5),
    Cap("commitment_ner", "Sharper commitments in meetings (GLiNER)", "intelligence",
        ("gliner",), "nlp-extra", "social_lens/commitment_ner.py",
        note="a tiny zero-shot NER; the deterministic extractor is always on",
        gain="baseline pulls action items with regex shapes ('I'll …'); this catches the ones a regex can't ('owner: Dana, ship by EOW')", impact=3, before=2.5, after=4),
    Cap("online_learning", "Per-user adaptation in real time", "intelligence",
        ("river",), "intelligence",
        "orchestrator/taste_river.py, dream_mode/weather_river.py",
        gain="baseline rankings are static; this adapts to your taste as you use it", impact=3, before=2.5, after=4),
    Cap("persona_tuning", "Human-in-the-loop persona classifier", "intelligence",
        ("hulearn",), "intelligence", "orchestrator/persona_humanlearn.py",
        gain="baseline persona filter is a no-op; this lets you tune it by example", impact=2, before=0, after=3),
    Cap("object_tracking", "Identity-stable multi-object tracking", "intelligence",
        ("supervision",), "intelligence", "dream_mode/track_supervision.py",
        gain="baseline tracker loses objects when they overlap; this keeps identity through occlusion", impact=3, before=2.5, after=4),
    Cap("facial_aus", "Micro-expression action units", "intelligence",
        ("libreface", "feat", "facetorch"), None, "truth_lens/au_backends.py",
        kind="manual", note="research installs; see adapter docstring",
        gain="baseline passes frames through untouched; this reads micro-expressions for the truth lens", impact=4, before=0, after=4),

    # --- vision -------------------------------------------------------------------
    Cap("vision_classify", "Object recognition (CLIP/YOLO/VLM)", "vision",
        ("ultralytics", "open_clip", "moondream"), "vision",
        "object_lens/classify_backends.py",
        gain="baseline declines 'what is this?' entirely; this recognizes objects locally", impact=5, before=0, after=5),
    Cap("coreml_ondevice", "Apple-silicon on-device inference", "vision",
        ("coremltools",), "vision", "object_lens/classify_backends.py",
        kind="darwin",
        gain="runs recognition on Apple silicon instead of CPU — faster, cooler", impact=2, before=3, after=4.5),
    Cap("text_ocr", "Read text in view (prices, menus, ISBNs)", "vision",
        ("rapidocr_onnxruntime",), "vision", "object_lens/ocr_backends.py",
        note="every OCR line is person- and PII-scrubbed before it surfaces",
        gain="baseline only has the vision model's guess at any text; this reads it for real, on-device — feeding the translation and taste lenses and the price/ISBN providers", impact=4, before=1.5, after=4.5),
    Cap("barcode_scan", "Scan a product barcode → nutrition & allergens", "vision",
        ("zxingcpp",), "vision", "object_lens/barcode_backends.py",
        note="decoding is on-device; the Open Food Facts lookup sends only the "
             "numeric code, and only when the Veil is down",
        gain="baseline can't read a barcode at all; this decodes it on-device and checks the product's allergens against your dietary rules — 'contains milk, soy — you avoid dairy'", impact=3, before=0, after=4),
    Cap("math_ocr", "Read an equation → LaTeX", "vision",
        ("pix2tex",), "math-ocr", "object_lens/vision_extras.py",
        gain="baseline can't read maths; this turns an equation on a board into LaTeX, on-device", impact=2, before=0, after=4),
    Cap("doc_read", "Read a document with its layout (forms, tables)", "vision",
        ("surya",), "doc-ocr", "object_lens/vision_extras.py",
        gain="baseline OCR gives loose lines; this reads a form/receipt with reading order and structure", impact=3, before=1.5, after=4),
    Cap("depth_sense", "A sense of distance from one camera", "vision",
        ("transformers",), "depth", "object_lens/vision_extras.py",
        note="relative proximity, not calibrated metres",
        gain="baseline is flat 2-D; this gives a proximity cue for what's in front of you (mobility, spatial anchoring)", impact=3, before=0, after=4),
    Cap("openvocab_find", "Find anything you can name (open-vocabulary)", "vision",
        ("ultralytics",), "vision", "object_lens/vision_extras.py",
        gain="baseline recognizes a fixed taxonomy; this finds any noun you say — 'my inhaler', 'a fire extinguisher'", impact=3, before=2, after=4.5),
    Cap("dream_style", "See the world as a painting (neural style transfer)", "vision",
        ("onnxruntime",), "dream-style", "dream_mode/dream_style.py",
        note="opt-in neural model on top of the always-on procedural painterly wash; on-device",
        gain="Dream Mode's built-in wash is a procedural poster filter; this runs a real fast-style-transfer net so your street comes back as a painting", impact=3, before=2.5, after=4),
    Cap("sky_sense", "Look up — the night sky, named (planets + ISS)", "vision",
        ("skyfield",), "sky", "object_lens/sky_lens.py",
        note="opt-in; computes from LOCAL data files in $DL_SKY_DIR (de421.bsp, stations.tle) — never downloads",
        gain="the glasses know the street but not the sky; this names the planets above the horizon and whispers when the ISS crosses — research-grade astronomy, fully offline", impact=2, before=0, after=4),
    Cap("scene_segment", "Segment what you're pointing at (FastSAM)", "vision",
        ("ultralytics",), "vision", "object_lens/vision_extras.py",
        gain="baseline has boxes only; this gives pixel-accurate masks for the glance target and scene density", impact=1, before=0, after=3.5),

    # --- causal ---------------------------------------------------------------------
    Cap("causal_fusion", "Causal inference over credibility channels", "intelligence",
        ("dowhy",), "causal", "truth_lens/causal_fusion.py",
        gain="baseline fuses credibility channels with fixed weights; this infers causally", impact=2, before=3, after=4),

    # --- infra ------------------------------------------------------------------------
    Cap("dashboard", "Live TUI status dashboard", "infra",
        ("rich",), "infra", "ai_brain/dashboard_rich.py",
        gain="baseline is plain log lines; this is a live status board", impact=2, before=2, after=4),
    Cap("fs_watch", "Instant reaction to file changes", "infra",
        ("watchdog",), "infra", "orchestrator/fs_watch.py",
        gain="baseline rescans on a timer; this reacts the moment a file changes", impact=2, before=3, after=4.5),
    Cap("lan_discovery", "Phone finds the Brain automatically", "infra",
        ("zeroconf",), "infra", "orchestrator/discovery_zeroconf.py",
        gain="baseline needs the Brain's IP typed in; this lets the phone find it automatically", impact=3, before=2.5, after=5),
    Cap("memory_explorer", "Browsable SQL view of the memory DB", "infra",
        ("datasette",), "infra", "memory/datasette_app.py",
        gain="baseline memory DB is a closed file; this makes it browsable for audit", impact=2, before=1, after=4),
    Cap("spatial_viz", "Spatial/temporal debug visualization", "infra",
        ("rerun",), "infra", "simulator/rerun_viz.py",
        gain="baseline spatial debugging is print statements; this draws it", impact=2, before=1.5, after=4),

    # --- privacy ------------------------------------------------------------------------
    Cap("pii_redaction", "ML PII scrubbing before any write", "privacy",
        ("presidio_analyzer",), "privacy", "memory/pii_presidio.py",
        note="regex fallback is always on; `dreamlayer setup models` downloads the "
             "spaCy model that activates the presidio path",
        gain="baseline scrubs emails/phones/cards/SSNs by regex; presidio adds robust detection of IBANs, crypto wallets, passports and licences in context — deliberately NOT names or places, so recall stays intact", impact=4, before=2.5, after=4.5),
    Cap("asym_signing", "Ed25519 provenance signatures", "privacy",
        ("cryptography",), "privacy", "reality_compiler/sign_crypto.py",
        note="HMAC fallback is always on",
        gain="baseline HMAC can be forged by anyone holding the key; Ed25519 can't", impact=3, before=3, after=5),
    Cap("structured_concurrency", "Veil-stop cancels every task", "privacy",
        ("anyio",), "privacy", "orchestrator/concurrency_anyio.py",
        note="asyncio fallback is always on",
        gain="baseline cancel-all is hand-rolled asyncio; this makes the Veil-stop guarantee structural", impact=2, before=3.5, after=5),
    Cap("stranger_defense", "Recognize people you've met; never a stranger", "privacy",
        ("presidio_analyzer",), "privacy", "object_lens/person_guard.py",
        note="deterministic name-shape + person-word guard is ALWAYS on; "
             "`dreamlayer setup models` activates the presidio NER layer; the "
             "visual person-detect backstop rides the vision pack (ultralytics)",
        gain="baseline defers a person by name-shape and a person-word list; this "
             "adds Presidio NER for a lone or odd-cased given name the shape rule "
             "misses, and (with the vision pack) a YOLO backstop for a human the "
             "VLM mislabels as an object", impact=3, before=3, after=4.5),

    # --- platform ----------------------------------------------------------------------
    Cap("plugin_entrypoints", "Plugins distributed as pip packages", "platform",
        ("pluggy",), "platform", "plugins/hookspecs.py",
        note="stdlib entry-point path works without it",
        gain="baseline plugins are wired by hand; this discovers pip-installed ones automatically", impact=3, before=2.5, after=4),
    Cap("event_bus", "Decoupled pub/sub over mesh traffic", "platform",
        ("pyee",), "platform", "confluence/emitter_pyee.py",
        gain="baseline mesh events go to one listener; this fans them out cleanly", impact=2, before=3, after=4),
    Cap("offline_translation", "Neural MT with no network", "platform",
        ("argostranslate",), "platform", "rosetta_argos.py",
        gain="baseline 'translation' returns the text unchanged; this actually translates, offline", impact=4, before=0, after=4.5),
    Cap("skia_render", "GPU-crisp HUD rasterizing", "platform",
        ("skia",), "platform", "hud/render_skia.py",
        gain="baseline PIL rendering is solid; this adds GPU-crisp strokes if you want them", impact=1, before=3.5, after=4),
    Cap("asgi_server", "Async FastAPI mirror of the Brain", "platform",
        ("fastapi",), "platform", "ai_brain/server_fastapi.py",
        gain="baseline stdlib server works; this adds async handlers + websockets alongside it", impact=2, before=3.5, after=4),
    Cap("frame_glasses", "Brilliant Frame as a second display", "platform",
        ("frame_sdk",), "platform", "bridge/frame_sdk.py",
        gain="baseline targets Halo only; this lights up a Brilliant Frame too", impact=2, before=0, after=3.5,
        optional=True),   # frame-sdk has no universal wheel — needs a compiler
    Cap("lsl_streams", "Lab Streaming Layer sensor export", "platform",
        ("pylsl",), "platform", "pipelines/lsl_transport.py",
        gain="baseline has no research export; this syncs sensors with lab tooling", impact=1, before=0, after=3),
    Cap("mlx_train", "Overnight LoRA fine-tune of the local model", "platform",
        ("mlx",), "platform", "rem/nightly_mlx.py", kind="darwin",
        gain="baseline model never adapts; this fine-tunes it overnight on your own memories", impact=4, before=2, after=4.5),

    # --- on-device speech (one ONNX engine behind the voice seams) ---------------
    Cap("onnx_speech", "Unified on-device speech engine (ASR + VAD + speaker + KWS)", "voice",
        ("sherpa_onnx",), "voice", "orchestrator/sherpa_backend.py",
        gain="baseline wires each voice seam to a separate model; this is one fast ONNX engine covering transcription, voice detection, speaker id and keyword spotting on-device", impact=4, before=2.5, after=4.5),

    # --- plugin isolation + cross-device sync ------------------------------------
    Cap("wasm_plugins", "In-process capability-enforced WASM plugin host", "platform",
        ("wasmtime",), "platform", "plugins/wasm_component_host.py",
        gain="baseline isolates an untrusted plugin in a subprocess; this runs a WASM guest in-process with ZERO ambient authority — it can only call the host functions its declared capabilities link", impact=4, before=3, after=5),
    Cap("crdt_sync", "Conflict-free repertoire sync across your devices", "platform",
        ("loro",), "sync", "reality_compiler/v2/vault_sync.py",
        gain="baseline keeps your Figments and memory on one device; this syncs them peer-to-peer across your devices — no server, no conflicts (a loro CRDT)", impact=3, before=1, after=4.5),

    # --- external runtimes (spoken to over HTTP; nothing to pip-import) -----------------
    Cap("ollama_local", "Local chat/vision/embeddings via Ollama", "services",
        (), None, "ai_brain/server/backends.py, ai_brain/gemma_backend.py",
        kind="service", note="http://127.0.0.1:11434",
        gain="without it the Brain leans on keyword search or cloud; with it, real local chat/vision", impact=5, before=1.5, after=5),
    Cap("exo_cluster", "One model across your machines via exo", "services",
        (), None, "ai_brain/exo_cluster.py",
        kind="service", note="http://127.0.0.1:52415",
        gain="single-machine inference only; this runs one bigger model across your machines", impact=2, before=3, after=4),
    Cap("mesh_range", "Tincan to the horizon — off-grid LoRa mesh", "platform",
        ("meshtastic",), "mesh", "orchestrator/mesh_bridge.py",
        note="opt-in; a local Meshtastic node (USB or LAN). Sends only the short tincan lines you typed — never memories or positions",
        gain="the tincan bond is Bluetooth-range; a $6 LoRa radio makes it miles-range with no wifi, no cell, no internet", impact=2, before=2, after=4),
    Cap("extism_plugins", "Plugins made incapable, not inspected (Extism)", "platform",
        ("extism",), "extism", "plugins/extism_host.py",
        note="opt-in; untrusted WASM guests with no WASI, no hosts, a memory cap and a timeout — write DreamLayer plugins in Rust/Go/JS",
        gain="baseline trust is capability scanning + subprocess isolation; an Extism guest simply HAS no filesystem/network to misuse — figment budgets, applied to plugins", impact=3, before=3, after=4.5),
    Cap("sound_pairing", "Pair by sound — the Brain sings the code (ggwave)", "platform",
        ("ggwave",), "soundlink", "soundlink.py",
        note="opt-in; a QR-free fallback — the Brain sings the short single-use pairing code as a near-ultrasonic chirp a phone catches. Carries only the same 5-minute code the QR does, never the token",
        gain="pairing needs a camera to scan the QR or a keypad to type the code; this hands the code over the air — a phone in earshot catches it, no camera, no typing (a real accessibility + hands-free win)", impact=2, before=0, after=4),
    Cap("immich_people", "Your photo library as memory (Immich)", "services",
        (), None, "memory/source_immich.py",
        kind="service", note="self-hosted Immich on your LAN (base URL + API key); public URLs are refused",
        gain="People and Yesterlight start empty; a self-hosted Immich fills them from the faces, places and dates you already own", impact=3, before=0, after=4),
    Cap("home_hud", "The glasses become a HUD for your house (Home Assistant)", "services",
        (), None, "orchestrator/home_bridge.py",
        kind="service", note="local-first Home Assistant on your LAN (Bearer token); narrow by design — open doors + safety alarms only",
        gain="leave home blind; with Home Assistant the glass taps you that the garage is still open, or that the smoke alarm is going", impact=3, before=0, after=4),
    Cap("location_spine", "Where you were, self-hosted (Dawarich)", "services",
        (), None, "memory/source_dawarich.py",
        kind="service", note="self-hosted Dawarich on your LAN; location history never transits the internet",
        gain="memories float free of place; Dawarich pins them — 'you were at the coffee shop on Vine when you said that'", impact=3, before=0, after=4),
    Cap("folder_sync", "Your memory follows you — device-to-device (Syncthing)", "services",
        (), None, "docs (SYNCTHING.md recipe)",
        kind="service", note="http://127.0.0.1:8384 — point Syncthing at the Brain's config dir; encrypted peer-to-peer, no third party ever holds bytes",
        gain="the Cloud card's biggest promise without the cloud: memories sync across your devices over battle-tested P2P TLS", impact=3, before=0, after=4),
    Cap("screen_memory", "Your screen becomes memory (screenpipe)", "services",
        (), None, "memory/source_screenpipe.py",
        kind="service", note="screenpipe app — read-only from ~/.screenpipe/db.sqlite",
        gain="the Brain remembers only what you tell it; with screenpipe running it also remembers what was on your screen — a Rewind-style memory before the glasses ship, all on-device", impact=4, before=0, after=4.5),
    Cap("desk_memory", "What you worked on, remembered (ActivityWatch)", "services",
        (), None, "memory/source_activitywatch.py",
        kind="service", note="http://127.0.0.1:5600 — a decade-trusted local tracker",
        gain="recall has no work-context spine; this indexes app + window-title time so 'what was I doing Tuesday' just answers — a gentler privacy gradient than screen capture", impact=3, before=0, after=3.5),
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


def wired_now(cap: Cap, env: Optional[dict] = None) -> bool:
    """DL_WIRED_<KEY> ∈ {1,true,yes,on} promotes a normally-dormant capability to
    'active' — set at RUNTIME by the subsystem that actually drives it, and only
    while it's running. The always-on ear, for example, sets DL_WIRED_VOICE_VAD /
    _LOCAL_ASR / _MIC_CAPTURE / … the instant it opens the microphone and clears
    them when it stops. So a cap in _NOT_WIRED stays honestly 'dormant' by default
    (nothing is driving it), yet reads 'active' precisely when a live path is —
    no false green, and no permanent under-report of a feature that IS on."""
    flag = "DL_WIRED_" + cap.key.upper()
    val = (env if env is not None else os.environ).get(flag, "")
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def supported(cap: Cap) -> bool:
    return cap.kind != "darwin" or sys.platform == "darwin"


# Installed-but-not-yet-wired capabilities: the library imports, but no live code
# path calls the adapter, so installing it gains the user nothing REACHABLE today.
# The 2026-07-22 reachability audit traced all 74 caps to their call sites and
# found these light "active" on import while doing nothing you can trigger. They
# report "dormant" (not "active") and DON'T inflate the awakening meter, so the
# panel never claims a feature is on when it isn't. As each is genuinely wired
# into a live path (phased), its key is removed here and it becomes active for
# real. test_capabilities_wired keeps this list honest against the catalog.
_NOT_WIRED = frozenset({
    # memory: adapters built, never consumed on a live path
    "memory_dedup", "typed_docs", "social_graph",
    # voice: the on-device "ear". Seven of these (voice_vad, local_asr,
    # mic_capture, asr_moonshine, onnx_speech, sound_events, bird_song) are now
    # driven by the Brain's opt-in ear (ai_brain/server/ear.py) — it sets
    # DL_WIRED_<KEY> the moment it opens the microphone, so wired_now() promotes
    # them from "dormant" to "active" precisely while listening is on, and they
    # fall back to "dormant" (not a false green) when it's off. They stay listed
    # here so the DEFAULT (ear off) is the honest "dormant". wake_word (no wake
    # engine yet), live_interpret (the SeamlessM4T interpreter), asr_alignment
    # and diarization are NOT promoted — they need the full Orchestrator path.
    "voice_vad", "local_asr", "wake_word", "mic_capture", "live_interpret",
    "sound_events", "asr_moonshine", "bird_song", "asr_alignment", "diarization",
    "onnx_speech",
    # vision: six frontier lenses (math_ocr, doc_read, depth_sense,
    # openvocab_find, scene_segment, sky_sense) are now reachable from the phone /
    # Live Lens via WorldLensHost.look_lens (?lens=…), each an on-device engine
    # that self-describes when its pack isn't installed — so they report "active"
    # once installed rather than "dormant". dream_style stays DORMANT: the reach-
    # able ?lens=dream path only ever runs the dependency-free painterly wash
    # (no caller constructs the neural stylizer with a model unless DL_DREAM_MODEL
    # is set), so onnxruntime being importable must NOT light the neural cap green.
    # coreml_ondevice likewise (a macOS Vision classify backend not on the live path).
    "coreml_ondevice", "dream_style",
    # intelligence / structured: adapters wired only in tests
    "speaker_id", "persona_tuning", "object_tracking", "facial_aus",
    "causal_fusion", "structured_output", "typed_models", "typed_pipeline",
    # platform / infra: no live loader / surface reaches these
    "plugin_entrypoints", "event_bus", "skia_render", "asgi_server",
    "frame_glasses", "lsl_streams", "mlx_train", "wasm_plugins", "crdt_sync",
    "mesh_range", "extism_plugins", "dashboard", "fs_watch",
    "lan_discovery", "spatial_viz",
    # privacy: the structural anyio veil-stop is never used (the flag-gate is).
    # (pii_redaction IS wired now — MemoryDB.add_memory runs default_redactor() on
    # every summary before the row is written, with a narrow contact/financial-only
    # entity policy so it never strips the names the product legitimately remembers.)
    "structured_concurrency",
})


def state(cap: Cap, env: Optional[dict] = None) -> str:
    """One word a human can act on:
      active       installed, allowed, AND wired into a live path — really on
      dormant      installed but not yet wired into the running app (no live
                   caller) — the honest state for a library that imports but does
                   nothing reachable; does NOT count toward the awakening meter
      off          installed but DL_DISABLE_* set — fallback runs by choice
      missing      not installed — fallback runs (install cap's extra to flip)
      unsupported  wrong platform (macOS-only capability elsewhere)
      external     a service, not a library — probe it at runtime (--probe)
    """
    # honor DL_DISABLE_* for services too — before the "external" verdict — so a
    # disabled service isn't silently reported reachable (audit 2026-07-14).
    if disabled(cap, env):
        return "off"
    if cap.kind == "service":
        return "external"
    if not supported(cap):
        return "unsupported"
    if not installed(cap):
        return "missing"
    if cap.key in _NOT_WIRED and not wired_now(cap, env):
        return "dormant"        # imports, but nothing live calls it yet
    return "active"             # ...unless a live subsystem set DL_WIRED_<KEY>


def enabled(key: str, env: Optional[dict] = None) -> bool:
    """Single-call check for builders: installed AND not flagged off. Returns
    False for an unknown key rather than raising a KeyError."""
    cap = _BY_KEY.get(key)
    return cap is not None and state(cap, env) == "active"


# --- display groups: the capabilities page, organised -------------------------
# Every Cap.tier is one of these keys. Each carries a human title and a one-line
# "what this group unlocks", in the order the panel shows them — so the page
# reads as a story ("Memory → Hearing → Sight → …"), not a flat dump. The panel
# renders a header + blurb per group from this table (payload["tiers"]).
TIERS: Tuple[Tuple[str, str, str], ...] = (
    ("memory", "Memory",
     "How much the Brain remembers — and how well it finds it again, by meaning and over time."),
    ("voice", "Hearing & Voice",
     "The ear and the mouth: hear speech and the world's sounds, and answer aloud — all on-device."),
    ("vision", "Sight",
     "See and read the world through a camera: objects, text, depth, documents, even the night sky."),
    ("intelligence", "Understanding",
     "The thinking layer — parse language, track who's who, read faces, reason about cause."),
    ("structured", "Precision",
     "Schema-locked output and typed pipelines, so the Brain answers in exact, checkable shapes."),
    ("privacy", "Privacy & Trust",
     "Scrub, sign, and defend — provable, on-device privacy you can verify."),
    ("platform", "Connectivity & Platform",
     "Bridges, plugins, and sync — how the Brain reaches your other devices and extends itself."),
    ("infra", "Operations",
     "Dashboards, discovery, and the quiet machinery that keeps the Brain running."),
    ("services", "Local Services",
     "Self-hosted apps on your own LAN the Brain reads as memory — configured, never the cloud."),
)
_TIER_ORDER = {k: i for i, (k, _t, _b) in enumerate(TIERS)}
_TIER_TITLE = {k: t for (k, t, _b) in TIERS}


def tiers() -> list[dict]:
    """The display-group metadata, in page order (title + what it unlocks)."""
    return [{"key": k, "title": t, "blurb": b} for (k, t, b) in TIERS]


def report(env: Optional[dict] = None) -> list[dict]:
    """Every capability as a panel row, GROUPED by display tier in page order
    (stable within a tier), so the panel's contiguous-group rendering holds no
    matter where a Cap sits in the source tuple."""
    rows = [{
        "key": c.key, "tier": c.tier, "tier_title": _TIER_TITLE.get(c.tier, c.tier),
        "title": c.title, "state": state(c, env),
        "extra": c.extra, "profiles": list(c.profiles), "modules": list(c.modules),
        "seam": c.seam, "kind": c.kind, "flag": c.flag_env, "note": c.note,
        "gain": c.gain, "impact": c.impact,
        "before": c.before, "after": c.after,
    } for c in CAPABILITIES]
    rows.sort(key=lambda r: _TIER_ORDER.get(str(r["tier"]), len(TIERS)))
    return rows


def summary(env: Optional[dict] = None) -> dict:
    counts: dict[str, int] = {}
    for c in CAPABILITIES:
        s = state(c, env)
        counts[s] = counts.get(s, 0) + 1
    return counts


# --- power stats: the number at the top that climbs as you install ------------
# The capabilities page opens with "how awakened is this Brain" — a single
# percent + level that RISES every time a capability flips to active. Only
# installable capabilities (a library you can add) count toward the meter, so it
# can actually reach 100% on a given machine; services and wrong-platform caps
# are reported alongside but never trap the percent below full.

# level bands (low, label) — the climb a person feels as they download more.
_LEVELS: Tuple[Tuple[int, str], ...] = (
    (0, "Dormant"), (10, "Waking"), (25, "Aware"),
    (45, "Attuned"), (65, "Sharp"), (85, "Ascendant"),
)


def _level_for(percent: float) -> Tuple[int, str]:
    """(index, label) for a completion percent — the highest band it clears."""
    idx, label = 0, _LEVELS[0][1]
    for i, (low, name) in enumerate(_LEVELS):
        if percent >= low:
            idx, label = i, name
    return idx, label


def power_stats(env: Optional[dict] = None) -> dict:
    """The awakening meter for the top of the capabilities page.

    Counts only INSTALLABLE capabilities (kind python/darwin that this machine
    supports): `unlocked` are the ones actually active, weighted by impact into
    a `power` score out of `power_total`. `percent` and `level` climb as packs
    install. `by_tier` powers per-group mini-bars; `services` reports the
    configurable local-service caps separately (they never gate the percent)."""
    unlocked = total = 0
    power = power_total = 0
    by_tier: dict[str, dict] = {}
    services_total = services_on = 0
    for c in CAPABILITIES:
        st = state(c, env)
        if c.kind == "service":
            services_total += 1
            # a service reads "external"; treat a disabled one as off, else on-ish
            if st != "off":
                services_on += 1
            continue
        # only PACK-INSTALLABLE caps (python/darwin) gate the meter, so installing
        # every pack the panel offers can actually reach 100%. `manual` caps
        # (extra=None, research-only pip installs like diart) are real but no pack
        # ships them — counting them would cap the panel at <100% forever (audit
        # 2026-07-21).
        if c.kind not in ("python", "darwin"):
            continue
        if st == "unsupported":
            continue                              # can't be had on this machine
        if st == "dormant":
            continue                              # installed but not wired to a
            #                                       live path — must not pad the
            #                                       meter (it delivers nothing yet)
        total += 1
        power_total += c.impact
        bucket = by_tier.setdefault(
            c.tier, {"title": _TIER_TITLE.get(c.tier, c.tier),
                     "unlocked": 0, "total": 0, "power": 0, "power_total": 0})
        bucket["total"] += 1
        bucket["power_total"] += c.impact
        if st == "active":
            unlocked += 1
            power += c.impact
            bucket["unlocked"] += 1
            bucket["power"] += c.impact
    percent = round(100 * power / power_total) if power_total else 0
    level_index, level = _level_for(percent)
    # order by_tier for display
    ordered = {k: by_tier[k] for k in sorted(by_tier, key=lambda t: _TIER_ORDER.get(t, len(TIERS)))}
    next_at = next((low for low, _n in _LEVELS if low > percent), None)
    # "fully awakened" means every installable power is ACTIVE — not merely at the
    # top level band (85%+): a machine can be Ascendant with powers still off, so
    # the panel must key that copy off `fully`, never off next_level_at (audit).
    fully = power_total > 0 and power >= power_total
    return {
        "unlocked": unlocked, "total": total,
        "power": power, "power_total": power_total,
        "percent": percent, "fully": fully,
        "level": level, "level_index": level_index, "level_max": len(_LEVELS) - 1,
        "next_level_at": next_at,
        "services_on": services_on, "services_total": services_total,
        "by_tier": ordered,
    }


# --- packs: curated upgrade bundles the panel offers ------------------------------
# A pack is a named, human-meaningful bundle of extras groups with an honest
# download estimate — the unit a person installs, so single capabilities never
# get overlooked. Order = display order; the first is the flagship.

@dataclass(frozen=True)
class Pack:
    key: str
    name: str
    tagline: str                  # what it buys you, one sentence
    extras: Tuple[str, ...]      # pyproject groups it installs
    size: str                    # honest approximate download
    impact: int                  # 1..5
    recommended: bool = False

    def caps(self) -> Tuple[Cap, ...]:
        return tuple(c for c in CAPABILITIES if c.extra in self.extras)


PACKS: Tuple[Pack, ...] = (
    Pack("recall", "Total Recall",
         "Semantic memory that actually understands — indexed, deduped, searchable by meaning, fully offline.",
         ("memory",), "~2–4 GB", 5, recommended=True),
    Pack("ears", "Sharp Ears",
         "Local speech: neural voice detection, on-device transcription, and Juno speaking in her own cloned voice. Audio never leaves this Mac.",
         ("voice", "asr-extra", "voice-clone"), "~2–4 GB", 4),
    Pack("eyes", "Clear Eyes",
         "Perception: object recognition, identity-stable tracking, real voice fingerprints, proper language parsing, and a painterly dream-mode lens.",
         ("vision", "intelligence", "causal", "dream-style"), "~3–5 GB", 4),
    Pack("guardian", "Guardian",
         "Deeper privacy and provenance: in-context PII scrubbing, Ed25519 signatures, structured cancellation.",
         ("privacy", "structured"), "~300 MB", 3),
    Pack("operator", "Operator",
         "Operations toolkit: pair a phone by sound and route across any LLM provider — working today — plus the libraries for LAN discovery, live dashboards, a sandboxed WASM plugin host, off-grid mesh and conflict-free sync as those surfaces come online.",
         ("infra", "llm", "platform", "sync", "soundlink", "mesh", "extism"), "~250 MB", 2),
    Pack("interpreter", "Interpreter",
         "A live interpreter in your ear: a foreign speaker's meaning spoken to you, and your reply back in their language — SeamlessM4T on-device, audio never leaves this Mac.",
         ("interpreter",), "~2–4 GB", 4),
    Pack("world-sense", "World Sense",
         "Senses beyond speech: alarms, doorbell and glass-breaking taps, birdsong ID, document and handwriting/math reading, and a sense of distance from one camera.",
         ("sound-events", "birds", "doc-ocr", "math-ocr", "depth"), "~1–2 GB", 3),
    Pack("stargazer", "Stargazer",
         "Look up and know the sky — planets, stars, and constellations named from your place and time, fully offline.",
         ("sky",), "~50 MB", 2),
    Pack("mind-palace", "Mind Palace",
         "Deeper memory: a temporal knowledge graph that answers what's connected and when, sharper commitment extraction from real meeting speech, plus spaced rehearsal that resurfaces a name right before you'd lose it.",
         ("memory-graph", "srs", "nlp-extra"), "~500 MB", 3),
)

_PACK_BY_KEY = {p.key: p for p in PACKS}

# Distribution names (as pip sees them, hyphenated) of the build-only extras
# that have no universal wheel: installing them needs a C/C++ toolchain the user
# may not have. The installer skips these instead of failing the whole pack, and
# pack_state excludes their caps from the "is this pack complete?" tally — so a
# pack whose only gap is a build-only extra reads installed, and "Retry the rest"
# doesn't loop forever re-attempting a dep that deterministically can't build.
# These are the pip distribution names for the caps marked optional=True
# (frame_glasses→frame-sdk, bird_song→birdnetlib); test_pack_optional_reqs keeps
# the two in lockstep so a newly-optional cap can't silently fall through.
PACK_OPTIONAL_REQS = frozenset({"frame-sdk", "birdnetlib"})


def pack_state(pack: Pack, env: Optional[dict] = None) -> str:
    """installed / partial / available — from the pack's python capabilities.

    Build-only optional caps (no universal wheel) don't count toward the tally:
    a pack is "installed" once everything installable is in, even if a compiler
    was missing for an optional extra."""
    caps = [c for c in pack.caps()
            if c.kind in ("python", "darwin") and supported(c) and not c.optional]
    have = [c for c in caps if installed(c)]
    if not caps:
        return "available"
    if len(have) == len(caps):
        return "installed"
    return "partial" if have else "available"


def packs_report(env: Optional[dict] = None) -> list[dict]:
    # Most impactful first — the packs a new Brain gains the most from lead the
    # page. Stable, so equal-impact packs keep their curated definition order.
    ordered = sorted(PACKS, key=lambda p: -p.impact)
    return [{
        "key": p.key, "name": p.name, "tagline": p.tagline, "size": p.size,
        "impact": p.impact, "recommended": p.recommended,
        "extras": list(p.extras), "state": pack_state(p, env),
        "caps": [c.key for c in p.caps()],
    } for p in ordered]


def extras_requirements(extra: str) -> list[str]:
    """The concrete requirement strings one extras group pins — what an
    installer actually feeds to pip. `pip install "dreamlayer[memory]"` can't
    work for a source checkout that isn't on PyPI, so packs install the
    group's requirements directly.

    Resolution order: the installed distribution's metadata (correct for any
    real install), falling back to parsing pyproject.toml (source tree, where
    editable metadata may predate newly added groups). Environment markers are
    preserved minus the `extra == ...` clause pip's metadata adds."""
    reqs: list[str] = []
    try:
        from importlib.metadata import requires
        for line in (requires("dreamlayer") or ()):
            if f'extra == "{extra}"' not in line:
                continue
            head, _, marker = line.partition(";")
            # drop the extra-clause; keep any real platform markers
            terms = [t.strip() for t in marker.split(" and ")
                     if t.strip() and "extra ==" not in t]
            reqs.append(head.strip() + ("; " + " and ".join(terms) if terms else ""))
    except Exception:
        pass
    if reqs:
        return reqs
    # source-tree fallback: read the group straight from pyproject.toml
    try:
        import tomllib
        from pathlib import Path
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        with open(pyproject, "rb") as f:
            deps = tomllib.load(f)["project"]["optional-dependencies"]
        return list(deps.get(extra, ()))
    except Exception:
        return []


def pack_site_dir(cfg_dir) -> Path:
    """The writable sidecar where the bundled (frozen) app installs pack wheels —
    ``<cfg_dir>/site-packages``. A code-signed .app/.exe is SEALED (installing
    into itself would break its signature + notarization), so packs land here and
    are added to ``sys.path`` at startup instead. A source install has a normal
    writable environment and doesn't use this."""
    return Path(cfg_dir).expanduser() / "site-packages"


def enable_pack_site(cfg_dir) -> Path:
    """Put the pack sidecar on ``sys.path`` so packs installed there are
    importable. Called once at startup (before the Brain builds) and idempotent.
    Adding it even when empty means a later install into the SAME dir becomes
    visible to find_spec after importlib.invalidate_caches() — so a pack can
    light up without a restart. Returns the sidecar path."""
    import site
    d = pack_site_dir(cfg_dir)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return d
    sd = str(d)
    if sd not in sys.path:
        site.addsitedir(sd)                    # honors any .pth and inserts on sys.path
        if sd not in sys.path:                 # addsitedir is a no-op if already known to site
            sys.path.insert(0, sd)
    return d


def pack_installer_available() -> bool:
    """True when this process can actually INSTALL a pack — either a normal
    (non-frozen) environment, or a frozen bundle that still carries an importable
    ``pip`` (installs go into the sidecar via pip --target). Drives the panel:
    only show a one-click 'Install pack' when it will really work; otherwise the
    honest 'runs on a source install'."""
    if not bool(getattr(sys, "frozen", False)):
        return True
    try:
        return find_spec("pip") is not None
    except BaseException:
        return False


def pack_requirements(pack_key: str) -> list[str]:
    """Everything pip needs for one pack. Unknown pack → empty (caller 400s)."""
    pack = _PACK_BY_KEY.get(pack_key)
    if pack is None:
        return []
    out: list[str] = []
    for extra in pack.extras:
        for r in extras_requirements(extra):
            if r not in out:
                out.append(r)
    return out


# --- optional live probe for the fixed-port external runtimes --------------------

# Services with a KNOWN local port. Configured-base services (Immich, Home
# Assistant, Dawarich) are deliberately absent — their base is user config, so
# a probe here can only lie about them.
_PROBE_URLS = {
    "ollama_local": "http://127.0.0.1:11434/api/tags",
    "exo_cluster": "http://127.0.0.1:52415/v1/models",
    "screen_memory": "http://127.0.0.1:3030/health",
    "desk_memory": "http://127.0.0.1:5600/api/0/info",
    "folder_sync": "http://127.0.0.1:8384/rest/noauth/health",
}


def has_probe_url(key: str) -> bool:
    return key in _PROBE_URLS


def probe_service(cap: Cap, timeout: float = 1.5) -> bool:
    """Best-effort HTTP reachability for a `service` capability. Never raises."""
    url = _PROBE_URLS.get(cap.key)
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
    style = {"active": "green", "off": "yellow", "dormant": "yellow",
             "missing": "dim", "unsupported": "dim", "external": "cyan"}
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
    # opt-in structured logging at the entrypoint (DL_LOG_JSON=1); a no-op
    # formatting change by default (audit 2026-07-14: configure at every entry).
    from .logging_setup import configure_logging
    configure_logging()
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
                # only services with a FIXED local port are probeable; a
                # configured-base service (Immich/HA/Dawarich) keeps "external"
                # rather than being branded unreachable while it's live on a
                # base we don't know here (refute 2026-07-21).
                if probe_service(_BY_KEY[r["key"]]):
                    r["state"] = "active"
                elif has_probe_url(r["key"]):
                    r["state"] = "unreachable"

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
