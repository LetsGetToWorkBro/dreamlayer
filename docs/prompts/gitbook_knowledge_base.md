You are a senior technical writer and systems analyst working inside the DreamLayer monorepo. Your mission: read and understand the ENTIRE codebase across every runtime, then produce a complete, in-depth GitBook-style knowledge base that documents literally everything about DreamLayer — the glasses experience, the phone app, and the desktop (Mac "Brain") app — leaving nothing out. It must be accurate to the code, richly illustrated with the product's REAL rendered cards, animations, and screenshots, and written to communicate the vision so clearly it excites and impresses the reader. Also update any README or docs that have gone stale.

Hard rules:
- No emojis anywhere, in the docs or in commits.
- Accuracy over hype. DreamLayer's flagship feature is a live fact-checker; a knowledge base that overstates or invents features would be self-defeating. Every claim must trace to code. Clearly distinguish what is fully implemented from what is a documented "device seam" (e.g. camera frames, ASR, on-device face embedding, the cloud verify call) or pre-hardware. This is a pre-hardware build.
- Use the product's ACTUAL visuals, generated from the repo's own tooling — never hand-drawn mockups or stock imagery for the UI.

Orientation (verify exact paths/signatures yourself before relying on them):
- Four runtimes. Phone app: `phone-app/` (Expo / React Native; screens under `phone-app/app/`, state in `phone-app/src/state/useBrainStore.ts`, design system in `phone-app/src/ui/`, see `phone-app/DESIGN.md`). Glasses "orchestrator" hub: `host-python/src/dreamlayer/orchestrator/`. Mac mini "Brain" server: `host-python/src/dreamlayer/ai_brain/server/` (HTTP API, endpoints under `/dreamlayer/*`) plus its control panel (HTML). Device firmware: `halo-lua/` (the Lua that runs on the Brilliant Labs Halo glasses; HUD in `halo-lua/display/`).
- The HUD has two mirrored renderers: the device `halo-lua/display/renderer.lua` (source of truth, animated) and a Python mirror `host-python/src/dreamlayer/hud/renderer.py` (drives goldens and the demo). Card payloads and a sample gallery live in `host-python/src/dreamlayer/hud/cards.py` (`ALL_SAMPLES`). Design docs: `docs/cinema_v2/` (`lumen.md` motion, `solid.md` materials, plus focus/horizon/testimony/etc.).
- Cross-runtime integration is documented in `docs/INTEGRATION.md`; the AI stack in `docs/AI_BRAIN.md` (if present). Read these first; they are the spine.
- Tooling you will use to generate REAL assets:
  - Every HUD card as a still: `host-python/src/dreamlayer/hud/golden_images.py` `generate_golden(key, out_dir)` (keys are the `ALL_SAMPLES` keys). Device-accurate goldens: `host-python/src/dreamlayer/hud/export_cinema_v2_golden.py`.
  - Full feature demo as overlays + previews + a master film + a narration script: `python -m dreamlayer.demo catalog <out>` and `python -m dreamlayer.demo all <out>` (see `host-python/src/dreamlayer/demo/` and its README / STORYBOARDS / AI_VIDEO docs). These render the emissive HUD (waveguide look) over a plate and produce `preview.gif`, `poster.png`, transparent `overlays/`, `manifest.json`, and `catalog.md`.
  - Motion GIFs (springs, aurora, focus physics, save/hark) via `scripts/export_meridian_motion.py` -> `out/meridian_motion/`.
  - The Mac Brain control panel is HTML served by the Brain server; Chromium + Playwright are available (PLAYWRIGHT_BROWSERS_PATH is set — do not run `playwright install`). Boot the Brain and screenshot every panel view.
  - Phone screens are React Native. If an Expo web export can be stood up and screenshotted headlessly, do so; otherwise treat live phone screenshots as a seam, render the screens' logic/states from the store, and clearly note the seam. Do not fake screenshots.

Method:
1. Do a broad read-only sweep of all four runtimes and the docs before writing a word. Build a full feature inventory by reading the code — do not rely on memory or existing prose. Grep the orchestrator, the Brain server routes, the phone store/screens, the Lua card set, and the tests (tests are the most honest spec of behavior).
2. Cross-check the feature inventory against `docs/INTEGRATION.md` and the demo `catalog.py` FEATURES list so nothing is missed.
3. Generate the asset library (cards, demo clips, motion, panel screenshots) into an assets folder inside the GitBook, and embed the real images/GIFs beside the prose.
4. Write the GitBook. Then re-read to ensure every feature, setting, mode, and toggle in the code appears somewhere.

Deliverable — a GitBook under `docs/gitbook/` (or `knowledge-base/`) with a `SUMMARY.md` table of contents and one markdown file per section. Suggested structure (expand as the code demands; do not drop anything you find):
- What DreamLayer is: the vision, local-first and privacy-first stance, and the positioning as an intelligence layer for any capable smart glasses (Halo supported today).
- Ecosystem architecture: the four runtimes, how they talk, the pairing/BLE and HTTP paths, and the "device seam" concept.
- The glasses experience: every HUD card (name, when it appears, what it shows, its materials and animation), the Meridian design language (Lumen motion + Solid materials), earcons and haptics. One real render per card.
- The Oracle: wake methods, the command router (everything "Hey Oracle" can do), its persona, and how it learns the user (the user model) and what it stores.
- Perception and memory: live captions, look-to-dossier (Social Lens), object/commitment recall, anticipation/proactive cards, rewind / time-scrub, the morning brief.
- Truth and discernment: Veritas (self-contradiction + world check), Truth Lens (delivery/deception read), the Discernment fusion, and answer-ahead. Be precise about the verify seam and the calibration behavior.
- Attention and focus: the "Listen!" / "Watch out!" attention policy, focus mode, the proactive cue picker.
- Progression: the Saga (ranks, levels, achievements) and how events unlock them.
- Privacy and control: the Privacy Veil, incognito, focus, consent, private zones, the three brain switches, egress logging, retention, quiet hours.
- The phone app: every screen and every setting/toggle, with real screens or clearly-labeled state renders.
- The desktop Brain app: every panel view, the pairing and connector flows, the AI/model setup wizard, folders/indexing, activity log, backup/restore, ops controls. Real panel screenshots.
- The AI Brain deep dive: the tiered router (device -> laptop -> cloud), Ollama, the cloud opt-in and what can and cannot leave the device, embeddings, semantic search.
- Reference: an exhaustive settings/modes table; the full endpoint list; the full card list; the earcon/haptic map.
- Hardware and seams: Halo, the EMG wristband option, and a clear "implemented vs seam vs pre-hardware" matrix.
- For builders: repo layout, how to run each runtime, the test suites (pytest, tsc, the Lua raster harness), and the demo/video pipeline.
- Glossary of every DreamLayer term (Oracle, Veritas, Candor, Discernment, Saga, Halo, Meridian, Lumen, Solid, Hark, etc.).

Also: find and update any README or doc that is now outdated (root README, `phone-app/` README/DESIGN, `host-python/` readmes, testing guide, `docs/INTEGRATION.md`). Fix stale feature lists, paths, and instructions; do not rewrite what is still correct.

Quality bar: this should read like the reference manual for a shipping, world-class product — precise, complete, and genuinely exciting, with the real interface shown throughout. When you are unsure whether something is implemented, read the tests; if still unsure, mark it as a seam rather than asserting it.

Workflow: work on a feature branch, commit in logical chunks with clear messages (no emojis), verify assets actually render and embed correctly, then open a single PR summarizing the knowledge base and the README updates. Do not push to main.
