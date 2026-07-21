# The Frontier — staged integrations, and exactly why they're staged

DreamLayer's browser surfaces (Live Lens, panel) ship with a **no-egress CSP**:
no CDN scripts, no model downloads from the page. That is the product's proudest
claim — and it means a browser-side model can only ship one of two ways:
**vendored into the repo** (fine for ~10 MB of MediaPipe, wrong for 80 MB–4 GB
of weights) or **served from the Brain after a pack download** (the packs/
download-queue system, posture-gated). Everything below is staged behind that
pack path or behind hardware scope — the seams are already in the codebase.

## Already shipped, in case you're looking for it

| You asked for | It ships as |
|---|---|
| Kokoro (server) | `kokoro_tts` — Juno's preferred voice; panel + phone already speak via `/dreamlayer/tts` |
| sqlite-vec | `vector_search` (`memory/vector_store.py` + siblings) |
| model2vec | static embeddings (`memory/embedder_static.py`, `memory` extra) |
| Surya | `doc_read` (`object_lens/vision_extras.py`, current predictor API) |
| openWakeWord | `wake_word` (`orchestrator/wakeword.py`) |
| YAMNet-class sound tagging | `sound_events` (PANNs → sherpa-onnx ladder) + `bird_song` |

## Staged: browser-WASM (blocked on weight size, not code)

* **kokoro-js (zero-server browser voice).** Today the phone browser speaks by
  fetching WAV from the Brain (`/dreamlayer/tts`) — already zero-cloud. A truly
  *Brain-less* browser voice needs the ~86 MB Kokoro ONNX vendored or
  pack-served to the page. Seam: the packs system + the existing `junoSay()`
  in the panel/Live Lens. Ship as a `voice-web` pack.
* **bergamot-translator (offline browser translation).** Marian-WASM + per-pair
  models (20–40 MB each). Seam: `RosettaLens` already takes `translate_fn`;
  the Live Lens would load the pack-served WASM the same way it loads vendored
  MediaPipe. Ship as `rosetta-web` packs per language pair.
* **WebLLM / MLC (browser Q&A when the Brain is unreachable).** Multi-GB
  weights; strictly pack-served. Seam: the Live Lens ask box already falls back
  when the Brain is away — that's the switch point.
* **SmolVLM-256M via transformers.js (browser scene sentences).** ~500 MB
  runtime+weights today. Seam: the Live Lens `look()` path where MediaPipe
  results land; a pack-served model would add sentences to the same card.
* **Protomaps/PMTiles (the planet in one file).** Needs a JS map renderer on
  the page + a user-supplied `.pmtiles`. Seam: the Brain can already serve
  local files with Range requests; Waypath is the consumer. Ship with a
  `maps` pack that includes the renderer.

## Staged: firmware / hardware scope (not host-python's tree)

* **microWakeWord** — "Hey Juno" ON the glasses. The host `wake_word` cap is
  the near-ear fallback; the TFLite-micro build belongs in `halo-lua`/firmware.
* **WAMR** — figments' endgame: the same WASM core running on the glasses-class
  chip, collapsing the Lua stage. Firmware work; `reality_compiler` already
  compiles to WASM, so the host side is ready.
* **omiGlass / OpenGlass ($25 face computer).** The Brain's BLE seams are
  hardware-agnostic already; an ESP32-S3 bridge profile is a firmware
  contribution, and a wonderful community PR to invite.
* **Meshtastic on-glass** — the host bridge shipped (`mesh_range`); radios in
  the frame are hardware scope.

## Staged: the moonshot

* **Brush (gaussian-splat "walk through yesterday").** Rust/WebGPU scene
  reconstruction from a phone video. Degrades gracefully to a party trick, but
  even the trick needs a vendored WebGPU engine + per-scene training minutes.
  Seam when it lands: Yesterlight, as a pack-served viewer page.

**The rule this document encodes:** a capability appears in `capabilities.py`
only when the code in this repo actually does the thing today. Everything here
is a seam plus an honest reason, so the next contributor starts at the right
line instead of a blank page.
