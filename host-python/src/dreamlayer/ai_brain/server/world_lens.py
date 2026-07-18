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
        # host-state the plugin context reads; kept intentionally minimal.
        self.ring = None
        self.mesh = None
        self.perception = None
        self.glance_arbiter = None
        self.plugin_events = None
        self.db = None                      # per-plugin settings stay in-memory
        self._router = _BrainVisionRouter(brain)
        self._shop_providers: list = []

        from ...object_lens import ObjectLens, AIProvider, DietaryProfile
        from ...object_lens.recognizer import ObjectRecognizer
        from ...object_lens.vision_recognizer import VisionSightingRecognizer
        recognizer = ObjectRecognizer(
            classify_fn=VisionSightingRecognizer(self._describe))
        self.object_lens = ObjectLens(recognizer=recognizer, privacy=self.privacy)
        self.object_lens.registry.register(AIProvider(self._router))

        from ...orchestrator.taste import TasteLens
        self.dietary = DietaryProfile()
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

    def look(self, frame, facet: Optional[str] = None):
        """Recognise the object in a photo and build its panel (or None)."""
        facets = {facet} if facet else None
        return self.object_lens.look(frame, facets=facets)

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
        return self.object_lens.registry.build_panel(sighting, facets=facets)

    def taste(self, frame, budget: Optional[float] = None):
        """Read a shelf/menu and rank it against the wearer's rules."""
        if not self.privacy.allow_capture():
            return None
        return self.taste_lens.look(frame, budget=budget)


def build_world_lens(brain, isolate: str = "untrusted") -> WorldLensHost:
    return WorldLensHost(brain, isolate=isolate)
