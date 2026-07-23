"""ai_brain/server/world_lens.py — the on-glass World lenses, hosted in the Brain.

In production the Halo runs the world lenses on-device: you look at a thing and
the Object Lens (Juno) or TasteLens draws a panel on the glass. Pre-hardware,
there is no glass and no NPU — so this module lets the **Mac-mini Brain** run
that exact compute, and a phone photo becomes the camera. It is the honest
stand-in the phone's `Look` screen talks to: same lenses, same providers, same
privacy gate — just the Brain doing the recognising instead of the glasses.

What it wires:

  * an :class:`~dreamlayer.object_lens.ObjectLens` whose recogniser is the
    VLM-backed :class:`VisionSightingRecognizer` (reusing the Brain's own vision
    model to read structured fields off the photo — a price, a title — with the
    dependency-free heuristic ladder as the offline fallback);
  * a :class:`TasteLens` that reads a shelf/menu through the same vision seam;
  * the Brain's **installed plugins**, loaded through the very same
    ``PluginStore.load_installed`` path the Orchestrator uses — so a connector
    like the Currency converter lights up on a look exactly as it will on-glass.

Privacy: the lens is gated on the Brain's incognito posture (a veiled look is
blind, never a guess), identical to the on-device gate.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger("dreamlayer.world_lens")

# the shelf/menu read prompt — mirrors orchestrator.ops_world_lenses._taste_read
_TASTE_PROMPT = (
    "List the products or dishes in view for a shopping assistant, one per "
    "line: NAME | ingredients | price | rating(0-5). Use '?' for anything "
    "unknown. Nothing else.")


class _LookGate:
    """A privacy gate reflecting the Brain's incognito posture. ``allow_capture``
    is False while incognito, so a deliberate look then returns blind — the same
    honest "veiled = deliberately blind" contract the on-device gate gives. Fails
    CLOSED when the posture can't be read (unknown trust signal → veiled)."""

    def __init__(self, brain):
        self._brain = brain

    def allow_capture(self) -> bool:
        try:
            return not bool(self._brain.incognito_now())
        except Exception:
            return False

    def allow_recall(self) -> bool:
        return self.allow_capture()


class _BrainVisionRouter:
    """Adapts the Brain's vision backend to the object-lens ``AIProvider`` router
    contract (``has_vision`` / ``explain(frame, label, want)``), so the AI
    explainer row works host-side just as it does on-glass."""

    def __init__(self, brain):
        self._brain = brain

    def has_vision(self) -> bool:
        # only a real local vision backend reads images here; cloud text models
        # do not, so has_vision reflects the backend, honestly.
        return getattr(self._brain, "_backend", None) is not None

    def explain(self, frame, label, want: str = "quick"):
        from .backends import vision_answer, is_local_endpoint
        from ...object_lens.vision_recognizer import frame_to_b64
        backend = getattr(self._brain, "_backend", None)
        cfg = getattr(self._brain, "config", None)
        url = getattr(cfg, "ollama_url", "") if cfg is not None else ""
        # A REMOTE vision backend (off-box ollama_url) receiving the wearer's
        # photo IS cloud egress — gate it on the privacy posture and COUNT it,
        # instead of silently shipping the frame off-box uncounted and unstoppable
        # by the wearer's on-device-only posture (refute 2026-07-18: the look path
        # never read no_cloud and never bumped cloud_calls, unlike ask). The
        # default local backend (127.0.0.1 ollama, MLX, none) is not egress.
        if url and not is_local_endpoint(url):
            try:
                if self._brain.incognito_now():
                    return None                  # on-device-only → no remote vision
            except Exception:
                return None                      # unreadable posture → fail closed
            try:
                self._brain.bump_cloud_calls()
            except Exception:
                pass
        return vision_answer(backend, label, frame_to_b64(frame), want)


class WorldLensHost:
    """Runs the Object Lens + TasteLens inside the Brain. Built once and cached
    on the Brain (``Brain.world_lens()``); presents the small orchestrator-shaped
    surface ``PluginStore.load_installed`` needs (``load_plugins`` /
    ``plugin_context``) so installed plugins load through the shared path."""

    def __init__(self, brain, isolate: str = "untrusted"):
        self.brain = brain
        self.health = getattr(brain, "health", None)
        from ...orchestrator.capability_log import CapabilityLedger
        self.capability_log = CapabilityLedger()
        self.privacy = _LookGate(brain)
        # The SAME hot-memory primitive the glasses run (orchestrator.py wires
        # SemanticRingBuffer(cfg.passive_ring_capacity)): typed MemoryEvents
        # only, in-memory only, never raw pixels and never disk. Deliberate
        # looks append the canonical object event (pipelines/ingest.py shape),
        # so MemoryProvider's "seen before N× · last at …" rows are REAL here —
        # not a stub — and erase/rebuild drops the ring with the host.
        from ...memory.ring_buffer import SemanticRingBuffer
        self.ring = SemanticRingBuffer(64)          # glasses default capacity
        self.mesh = None
        # The auto-lens-selector: the SAME PerceptionRouter + GlanceArbiter the
        # glasses run, so a look decides its own lens (fire the clear winner,
        # offer a chooser when ambiguous) instead of making you pick. Built here
        # rather than left None so the live path gets the arbiter, not a dropdown.
        _perception = None
        _arbiter = None
        try:
            from ..perception import PerceptionRouter
            from .glance_live import build_live_arbiter
            _perception = PerceptionRouter()
            _cfg = getattr(brain, "cfg_dir", None)
            _priors = os.path.join(str(_cfg), "glance_priors.json") if _cfg else None
            _arbiter = build_live_arbiter(_priors)
        except Exception as exc:                 # noqa: BLE001 — auto-glance is optional
            log.warning("[glance] arbiter unavailable: %s; manual lenses only", exc)
        self.perception = _perception
        self.glance_arbiter = _arbiter
        self.plugin_events = None
        self.db = None                      # per-plugin settings stay in-memory
        self._router = _BrainVisionRouter(brain)
        self._shop_providers: list = []

        from ...object_lens import (ObjectLens, AIProvider, DietaryProfile,
                                    LabelProvider, RosettaProvider)
        from ...object_lens.recognizer import ObjectRecognizer
        from ...object_lens.vision_recognizer import VisionSightingRecognizer
        recognizer = ObjectRecognizer(
            classify_fn=VisionSightingRecognizer(
                self._describe, available=self._router.has_vision))
        # ring=… auto-registers MemoryProvider — the SAME built-in provider set
        # the glasses wire in orchestrator._init_object_lenses (Memory + AI +
        # Label + Rosetta), so a phone look runs every lens a glance does.
        # Laptop/Car/Plant stay app-layer seams on both surfaces, by design.
        self.object_lens = ObjectLens(ring=self.ring, recognizer=recognizer,
                                      privacy=self.privacy)
        self.object_lens.registry.register(AIProvider(self._router))

        from ...orchestrator.taste import TasteLens
        self.dietary = DietaryProfile()
        # Rosetta exactly as the glasses build it: the offline Argos backend
        # when installed (extras `platform` — the Operator pack), else the
        # identical no-op (translate_fn=None) — never a fake translation.
        from ...rosetta import RosettaLens
        from ...rosetta_argos import ArgosTranslator, make_translate_fn
        self.rosetta = RosettaLens(
            translate_fn=make_translate_fn() if ArgosTranslator.available else None,
            engine="argos")
        self.object_lens.registry.register(LabelProvider(self.dietary, self.ring))
        self.object_lens.registry.register(RosettaProvider(self.rosetta))
        # Barcode → Open Food Facts → your dietary rules. Only the numeric code
        # leaves, and only when the Veil is down (allow_capture) — the same gate
        # the taste read uses; your DietaryProfile never leaves the device.
        from ...object_lens.barcode_lens import BarcodeFoodProvider
        from ...plugins.openfoodfacts import _default_fetch, off_barcode_fn
        # a snappy fetch (no retries, 2s) so a slow OFF can't hold a glance-pool
        # worker for the default 13.5s retry budget and starve the other lenses
        _off = off_barcode_fn(lambda u: _default_fetch(u, retries=0, timeout=2.0))
        self.object_lens.registry.register(BarcodeFoodProvider(
            self.dietary, lookup_fn=_off,
            allow_network=self.privacy.allow_capture))
        self.taste_lens = TasteLens(read_fn=self._taste_read,
                                    profile=self.dietary, shop_fn=self._taste_shop)

        self._load_installed_plugins(isolate)

    # -- the Brain's vision seam ---------------------------------------------

    def _describe(self, prompt: str, image_b64: Optional[str]) -> str:
        backend = getattr(self.brain, "_backend", None)
        if backend is None or not hasattr(backend, "describe"):
            return ""
        # Same remote-vision gate as _BrainVisionRouter.explain: a REMOTE
        # ollama_url receiving the wearer's photo IS egress — blocked while the
        # egress shield is up, counted otherwise. The recognizer's describe path
        # ships the same pixels as explain and must ride the same gate, or the
        # look's "frames stay with your Brain" claim quietly breaks the moment
        # someone points ollama_url off-box.
        from .backends import is_local_endpoint
        cfg = getattr(self.brain, "config", None)
        url = getattr(cfg, "ollama_url", "") if cfg is not None else ""
        if url and not is_local_endpoint(url):
            try:
                if self.brain.incognito_now():
                    return ""                # nothing leaves → no remote vision
            except Exception:
                return ""                    # unreadable posture → fail closed
            try:
                self.brain.bump_cloud_calls()
            except Exception:
                pass
        try:
            return backend.describe(prompt, image_b64) or ""
        except Exception as exc:
            log.warning("[world_lens] vision describe failed: %s", exc)
            return ""

    # -- plugin loading (the orchestrator-shaped surface) --------------------

    def _plugin_capabilities(self) -> frozenset:
        try:
            caps = set(self.brain.plugin_capabilities())
        except Exception:
            return frozenset()
        # Veil-aware, fail-closed: the world lens is REMOTELY reachable, so a
        # plugin gets `network` egress ONLY when the privacy gate CLEARLY allows
        # capture — mirroring the orchestrator's hardened grant (ops_plugins.py,
        # "silence is not permission"). The Brain's own plugin_capabilities grants
        # network on `not lan_only` alone, blind to the incognito/veil posture, so
        # strip it here whenever capture isn't allowed (refute 2026-07-18).
        try:
            if not self.privacy.allow_capture():
                caps.discard("network")
        except Exception:
            caps.discard("network")            # unreadable posture → no egress
        return frozenset(caps)

    def plugin_context(self, renderer=None, config=None):
        from ...plugins import PluginContext
        return PluginContext(
            object_registry=self.object_lens.registry,
            glance_arbiter=self.glance_arbiter, brain=self._router,
            perception=self.perception, renderer=renderer,
            capabilities=self._plugin_capabilities(), ring=self.ring,
            veil=self.privacy, mesh=self.mesh,
            shop_registry=self._shop_providers, config=config,
            events=self.plugin_events, db=self.db)

    def load_plugins(self, plugins, renderer=None, config=None):
        from ...plugins import PluginRegistry
        reg = PluginRegistry(self.plugin_context(renderer, config),
                             health=self.health, caplog=self.capability_log)
        res = reg.load_all(plugins)
        reg.start_all()
        self.plugins = reg
        for name, obj in reg.plugins.items():
            self.capability_log.grant(name, getattr(obj, "requires", ()))
        return res

    def _load_installed_plugins(self, isolate: str) -> None:
        """Load the Brain's installed plugins into these registries, best-effort.
        Any failure (a jail that can't start here, a bad package) degrades to
        "the object lens still serves via the AI explainer" — a look never dies
        because a plugin wouldn't load."""
        store = getattr(self.brain, "plugins", None)
        if store is None:
            return
        try:
            # require_sandbox=True: the world lens is REMOTELY reachable (POST
            # /brain/look from a paired phone) and runs UNTRUSTED installed
            # plugins. On a host without a kernel sandbox (bwrap/nsjail/WASM) the
            # jail silently degrades to a plain subprocess with the full host-user
            # OS authority — an untrusted plugin could read the pairing token /
            # memory store off disk and egress it, never crossing the RPC surface.
            # Fail CLOSED: an untrusted plugin that can't be sandboxed is NOT
            # loaded (the object lens + first-party providers still serve); a WASM
            # runtime or a kernel sandbox re-enables third-party plugins here
            # (refute 2026-07-18: this was the first production path to run
            # installed plugins, and it ran them unsandboxed on the Mac Brain).
            store.load_installed(self, isolate=isolate, require_sandbox=True)
        except Exception as exc:
            if self.health is not None:
                self.health.record_failure("world_lens:plugins", exc)
            log.warning("[world_lens] plugin load degraded: %s", exc)

    # -- TasteLens seams (mirror the orchestrator's) -------------------------

    def _taste_read(self, frame) -> list:
        if not self.privacy.allow_capture():
            return []
        from ...object_lens.vision_recognizer import frame_to_b64
        from ...orchestrator._ops_helpers import _parse_taste_reply
        text = self._describe(_TASTE_PROMPT, frame_to_b64(frame))
        return _parse_taste_reply(text) if text else []

    def _taste_shop(self, label, attrs) -> dict:
        merged: dict = {}
        for fn in self._shop_providers:
            try:
                data = fn(label, attrs) or {}
            except Exception:
                continue
            for k, v in data.items():
                merged.setdefault(k, v)
        return merged

    # -- the looks ------------------------------------------------------------

    def veiled(self) -> bool:
        return not self.privacy.allow_capture()

    def _remember_sighting(self, label: str) -> None:
        """Append the canonical object event (pipelines/ingest.py shape) to the
        hot ring AFTER the panel builds, so "seen before" counts PRIOR sightings
        — the same order passive capture feeds the glasses' ring. In-memory
        only; the veil gate already ran (a veiled look never reaches here)."""
        key = (label or "").strip().lower()
        if not key:
            return
        try:                                 # veil re-check: a look IN FLIGHT when
            if not self.privacy.allow_capture():   # the veil dropped must not land
                return                             # (TOCTOU — refute 2026-07-21)
        except Exception:
            return
        try:
            import time as _t
            from ...pipelines.ingest import MemoryEvent
            # age-parity with the glasses' hot store: the REM sweep composts
            # ring events older than 24h nightly; the Brain has no night, so
            # purge on append (refute 2026-07-21, retention-parity finding)
            self.ring.purge_before(_t.time() - 24 * 3600)
            self.ring.append(MemoryEvent(kind="object", summary=key,
                                         confidence=0.90, meta={"object": key},
                                         source="look"), source="look")
        except Exception:
            pass                             # memory is best-effort, a look never dies

    def look(self, frame, facet: Optional[str] = None):
        """Recognise the object in a photo and build its panel (or None)."""
        facets = {facet} if facet else None
        panel = self.object_lens.look(frame, facets=facets)
        if panel is not None:
            self._remember_sighting(getattr(panel.sighting, "label", ""))
        return panel

    def look_sighting(self, sighting, facet: Optional[str] = None):
        """Build a panel for a caller-supplied sighting (deterministic mode: the
        phone/tests pass a label + attributes directly, no model needed). Honours
        the veil and the person-defence, exactly like a recognised look."""
        if not self.privacy.allow_capture():
            return None
        from ...object_lens import person_guard
        # Same layered person defence the image route applies (denylist +
        # name-shape + optional Presidio) — the label route reached build_panel
        # through here and previously ran only the deterministic check, so a
        # lone given name Presidio would catch slipped onto the glass (refute
        # 2026-07-18). No frame on this route, so the visual layer is N/A.
        if person_guard.defers_person(sighting.label):
            return None                     # a person → Social Lens, never here
        facets = {facet} if facet else None
        panel = self.object_lens.registry.build_panel(sighting, facets=facets)
        if panel is not None:
            self._remember_sighting(getattr(sighting, "label", ""))
        return panel

    def taste(self, frame, budget: Optional[float] = None):
        """Read a shelf/menu and rank it against the wearer's rules."""
        if not self.privacy.allow_capture():
            return None
        return self.taste_lens.look(frame, budget=budget)

    # -- deliberate "look closer" lenses -----------------------------------
    # These are the frontier lenses that always lived on the Orchestrator's
    # glance hub, which the shipped Brain never ran — so they were unreachable
    # from the phone/Live Lens. look_lens() routes a look to the on-device
    # engine for the chosen lens (each a lazy adapter with a neutral fallback),
    # so the feature is REACHABLE the moment its pack is installed. Readers are
    # cached on the host (the host itself is cached per-Brain and rebuilt on
    # config change), so a heavy model loads once, not per look.

    def _extra(self, name: str):
        """Lazily build + cache a vision_extras reader by name."""
        cache: dict = getattr(self, "_extras_cache", None) or {}
        self._extras_cache = cache
        if name not in cache:
            from ...object_lens import vision_extras as vx
            builders = {
                "math": vx.MathOcrReader, "doc": vx.DocReader,
                "depth": vx.DepthReader, "find": vx.YoloWorldFinder,
                "segment": vx.FastSamSegmenter,
            }
            try:
                cache[name] = builders[name]()
            except Exception as exc:                 # noqa: BLE001
                # value via extra={} (the scrubbed path), not the message string,
                # so the pii-in-log rule never trips on the `name` variable — it's
                # a lens key ("math"/"doc"…), never a person's name, but keep the
                # message literal to stay clear of the heuristic either way.
                log.info("[lens] reader unavailable",
                         extra={"reader": name, "err": str(exc)})
                cache[name] = None
        return cache[name]

    # lens key -> (capability key, human pack name) for the honest "install X"
    _LENS_NEEDS = {
        "math": ("math_ocr", "World Sense"),
        "doc": ("doc_read", "World Sense"),
        "depth": ("depth_sense", "World Sense"),
        "find": ("openvocab_find", "Clear Eyes"),
        "segment": ("scene_segment", "Clear Eyes"),
        "sky": ("sky_sense", "Stargazer"),
        "dream": ("dream_style", "Clear Eyes"),
    }

    def look_lens(self, frame, lens: str, args: Optional[dict] = None) -> dict:
        """Run a deliberate look through ONE named lens. Veil-gated (a veiled
        look is blind). Returns {ok, lens, ...} — on a missing model, ok is
        False with `need` (the pack to install) rather than an error, so the
        lens is always reachable and honestly self-describes what it needs."""
        lens = (lens or "").strip().lower()
        args = args or {}
        if lens not in self._LENS_NEEDS:
            return {"ok": False, "lens": lens, "reason": "unknown-lens"}
        cap, pack = self._LENS_NEEDS[lens]
        if not self.privacy.allow_capture():
            return {"ok": False, "lens": lens, "veiled": True,
                    "note": "a veiled look is blind — turn off Incognito"}

        def _need():
            return {"ok": False, "lens": lens, "need": cap, "pack": pack,
                    "note": f"install the {pack} pack to use this lens"}
        try:
            if lens == "math":
                r = self._extra("math")
                if r is None or not getattr(r, "available", False):
                    return _need()
                tex = r.read_math(frame)
                return {"ok": bool(tex), "lens": "math", "latex": tex}
            if lens == "doc":
                r = self._extra("doc")
                if r is None or not getattr(r, "available", False):
                    return _need()
                d = r.read_doc(frame)
                return {"ok": bool(d.get("text")), "lens": "doc", **d}
            if lens == "depth":
                r = self._extra("depth")
                if r is None or not getattr(r, "available", False):
                    return _need()
                near = r.nearest_relative(frame)
                return {"ok": near is not None, "lens": "depth",
                        "closeness": near}
            if lens == "find":
                r = self._extra("find")
                if r is None or not getattr(r, "available", False):
                    return _need()
                terms = args.get("terms") or []
                hits = r.find(frame, terms)
                return {"ok": bool(hits), "lens": "find",
                        "found": [{"term": t, "confidence": round(c, 3)}
                                  for t, c in (hits or [])]}
            if lens == "segment":
                r = self._extra("segment")
                if r is None or not getattr(r, "available", False):
                    return _need()
                n = r.segment(frame)
                return {"ok": n is not None, "lens": "segment", "regions": n}
            if lens == "sky":
                from ...object_lens.sky_lens import default_sky_lens, say_sky
                sky = default_sky_lens()
                if sky is None:                      # ephemeris not installed
                    return _need()
                lat, lon = args.get("lat"), args.get("lon")
                if lat is None or lon is None:
                    return {"ok": False, "lens": "sky", "need_location": True,
                            "note": "the sky lens needs your latitude/longitude"}
                data = sky.night_sky(float(lat), float(lon),
                                     args.get("when_ts")) or {}
                return {"ok": bool(data), "lens": "sky", "sky": data,
                        "line": say_sky(data)}
            if lens == "dream":
                # default_stylizer is never None — the neural painter when a MODEL
                # is provided (DL_DREAM_MODEL → the dream_style cap), else an
                # always-on painterly wash. So the lens always works; `neural`
                # tells the caller which ran, and dream_style stays honestly
                # dormant until a model is actually wired.
                import os as _os
                from ...dream_mode.dream_style import default_stylizer
                st = default_stylizer(_os.environ.get("DL_DREAM_MODEL") or None)
                out = None
                try:
                    out = st.stylize(frame)
                except Exception:                    # noqa: BLE001
                    out = None
                return {"ok": out is not None, "lens": "dream",
                        "styled": out is not None,
                        "neural": bool(getattr(st, "ready", False))}
        except Exception as exc:                     # noqa: BLE001 — a lens never crashes a look
            log.warning("[lens] %s failed: %s", lens, exc)
            return {"ok": False, "lens": lens, "reason": "error"}
        return {"ok": False, "lens": lens, "reason": "unknown-lens"}

    # -- automatic lens selection (the glance arbiter) ---------------------

    def glance(self, frame, dwell_ms: float = 0.0) -> dict:
        """Decide the lens FOR the wearer from what's in view — the "you never
        pick a mode" path. Reads cheap on-device signals (PerceptionRouter),
        classifies the scene, lets the lenses bid (GlanceArbiter), and returns:

          {"kind": "fire", "lens", "action", "card", "scene"}  a lens won → its card
          {"kind": "offer", "scene", "card"}                   ambiguous → chooser
          {"kind": "object"}                                   let the object path run
          {"kind": "veiled"}                                   incognito

        Kind "object" (the arbiter fired Juno, produced nothing, or abstained)
        hands back to the caller's normal object-recognition floor, so that path
        keeps all its behaviour and never runs twice. Never raises."""
        if not self.privacy.allow_capture():
            return {"kind": "veiled"}
        if self.glance_arbiter is None or self.perception is None:
            return {"kind": "object"}          # arbiter absent → object floor
        from ...orchestrator.glance import GlanceContext, classify_coarse
        try:
            signals = self.perception.perceive(frame).as_signals()
        except Exception as exc:               # noqa: BLE001
            if self.health is not None:
                self.health.record_failure("vision", exc)
            signals = {}
        reading = classify_coarse(signals, user_language="en")
        ctx = GlanceContext(dwell_ms=float(dwell_ms or 0.0), veiled=False)
        try:
            decision = self.glance_arbiter.arbitrate(reading, ctx)
        except Exception as exc:               # noqa: BLE001
            log.warning("[glance] arbitrate failed: %s", exc)
            return {"kind": "object"}
        if decision.kind == "offer":
            return {"kind": "offer", "scene": reading.scene, "card": decision.card}
        if decision.kind == "fire" and decision.winner is not None:
            action = decision.winner.action
            if action == "juno":               # object → the normal floor owns it
                return {"kind": "object"}
            card = self._run_glance_lens(action, frame, decision.winner.args or {})
            if not card:
                return {"kind": "object"}       # lens found nothing → object floor
            return {"kind": "fire", "lens": decision.winner.lens,
                    "action": action, "card": card, "scene": reading.scene}
        return {"kind": "object"}

    def _run_glance_lens(self, action: str, frame, args: dict):
        """Run the lens the arbiter chose and return a card dict, or None to fall
        back to the object floor. A lens that self-describes a MISSING PACK
        ({need:...}) is returned AS-IS (not None), so the auto-fire path surfaces
        "install the pack" honestly — exactly as the manual chooser does — instead
        of silently dropping to object-naming (audit 2026-07-23)."""
        try:
            if action == "read":
                return self._glance_lens_result(self.look_lens(frame, "doc"))
            if action == "math":
                return self._glance_lens_result(self.look_lens(frame, "math"))
            if action == "translate":
                panel = self.look(frame, facet="ai")
                return panel.to_hud_card() if panel is not None else None
            if action == "taste":
                from ...hud import cards
                res = self.taste(frame)
                # cards.taste renders the ranking — NOT a nonexistent
                # TasteRanking.to_hud_card, which silently returned None and
                # dropped every shelf/menu to object-naming (audit 2026-07-23).
                # An unavailable/empty ranking hands back to the object floor
                # rather than drawing a hollow "nothing to compare" card.
                if getattr(res, "unavailable", False) or not getattr(res, "items", None):
                    return None
                return cards.taste(res, unavailable=False)
        except Exception as exc:               # noqa: BLE001 — a lens never crashes a look
            log.warning("[glance] lens %s failed: %s", action, exc)
        return None

    @staticmethod
    def _glance_lens_result(r):
        """A look_lens result → a glance card: the real card when the look
        succeeded, the honest {need:...}/{need_location:...} self-description when
        a pack is missing (so auto-fire says "install the pack"), else None → the
        object floor (a genuine "nothing in view", never a swallowed missing-pack)."""
        if isinstance(r, dict) and (r.get("ok") or r.get("need") or r.get("need_location")):
            return r
        return None

    def choose_glance(self, action: str, frame, args: dict, scene: str = "") -> dict:
        """The wearer tapped a chooser option: teach the arbiter this pick for
        this scene, then run the chosen lens. Returns the lens card (or an
        {ok:False} lens dict). Mirrors orchestrator.choose_glance's learning."""
        if scene and action and self.glance_arbiter is not None:
            lens_key = {"read": "read", "math": "math", "translate": "rosetta",
                        "taste": "taste", "juno": "juno"}.get(action, action)
            try:
                self.glance_arbiter.reinforce(scene, lens_key)
            except Exception:                  # noqa: BLE001
                pass
        if action == "juno":
            panel = self.look(frame)
            return panel.to_hud_card() if panel is not None else {"ok": False}
        card = self._run_glance_lens(action, frame, args or {})
        return card if card else {"ok": False, "action": action}


def build_world_lens(brain, isolate: str = "untrusted") -> WorldLensHost:
    return WorldLensHost(brain, isolate=isolate)
