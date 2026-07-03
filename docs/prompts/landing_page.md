You are a world-class creative front-end engineer and motion designer working inside the DreamLayer monorepo. Your mission: build a stunning, high-performance marketing landing page that makes people feel what DreamLayer is and want it immediately. Scroll-driven storytelling, refined motion, and — crucially — the ACTUAL product shown as if projected on the glasses, not a mockup. Push the design to the absolute limit of tasteful, world-class craft while staying fast on both desktop and mobile.

Positioning (get this exactly right):
- DreamLayer is an intelligence and memory LAYER for capable smart glasses — not a pair of glasses. It runs on the Brilliant Labs Halo today, and is built to come to any capable glasses next. Lead with "the layer," name Halo as the first supported hardware.
- Local-first and privacy-first is the wedge against big-tech smart glasses: your memories stay on your devices; the cloud is opt-in. Make this a felt promise, not fine print.
- The most jaw-dropping capabilities to headline: Veritas, the live fact-checker that catches a claim that does not hold up or that contradicts what someone told you before; answer-ahead, which surfaces the answer to a question the room just asked you in time to say it yourself; the Oracle assistant you can ask to do anything; and a memory that quietly remembers what you owe, where you left things, and who you are talking to.

Hard rules:
- No emojis anywhere.
- The interface shown MUST be the product's real HUD, not an artist's impression. This repo renders the true HUD; use it. A faked demo for a product whose headline feature is truth would undercut the whole pitch. You may stylize the WORLD/environment behind the HUD freely; the HUD overlay itself must be real renderer output.
- Accessible and honest: respect `prefers-reduced-motion` (provide calm static equivalents), keyboard navigable, sufficient contrast, real alt text. Do not claim shipping availability the product does not have — it is pre-hardware; use language like early access / waitlist / "coming to more glasses."

Real product assets (generate from the repo; verify exact commands before use):
- The emissive HUD composited over a POV "plate" (the waveguide look), as transparent overlays + previews + a full feature montage: `python -m dreamlayer.demo catalog <out>` and `python -m dreamlayer.demo all <out>` (see `host-python/src/dreamlayer/demo/`). These output transparent `overlays/*.png`, `poster.png`, `preview.gif`, and a `manifest.json` with timing/anchors — ideal for scroll-synced compositing and hero loops. The emissive keying (`demo/emissive.py`) makes the HUD read as light on the world; composite it over your own cinematic (or AI-generated) POV background plates.
- Individual HUD cards as transparent stills: `host-python/src/dreamlayer/hud/golden_images.py` `generate_golden(key, out_dir)` (keys from `hud/cards.py` `ALL_SAMPLES`).
- Motion GIFs of the real animations (focus physics, aurora, save/hark, spring settles): `scripts/export_meridian_motion.py` -> `out/meridian_motion/`.
- The brand's actual colors, type scale, and materials: `host-python/src/dreamlayer/hud/themes.py` and `docs/cinema_v2/` (Meridian Lumen + Solid). Match the product's visual language: deep near-black grounds, memory-teal and amber accents, additive glow, restrained typography. Read `phone-app/DESIGN.md` for the established aesthetic.

Experience to build (a single continuous scroll, cinematic and paced):
1. Hero: a first-person scene with the real HUD floating in the waveguide, one line that lands the idea ("A layer of intelligence for your glasses"), a subhead on local-first, and a primary call to action (join early access / get on the waitlist). Subtle idle motion; the HUD element uses a real render.
2. The problem / the shift: a short, confident beat on what memory and attention feel like today vs with DreamLayer.
3. Feature acts, each a scroll-pinned scene where the real HUD card animates in over a POV moment, synced to scroll progress: Veritas (the number that did not add up), answer-ahead (the answer before you speak), the Oracle (ask it anything), and memory (it remembered so you did not have to). Reuse the demo storyboards and manifest timings.
4. The whole product: a fast, elegant montage of the full feature set (the demo `catalog` master film is the reference), communicating breadth without clutter.
5. Privacy: a dedicated moment that makes local-first tangible and reassuring.
6. Hardware and the future: Halo today, built as a layer for any capable glasses next.
7. Close: a strong final call to action and a clean footer.

Craft targets:
- Scroll-driven, GPU-friendly animation (transform/opacity, will-change used sparingly). Use a scroll library or the native scroll-timeline/IntersectionObserver approach; whatever you choose, keep it buttery at 60fps and degrade gracefully. Parallax with depth, pinned scenes, and text that resolves as the HUD lands — never gratuitous, always in service of the story.
- Fully responsive: desktop is cinematic and wide; mobile is a tight vertical story that is just as beautiful. Test both. 9:16 hero material exists in the demo output for mobile.
- Performance: lazy-load heavy media, preload the hero, compress/serve modern formats (prefer video/webm or optimized frame sequences over huge GIFs for hero loops; the GIFs are fine as source to re-encode), avoid layout thrash, ship a fast LCP. Aim for excellent Lighthouse scores on mobile and desktop.
- Design system: derive the palette and type from the product tokens so the site and the glasses feel like one brand. Deep grounds, glowing accents, generous negative space, precise typography, one confident motion vocabulary.

Tech: choose a stack that best serves the animation ambition and stays fast (a static/SSG site with a modern framework is ideal; a self-contained build is fine). Decide, note the choice, and justify it briefly in the README. Put the site under `web/` (or `landing/`). Provide a working dev command and build command, and an assets pipeline that (re)generates the product renders from the repo tooling so the visuals never go stale.

Workflow: work on a feature branch. Generate the real assets first, then build the experience around them. Verify it runs, looks world-class on a desktop and a phone viewport, respects reduced motion, and has no emojis. Commit in logical chunks (no emojis in messages) and open a single PR with a short reel or screenshots of the result. Do not push to main.

The goal in one line: someone lands on this page, watches the real HUD think and remember and tell the truth in front of them, and cannot stop scrolling until they have signed up.
