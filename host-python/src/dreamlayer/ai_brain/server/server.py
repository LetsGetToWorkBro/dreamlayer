"""ai_brain/server/server.py — the Brain server (runs on your Mac mini).

Serves the control panel and the API the phone and the panel both call:

    GET  /                          control panel
    GET  /dreamlayer/config         config (token-safe) + index stats
    POST /dreamlayer/config         update model / connections
    POST /dreamlayer/folders        {action: add|remove, path}  → reindex
    POST /dreamlayer/upload?folder=&name=   drag-drop a file in → reindex
    POST /dreamlayer/brain/ask      {query} → Answer (logged to history)
    POST /dreamlayer/rc/compose     {prompt} → verified figment ("Ask Juno")
    POST /dreamlayer/rc/feed        {text} → stream text into the live lens slot
    POST /dreamlayer/rc/emit        {tag, text} → lens emit → Brain → slot (ask)
    POST /dreamlayer/brain/explain  {label, image?, want?} → Answer
    GET  /dreamlayer/history        recent questions

All /dreamlayer/* calls require the pairing token (when one is set); the
panel page is injected with the token only when opened from localhost.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import threading
import time

from ..schema import Answer
from .store import BrainConfig, QueryHistory, ActivityLog
from .index import FileIndex
from .backends import OllamaBackend, make_synthesizer, vision_answer, probe_ollama
from .macos_sources import collect_documents
from .panel import render_panel

TOKEN_HEADER = "X-DreamLayer-Token"

# Billing-tier seam (no paywall). Extra capabilities each plan grants ON TOP OF
# the always-free base set in Brain.plugin_capabilities(). `free` adds nothing —
# everything works locally & open. A future hosted plan (managed AI, sync,
# relay) would list its capabilities here; the base set is never taken away.
PLAN_CAPS: dict[str, frozenset] = {
    "free": frozenset(),
    # The hosted tier (docs/CLOUD.md). Union-only: these are ADDED on top of
    # the always-free base set — a plan can never remove a capability.
    #   cloud_ai     managed AI, no key to wire (api.dreamlayer.app proxy)
    #   cloud_sync   E2E-encrypted cross-device sync + off-site backup
    #   cloud_relay  hosted mesh relay (GhostMode/Beacon beyond BLE range)
    "cloud": frozenset({"cloud_ai", "cloud_sync", "cloud_relay"}),
}

# What each cloud capability means, for the panel's Plan section.
PLAN_CAP_INFO: dict[str, str] = {
    "cloud_ai": "Managed AI — answers with no key to wire, billed by us",
    "cloud_sync": "Encrypted sync — your memory follows you across devices",
    "cloud_relay": "Private relay — GhostMode and the Beacon work beyond Bluetooth range",
}


def lan_ip() -> str:
    """This machine's LAN address — the one the phone can actually reach.

    Uses a UDP socket to discover the outbound interface without sending
    anything. Falls back to loopback if there's no network.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _spoken_duration(secs: float) -> str:
    """'5 minutes', '1 minute 30 seconds' — how Juno says a length back."""
    secs = int(round(secs))
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    parts = []
    if h:
        parts.append(f"{h} hour" + ("s" if h != 1 else ""))
    if m:
        parts.append(f"{m} minute" + ("s" if m != 1 else ""))
    if s:
        parts.append(f"{s} second" + ("s" if s != 1 else ""))
    return " ".join(parts) or "0 seconds"


def _hour_label(ts: float) -> str:
    """'2 PM' for an hour block in the rewind timeline."""
    lt = time.localtime(ts)
    h = lt.tm_hour
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


class Brain:
    """The Brain's live state: config + index + history, rebuilt on change."""

    def __init__(self, cfg_dir: Path | str, sources_fn=None, messages_fn=None,
                 calendar_reader_fn=None, calendar_list_fn=None):
        self.cfg_dir = Path(cfg_dir)
        self.config = BrainConfig.load(self.cfg_dir)
        self.history = QueryHistory(self.cfg_dir)
        self.activity = ActivityLog(self.cfg_dir)
        self.index = FileIndex(self.config)
        # macOS message/mail documents (folded in when email is enabled)
        self._sources_fn = sources_fn or collect_documents
        # the live feed the glasses read hands-free (the Mac is the bridge)
        from .macos_sources import (recent_messages, read_calendar_events,
                                     list_calendars, read_contacts, read_reminders,
                                     list_reminder_lists)
        self._messages_fn = messages_fn or recent_messages
        # macOS Calendar.app → agenda sync (both are injectable seams for tests)
        self._calendar_reader = calendar_reader_fn or read_calendar_events
        self._calendar_lister = calendar_list_fn or list_calendars
        # macOS Contacts + Reminders readers (injectable seams for tests)
        self._contacts_reader = read_contacts
        self._reminders_reader = read_reminders
        self._reminder_lister = list_reminder_lists
        self._sig = None
        self._last_phone_ts = 0.0        # last authed request from off-box (the phone)
        self._started_ts = time.time()
        # per-seam failure ledger — the panel's answer to "why is it mush?"
        from ...orchestrator.health import HealthLedger
        self.health = HealthLedger()
        self.last_index_ts = 0.0
        self.email_docs = 0
        self.last_brief = None
        self.last_long_brief = None
        self._brief_ran_day = None
        self._brief_stop = None
        self._cal_stop = None
        self.last_calendar_sync = 0.0
        self.last_contacts_sync = 0.0
        self.last_reminders_sync = 0.0
        # Saga: the ecosystem progression the phone shows — ranks, level, and
        # achievements. Brain-hosted so the phone (and hub) can read/record it.
        from ...saga import SagaProfile
        self.saga = SagaProfile(self.cfg_dir)
        # Plugin marketplace (docs/MARKETPLACE.md): the Brain hosts the plugins
        # the user installs. Every package is validated (integrity + capability
        # scan + smoke test) before it's written; the panel and phone manage them.
        from ...plugins import PluginStore
        self.plugins = PluginStore(self.cfg_dir / "plugins",
                                   host_capabilities=self.plugin_capabilities())
        # Juno's profile of you (name, interests, people, remembered prefs).
        # Built on the glasses hub from the conversation stream, then *pushed*
        # here so the phone can read it — the hub->Brain bridge. Just a mirror;
        # the Brain never writes it, only stores what the hub sends.
        self.profile: dict = self._load_profile()
        # Social memory mirror (hub -> Brain, like the profile): everyone you've
        # met with their relation, notes, and debts, so the phone's People
        # screen can read and edit them. The hub owns the truth; this is a
        # mirror the phone drives.
        self.social_people: list = self._load_people()
        # Waypath: where you left your things. "I left my bike at the north rack"
        # → a spoken anchor; "where's my bike?" reads it back. Persisted so the
        # phone's typed-voice loop (stash then locate) is self-contained here,
        # independent of the glasses hub (which keeps its own IMU anchors).
        from ...orchestrator.waypath import WaypathLens
        self.waypath = WaypathLens()
        self._load_waypath()
        # Reality Compiler v2 (the Rehearsal paradigm, docs/RC_V2_*.md): the
        # phone performs a behavior as beats; the Brain infers → verifies →
        # signs → hot-swaps a Figment. The vault (signed, on-device storage)
        # lives beside the Brain's config so kept figments persist. No bridge
        # is wired here yet, so deploys run in dry-run (they record the exact
        # BLE envelopes) until the glasses transport is attached.
        from ...reality_compiler.v2.compiler import RealityCompilerV2
        self.rc = RealityCompilerV2(vault_dir=self.cfg_dir / "vault")
        self._rc_pending: dict = {}          # figment_id → Figment awaiting keep
        self._rc_active: Optional[str] = None  # the figment on stage right now
        self._watch_stop: threading.Event | None = None
        # retention: drop logs older than the configured window on boot
        if self.config.retention_days:
            self.history.prune(self.config.retention_days)
            self.activity.prune(self.config.retention_days)
        self._wire_model()
        self.reindex()

    # -- plugin marketplace --------------------------------------------------

    def plugin_capabilities(self) -> frozenset:
        """What this Brain can safely grant a plugin. The always-available
        extension points, plus midi (the Mac has it); mesh + shop (the
        GhostMode-broadcast and TasteLens-connector seams — a plugin that emits
        to a mesh/shop that isn't wired just no-ops, same as perception/glance
        pre-hardware); vision when a vision model or cloud is available; network
        unless incognito. fs/subprocess are withheld — a plugin needing them is
        rejected."""
        caps = {"object_lens", "glance", "perception", "cards", "ring", "midi",
                "mesh", "shop"}
        if self.config.model == "ollama" or self.config.cloud_ready():
            caps.add("vision")
        if not self.config.lan_only:
            caps.add("network")
        # Billing-tier seam (no paywall today): the free plan grants everything
        # above; a future hosted plan would add its capabilities here. Kept as a
        # union so `free` never removes a capability — see BrainConfig.plan.
        caps |= PLAN_CAPS.get(getattr(self.config, "plan", "free"), frozenset())
        return frozenset(caps)

    def plan_summary(self) -> dict:
        """The Plan section's data: current plan, what Cloud adds (with human
        meaning), and which of those entitlements are active now. Union-only —
        the free plan's capabilities are never listed as removable."""
        plan = getattr(self.config, "plan", "free")
        cloud_caps = sorted(PLAN_CAPS.get("cloud", frozenset()))
        return {
            "plan": plan if plan in PLAN_CAPS else "free",
            "cloud_caps": [{"key": c, "info": PLAN_CAP_INFO.get(c, c),
                            "active": plan == "cloud"} for c in cloud_caps],
        }

    def plugins_state(self) -> dict:
        from ...plugins import PluginPackage
        installed = []
        for name in self.plugins.installed():
            try:
                pkg = PluginPackage.load(self.plugins.dir / name)
                m = pkg.manifest
                installed.append({"name": m.name, "version": m.version,
                                  "author": m.author, "official": m.official,
                                  "api": m.api, "requires": list(m.requires),
                                  "description": m.description, "long": list(m.long),
                                  "forwho": m.forwho, "screenshot": m.screenshot})
            except Exception:
                installed.append({"name": name, "version": "", "author": "", "requires": []})
        return {"installed": installed,
                "capabilities": sorted(self.plugin_capabilities())}

    def install_plugin(self, body: dict) -> dict:
        """Install a plugin, validated. Accepts a sideloaded package
        ({manifest, source}) or a registry name (needs a wired registry)."""
        from ...plugins import PluginPackage, PluginManifest, ValidationReport
        if body.get("source") and body.get("manifest"):
            pkg = PluginPackage(manifest=PluginManifest.from_dict(body["manifest"]),
                                source=str(body["source"]))
            report = self.plugins.install_package(pkg)
            label = pkg.manifest.name
        elif body.get("name"):
            report = self.plugins.install(str(body["name"]))
            label = str(body["name"])
        else:
            report = ValidationReport()
            report.add_error("provide a package (manifest+source) or a registry name")
            label = "?"
        if report.ok:
            self.activity.add("plugin", f"Installed plugin {label}")
        return {"ok": report.ok, "errors": report.errors,
                "warnings": report.warnings, "state": self.plugins_state()}

    def remove_plugin(self, name: str) -> dict:
        ok = self.plugins.remove(name)
        if ok:
            self.activity.add("plugin", f"Removed plugin {name}")
        return {"ok": ok, "state": self.plugins_state()}

    # -- Reality Compiler v2 (Rehearsal) -------------------------------------

    def rc_rehearse(self, name: str, beats: list) -> dict:
        """Replay a performance (the phone's beats) into a rehearsal session,
        infer → verify → run-through, and mirror the result back: the live
        score, and either a budget-proved figment + folded preview (ok) or a
        teach card worded in beats (not ok). A rehearsal figment is held
        pending until the phone keeps it."""
        from ...reality_compiler.v2 import present
        session = self.rc.rehearse(name or "Rehearsed behavior")
        for b in beats or []:
            kind = (b or {}).get("kind")
            if kind == "tap":
                session.tap()
            elif kind == "double_tap":
                session.double_tap()
            elif kind == "long_press":
                session.long_press()
            elif kind == "dwell":
                session.dwell(float(b.get("seconds") or 0.0))
            elif kind == "say":
                text = str(b.get("text") or "")
                session.say(text)
                self.rc.mine_utterance(text)   # grammar mining (5.3), local-only
            # unknown kinds are ignored — the grammar can't be smuggled past
        try:
            result = session.finish()
        except Exception:
            # last-resort net: a performance must never crash the Brain
            from ...reality_compiler.v2 import present
            return {"ok": False,
                    "score": present.score_from_beats(session.beats),
                    "teach": {"title": "CAN'T DO THAT",
                              "lines": ["couldn't stage that performance"],
                              "beat": None,
                              "suggestion": "try fewer, simpler beats"}}
        resp: dict = {"ok": result.ok,
                      "score": present.score_from_beats(result.beats)}
        if result.report is not None:
            resp["report"] = {"scenes": result.report.scene_count,
                              "display_hz": result.report.worst_display_hz,
                              "emit_per_sec": result.report.worst_emit_per_sec}
        if result.ok:
            fig = result.figment
            self._rc_pending[fig.id] = fig
            resp["figment_id"] = fig.id
            resp["brief"] = present.figment_brief(fig)
            resp["preview"] = present.playback_rows(result.playback)
        elif result.teach is not None:
            t = result.teach
            resp["teach"] = {"title": t.title, "lines": t.hud_lines(),
                             "beat": t.beat, "suggestion": t.suggestion}
        return resp

    def rc_keep(self, figment_id: str) -> dict:
        """Sign + vault a rehearsed figment (must have been rehearsed ok this
        session). Returns the new Repertoire card."""
        from ...reality_compiler.v2 import present
        fig = self._rc_pending.get(figment_id)
        if fig is None:
            return {"ok": False, "error": "no rehearsed figment with that id"}
        entry = self.rc.keep(fig)
        self._rc_pending.pop(figment_id, None)
        self.activity.add("rc", f"Kept figment {fig.name!r}")
        return {"ok": True,
                "entry": present.repertoire_entry(entry, self._rc_active)}

    def rc_repertoire(self) -> dict:
        # ranked by fit-for-now (5.3): the machine you finish, at the hour you
        # usually run it, floats to the top; plus the one-line "start the usual?"
        from ...reality_compiler.v2 import present
        items = [present.repertoire_entry(e, self._rc_active)
                 for e in self.rc.ranked_repertoire()]
        return {"items": items, "active": self._rc_active,
                "suggestion": self.rc.suggest()}

    def rc_suggest(self) -> dict:
        """The right machine for right now, or nothing when none is a confident
        fit — the Juno's "Gym? Start the usual circuit?" """
        return {"suggestion": self.rc.suggest()}

    def rc_grammar_candidates(self) -> dict:
        """The words people keep trying to say that the rehearsal grammar can't
        hear yet — the compiler's roadmap, measured locally (5.3)."""
        return {"candidates": self.rc.grammar_candidates()}

    def rc_deploy(self, figment_id: str) -> dict:
        """Hot-swap a kept figment onto the stage. On success it's the one on
        stage (the phone shows it armed)."""
        record = self.rc.deploy(figment_id)
        if record.success:
            self._rc_active = figment_id
            self.activity.add("rc", f"Deployed figment {figment_id}")
        return {"ok": record.success, "message": record.message,
                "active": self._rc_active, **self.rc_repertoire()}

    def rc_revoke(self, figment_id: str) -> dict:
        record = self.rc.revoke(figment_id)
        if self._rc_active == figment_id:
            self._rc_active = None
        # a revoke is the wearer rejecting the machine — the strongest negative
        # signal the ranker gets, so it stops offering what you keep dropping.
        self.rc.record_outcome(figment_id, "banish")
        self.activity.add("rc", f"Revoked figment {figment_id}")
        return {"ok": record.success, "message": record.message,
                "active": self._rc_active, **self.rc_repertoire()}

    def rc_complete(self, figment_id: str) -> dict:
        """A deployed figment reached its terminal scene — the positive signal
        the ranker learns "you finish this one" from (5.3)."""
        self.rc.record_outcome(figment_id, "complete")
        if self._rc_active == figment_id:
            self._rc_active = None
        return {"ok": True, **self.rc_repertoire()}

    def rc_compose(self, prompt: str) -> dict:
        """Ask Juno: turn a plain-English description of a lens into a figment.

        The builder's "Ask Juno" box (INNOVATION_SESSION Category 1). We run the
        offline intent parser — no cloud, no model needed — lift it to a figment
        and budget-verify it *here* before it ever reaches the editor. The result
        is returned but NOT deployed: it lands in the builder for the author to
        preview, paint on, and tweak, then Deploy re-checks the proof again.
        """
        text = (prompt or "").strip()
        if not text:
            return {"ok": False, "unmatched": True,
                    "error": "Tell Juno what the lens should do."}
        try:
            result = self.rc.compile_text(text)
        except ValueError:
            return {"ok": False, "unmatched": True,
                    "error": "Juno couldn't turn that into a lens yet.",
                    "examples": [
                        "a 5 minute countdown that pulses at the end",
                        "interval timer, 3 minutes work 1 minute rest",
                        "count reps, add one on a nod",
                        "box breathing, 4 seconds each",
                        "teleprompter for my speech notes",
                    ]}
        except Exception as e:                          # pragma: no cover - defensive
            return {"ok": False, "error": f"compose failed: {e}"}
        fig = result.figment
        return {
            "ok": result.report.ok,
            "figment": fig.to_dict(),
            "describe": fig.describe(),
            "scenes": len(fig.scenes),
            "violations": [str(v) for v in result.report.violations],
        }

    def rc_import(self, data: dict) -> dict:
        """Import a figment authored elsewhere — the no-code browser builder's
        "Deploy to my Brain" (INNOVATION_SESSION Category 1). The proof is
        re-checked *here*: the Brain budget-verifies and re-signs it before it
        can run — it never trusts the author. On success it's on stage."""
        import uuid
        from ...reality_compiler.v2.figment import Figment
        from ...reality_compiler.v2 import safety
        try:
            fig = Figment.from_dict(data or {})
        except Exception as e:
            return {"ok": False, "error": f"not a figment: {e}"}
        # the browser builder ships id="" (it doesn't own identity); mint a fresh
        # one so two imported lenses can't collide/overwrite in the vault.
        if not fig.id:
            fig.id = uuid.uuid4().hex[:12]
        card = safety.safety_card(fig)
        if not card["ok"]:
            return {"ok": False, "error": "fails the sandbox", "safety": card}
        try:
            self.rc.keep(fig)               # re-verifies budgets + signs
        except Exception as e:
            return {"ok": False, "error": f"rejected: {e}", "safety": card}
        record = self.rc.deploy(fig.id)
        if record.success:
            self._rc_active = fig.id
            self.activity.add("rc", f"Imported lens {fig.name!r} from the builder")
        return {"ok": record.success, "id": fig.id, "safety": card,
                **self.rc_repertoire()}

    def rc_refine_suggestion(self, figment_id: str) -> dict:
        """If you keep quitting this figment at the same scene, the compiler's
        proposed edit — "you end this around 20:00 of 25:00, shorten it?" (5.3).
        Returns {proposal: null} when there's nothing to tune."""
        p = self.rc.refine_proposal(figment_id)
        return {"proposal": p.as_dict() if p is not None else None}

    def rc_refine_apply(self, figment_id: str) -> dict:
        """One tap: materialise the proposed refinement as a budget-verified,
        re-signed variant (lineage kept). Returns the new entry + repertoire."""
        from ...reality_compiler.v2 import present
        p = self.rc.refine_proposal(figment_id)
        if p is None:
            return {"ok": False, "error": "nothing to refine"}
        entry = self.rc.apply_refinement(p)
        self.activity.add("rc", f"Refined {figment_id} → {entry.figment.id}")
        return {"ok": True, "entry": present.repertoire_entry(entry, self._rc_active),
                **self.rc_repertoire()}

    def rc_event(self, name: str) -> dict:
        """Forward a physical-world signal to the figment on stage (the $6
        ESP32 kit path, INNOVATION 1.6): a reed switch / thermistor / button
        out in the world POSTs here, and the named event ("ble:3", "mail")
        reaches the running figment's scene grammar. Refused when no figment
        is armed — an event with nothing listening is a no-op, not a wake."""
        name = str(name or "")[:32]
        if not name:
            return {"ok": False, "error": "empty event name"}
        if self._rc_active is None:
            return {"ok": False, "error": "no figment on stage to receive the event"}
        record = self.rc.deployer.push_event(name)
        self.activity.add("rc", f"Event {name!r} → figment {self._rc_active}")
        return {"ok": record.success, "name": name, "active": self._rc_active,
                "mode": record.mode}

    def rc_feed(self, text: str, source: str = "") -> dict:
        """Stream a line of host text into the running lens's ``{slot}`` — the
        wire the world-facing lenses ride: a live translation, a camera label,
        a resurfaced Vault memory. It's the read-only twin of ``rc_event``
        (which advances scenes); feed only fills the text slot. The slot is one
        short line on the round glass, so it's clamped to MAX_TEXT_LEN here.
        Refused when no lens is on stage — there's nothing to show it on."""
        from ...reality_compiler.v2.figment import MAX_TEXT_LEN
        text = str(text or "")[:MAX_TEXT_LEN]
        if self._rc_active is None:
            return {"ok": False, "error": "no lens on stage to feed"}
        record = self.rc.deployer.push_text(self._rc_active, text)
        if source:
            self.activity.add("rc", f"{str(source)[:24]} → lens")
        return {"ok": record.success, "text": text,
                "active": self._rc_active, "mode": record.mode}

    def rc_emit(self, tag: str, text: str = "") -> dict:
        """Close the loop glass → Brain → glass. A running lens emits a tag and
        the Brain acts on it, streaming the result back into the lens's slot:

          ``ask``  → run your Brain over the spoken question, push the answer
                     (from your own files/memory, or the cloud if you allow it)
          other    → carry the tag's text payload straight to the slot (a camera
                     label from ``look``, a translation the hub already made)

        This is what makes the showcase lenses real on a paired Brain: the phone
        relays a figment's emit here, and the answer lands back on the glass.
        Refused when no lens is on stage."""
        from ...reality_compiler.v2.figment import MAX_EMIT_TAG_LEN
        tag = str(tag or "")[:MAX_EMIT_TAG_LEN]
        if not tag:
            return {"ok": False, "error": "empty emit tag"}
        if self._rc_active is None:
            return {"ok": False, "error": "no lens on stage"}
        if tag == "ask":
            ans = self.ask(text or "")
            reply = (ans.text if ans and not ans.is_empty() else "") or "no answer yet"
            tier = ans.tier if ans else ""
            out = self.rc_feed(reply, source="ask")
            self.activity.add("rc", "Lens asked → Brain answered")
            return {**out, "tag": tag, "answer": reply, "tier": tier}
        if text:
            return {**self.rc_feed(text, source=f"emit:{tag}"), "tag": tag}
        # a bare emit with no payload and no built-in reaction: acknowledged,
        # left for a plugin/hub to interpret, never an error
        return {"ok": True, "tag": tag, "active": self._rc_active, "noted": True}

    # -- native behaviors Juno builds (timers, intervals, clock) -----------

    def rc_native(self, intent: str, args: dict) -> dict:
        """Turn a parsed voice intent (timer / interval / clock) into a
        budget-verified Figment and put it on the stage immediately — no
        rehearsal, no Repertoire clutter. These are ephemeral: signed and
        deployed, but their vault entries are pruned so they don't pile up in
        the kept list. Returns a spoken confirmation + the figment id."""
        from ...reality_compiler.v2 import native

        a = args or {}
        if intent == "timer":
            secs = float(a.get("seconds") or 0)
            if secs <= 0:
                return {"ok": False, "say": "How long a timer?"}
            fig = native.timer_figment(secs, label=a.get("label") or "Timer")
            say = f"Timer set for {_spoken_duration(secs)}."
        elif intent == "interval":
            work = float(a.get("work") or 0)
            rest = float(a.get("rest") or 0)
            rounds = a.get("rounds")
            if work <= 0 or rest <= 0:
                return {"ok": False, "say": "How long on and off?"}
            fig = native.interval_figment(work, rest, rounds=rounds,
                                          label=a.get("label") or "Intervals")
            r = f" for {int(rounds)} rounds" if rounds else " until you hold to stop"
            say = (f"Intervals: {_spoken_duration(work)} on, "
                   f"{_spoken_duration(rest)} off{r}.")
        elif intent == "clock":
            if a.get("mode") == "time":
                now = time.localtime()
                return {"ok": True, "intent": "clock",
                        "say": time.strftime("It's %-I:%M %p.", now)}
            fig = native.clock_figment()
            say = "Clock's up. Hold to dismiss it."
        else:
            return {"ok": False, "say": ""}

        # deploy it straight to the stage, then drop it from the kept list
        self.rc.keep(fig)
        record = self.rc.deploy(fig.id)
        self._rc_active = fig.id if record.success else self._rc_active
        if intent == "clock" and record.success:
            # seed the slot so the clock isn't blank; the stage refreshes it
            # each minute (device tick / host push) once it's on real glasses
            self.rc.deployer.push_text(fig.id, time.strftime("%-I:%M %p"))
        try:
            self.rc.vault.revoke(fig.id)   # ephemeral: keep the Repertoire clean
        except Exception:
            pass
        self.activity.add("rc", f"Juno started {fig.name!r}")
        return {"ok": record.success, "intent": intent, "say": say,
                "figment_id": fig.id, "name": fig.name}

    def rc_native_cancel(self) -> dict:
        """Clear whatever native behavior is on the stage."""
        if self._rc_active:
            self.rc.revoke(self._rc_active)
            self._rc_active = None
        return {"ok": True, "say": "Stopped.", "intent": "timer_cancel"}

    def reindex(self) -> dict:
        self.index.reindex()
        self.email_docs = 0
        if self.config.email_enabled:
            try:
                docs = self._sources_fn(self.config)
                self.email_docs = len(docs)
                self.index.add_documents(docs)
            except Exception:
                pass
        self._sig = self._signature()
        self.last_index_ts = time.time()
        return self.index.stats()

    # -- auto-reindex when watched folders change ------------------------

    def _signature(self):
        sig = []
        for folder in self.config.folders:
            base = Path(folder).expanduser()
            if base.is_dir():
                try:
                    for f in base.rglob("*"):
                        if f.is_file():
                            sig.append((str(f), f.stat().st_mtime_ns))
                except OSError:
                    pass
        return tuple(sorted(sig))

    def poll(self) -> bool:
        """Reindex if the watched folders changed since last scan."""
        if self._signature() != self._sig:
            self.reindex()
            return True
        return False

    def start_watching(self, interval: float = 3.0) -> None:
        if self._watch_stop is not None:
            return
        self._watch_stop = threading.Event()

        def loop():
            while not self._watch_stop.wait(interval):
                try:
                    self.poll()
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    def stop_watching(self) -> None:
        if self._watch_stop is not None:
            self._watch_stop.set()
            self._watch_stop = None

    def _wire_model(self) -> None:
        """Point the index/vision at the configured backend."""
        if self.config.model == "ollama":
            self._backend = OllamaBackend(self.config)
            self.index.synthesizer = make_synthesizer(self._backend)
            self.index.embedder = (self._backend.embed
                                   if self.config.semantic_search else None)
        else:
            self._backend = None
            self.index.synthesizer = None
            self.index.embedder = None

    def save(self) -> None:
        self.config.save(self.cfg_dir)

    def apply_config(self, updates: dict) -> None:
        for k in ("model", "ollama_url", "ollama_chat_model",
                  "ollama_vision_model", "ollama_embed_model",
                  "email_enabled", "summarize_emails", "cloud_enabled",
                  "network_mode", "cloud_provider", "cloud_base_url",
                  "cloud_api_key", "cloud_model", "plan",
                  "semantic_search", "index_extensions", "max_file_kb",
                  "exclude_globs", "quiet_hours", "retention_days", "brief_hour",
                  "calendar_sync", "calendar_names", "calendar_days",
                  "contacts_sync", "reminders_sync", "reminder_lists"):
            if k in updates:
                setattr(self.config, k, updates[k])
        self._wire_model()
        self.save()
        # turning a sync on (or changing its filter) → pull immediately
        try:
            if updates.get("calendar_sync") or ("calendar_names" in updates and self.config.calendar_sync):
                self.sync_calendar()
            if updates.get("contacts_sync"):
                self.sync_contacts()
            if updates.get("reminders_sync") or ("reminder_lists" in updates and self.config.reminders_sync):
                self.sync_reminders()
        except Exception:
            pass
        if updates.get("cloud_enabled"):
            self.saga_record("cloud")
        if updates.get("network_mode") == "lan_only":
            self.saga_record("incognito")

    def incognito_now(self) -> bool:
        """Effective privacy shield: manual LAN-only OR a quiet-hours window."""
        from .store import in_quiet_hours
        return self.config.lan_only or in_quiet_hours(self.config.quiet_hours)

    def missing_folders(self) -> list:
        return [f for f in self.config.folders
                if not Path(f).expanduser().is_dir()]

    def ask(self, query: str) -> Optional[Answer]:
        ans = self.index.ask(query)
        if ans is None and self.config.cloud_ready() and not self.incognito_now():
            ans = self._ask_cloud(query)
        if ans is not None:
            self.history.add(query, ans.text, ans.tier, ans.sources)
            self.saga_record("recall")
        return ans

    def _ask_cloud(self, query: str) -> Optional[Answer]:
        """The one place data leaves the device — logged every single time."""
        from .backends import cloud_chat
        try:
            text = cloud_chat(self.config, query)
            self.health.record_ok("cloud")
        except Exception as exc:
            self.health.record_failure("cloud", exc)   # degrade, but on the record
            text = ""
        if not text:
            return None
        self.config.cloud_calls += 1
        self.save()
        self.activity.add("cloud-egress", f"Asked the cloud: {query[:70]}")
        return Answer(text=text, tier="cloud", sources=["cloud"], confidence=0.6)

    def explain(self, label: str, image_b64, want: str) -> Optional[Answer]:
        return vision_answer(self._backend, label, image_b64, want)

    def summarize(self, text: str, max_chars: int = 220) -> str:
        """One-glance summary of a long email. Uses the local model when there
        is one; otherwise clips to the first sentence — never blocks the feed."""
        text = (text or "").strip()
        if len(text) <= max_chars:
            return text
        if self._backend is not None:
            try:
                s = self._backend.chat(
                    "Summarize this email in one short sentence a person can "
                    "read at a glance. Just the sentence:\n\n" + text[:2000])
                if s and s.strip():
                    return s.strip()
            except Exception:
                pass
        head = text.split(". ")[0].strip()
        return head if 0 < len(head) <= max_chars else text[:max_chars].rstrip() + "…"

    def maybe_run_brief(self, now: float | None = None) -> bool:
        """If it's the configured brief hour and today's brief hasn't run yet,
        generate it and stash it for delivery. Returns True when it ran."""
        hour = self.config.brief_hour
        if hour is None or hour < 0:
            return False
        lt = time.localtime(now if now is not None else time.time())
        day = (lt.tm_year, lt.tm_yday)
        if lt.tm_hour != hour or getattr(self, "_brief_ran_day", None) == day:
            return False
        self._brief_ran_day = day
        b = self.brief()
        self.last_brief = {"text": b["text"], "bullets": b["bullets"],
                           "ts": time.time()}
        self.activity.add("brief", "Morning brief ready")
        return True

    def start_brief_scheduler(self, interval: float = 60.0) -> None:
        if getattr(self, "_brief_stop", None) is not None:
            return
        self._brief_stop = threading.Event()

        def loop():
            while not self._brief_stop.wait(interval):
                try:
                    self.maybe_run_brief()
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    def export_backup(self) -> dict:
        """A full, restorable snapshot of the Brain — config (incl. secrets),
        query history, activity, and agenda. Handed out only to the local
        panel, so it never crosses the network."""
        self.saga_record("backup")
        return {
            "version": _version(),
            "config": asdict(self.config),
            "history": self.history.recent(2000),
            "activity": self.activity.recent(2000),
            "agenda": self.calendar(200),
        }

    def import_backup(self, data: dict) -> None:
        from .store import field_list
        cfg = data.get("config") or {}
        known = {f.name for f in field_list(BrainConfig)}
        for k, v in cfg.items():
            if k in known:
                setattr(self.config, k, v)
        self.save()
        if isinstance(data.get("history"), list):
            self.history.restore(data["history"])
        if isinstance(data.get("activity"), list):
            self.activity.restore(data["activity"])
        if isinstance(data.get("agenda"), list):
            (self.cfg_dir / "agenda.json").write_text(json.dumps(data["agenda"]))
        self._wire_model()
        self.reindex()

    def calendar(self, limit: int = 10) -> list:
        """Upcoming events for the glasses + the brief. Reads
        <cfg>/agenda.json (a list of {title, ts, place}); events pulled from
        macOS Calendar carry source:"calendar". [] when empty."""
        events = []
        p = self.cfg_dir / "agenda.json"
        try:
            if p.exists():
                data = json.loads(p.read_text())
                for e in (data if isinstance(data, list) else []):
                    if e.get("title"):
                        events.append({"title": e["title"],
                                       "ts": float(e.get("ts", 0) or 0),
                                       "place": e.get("place", ""),
                                       "source": e.get("source", "manual"),
                                       "calendar": e.get("calendar", "")})
        except Exception:
            pass
        now = time.time()
        upcoming = [e for e in events if e["ts"] >= now - 3600]   # today onward
        upcoming.sort(key=lambda e: e["ts"])
        return upcoming[:limit]

    def add_event(self, title: str, ts: float = 0.0, place: str = "") -> list:
        """Append one event to <cfg>/agenda.json and return the upcoming list."""
        title = (title or "").strip()
        p = self.cfg_dir / "agenda.json"
        try:
            cur = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            cur = []
        if not isinstance(cur, list):
            cur = []
        if title:
            cur.append({"title": title, "ts": float(ts or 0), "place": place or ""})
            p.write_text(json.dumps(cur))
            self.activity.add("calendar", f"Added event {title}")
        return self.calendar(200)

    def remove_event(self, title: str, ts: float | None = None) -> list:
        """Drop the first agenda event matching title (and ts, if given)."""
        title = (title or "").strip()
        p = self.cfg_dir / "agenda.json"
        try:
            cur = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            cur = []
        kept, removed = [], False
        for e in (cur if isinstance(cur, list) else []):
            same = (e.get("title") == title and
                    (ts is None or abs(float(e.get("ts", 0) or 0) - float(ts)) < 1))
            if same and not removed:
                removed = True
                continue
            kept.append(e)
        if removed:
            p.write_text(json.dumps(kept))
            self.activity.add("calendar", f"Removed event {title}")
        return self.calendar(200)

    # -- macOS Calendar.app sync (read-only) -----------------------------

    def list_calendars(self) -> list[str]:
        """The calendars available to sync from (for the panel's picker)."""
        try:
            return self._calendar_lister()
        except Exception:
            return []

    def sync_calendar(self) -> dict:
        """Pull upcoming Calendar.app events into agenda.json, replacing any
        previously-synced events while keeping the ones you added by hand.
        Synced events carry `source: "calendar"`; manual ones don't."""
        try:
            events = self._calendar_reader(self.config)
        except Exception:
            events = []
        p = self.cfg_dir / "agenda.json"
        try:
            cur = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            cur = []
        if not isinstance(cur, list):
            cur = []
        # keep everything you added by hand; drop the last sync's events
        manual = [e for e in cur if e.get("source") != "calendar"]
        synced = [{"title": e["title"], "ts": float(e.get("ts", 0) or 0),
                   "place": e.get("place", ""), "calendar": e.get("calendar", ""),
                   "source": "calendar"} for e in events if e.get("title")]
        p.write_text(json.dumps(manual + synced))
        self.last_calendar_sync = time.time()
        self.activity.add("calendar", f"Synced {len(synced)} event(s) from Calendar")
        self.saga_record("calendar")
        return {"items": self.calendar(200), "synced": len(synced)}

    def maybe_sync_calendar(self) -> bool:
        """Run the macOS syncs whose toggles are on. Called by the scheduler."""
        ran = False
        if self.config.calendar_sync:
            self.sync_calendar(); ran = True
        if self.config.contacts_sync:
            self.sync_contacts(); ran = True
        if self.config.reminders_sync:
            self.sync_reminders(); ran = True
        return ran

    def start_calendar_sync(self, interval: int = 900):
        """Background loop: re-pull calendar / contacts / reminders every
        `interval` seconds while their toggles are on. Idempotent."""
        import threading
        if self._cal_stop is not None:
            return
        stop = threading.Event()
        self._cal_stop = stop

        def loop():
            first = True
            while True:
                if stop.wait(2 if first else interval):   # a quick first pull
                    break
                first = False
                try:
                    self.maybe_sync_calendar()
                except Exception:
                    pass

        threading.Thread(target=loop, daemon=True).start()

    # -- people you've been introduced to (the dossier registry) ---------

    def people(self) -> list:
        """Everyone you've introduced to the Brain, newest first. Backed by
        <cfg>/people.json: a list of {name, note, tags, ts}. [] when empty."""
        p = self.cfg_dir / "people.json"
        try:
            data = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            data = []
        out = []
        for e in (data if isinstance(data, list) else []):
            if e.get("name"):
                out.append({"name": e["name"], "note": e.get("note", ""),
                            "tags": e.get("tags", []), "ts": float(e.get("ts", 0) or 0),
                            "source": e.get("source", "manual")})
        out.sort(key=lambda e: -e["ts"])
        return out

    def add_person(self, name: str, note: str = "", tags=None) -> list:
        """Introduce (or update) a person. Re-adding a name updates the note."""
        name = (name or "").strip()
        if not name:
            return self.people()
        p = self.cfg_dir / "people.json"
        try:
            cur = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            cur = []
        if not isinstance(cur, list):
            cur = []
        tags = [t for t in (tags or []) if t]
        cur = [e for e in cur if e.get("name") != name]     # replace existing
        cur.append({"name": name, "note": note or "", "tags": tags,
                    "ts": time.time(), "source": "manual"})
        p.write_text(json.dumps(cur))
        self.activity.add("people", f"Introduced {name}")
        return self.people()

    def remove_person(self, name: str) -> list:
        name = (name or "").strip()
        p = self.cfg_dir / "people.json"
        try:
            cur = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            cur = []
        kept = [e for e in (cur if isinstance(cur, list) else []) if e.get("name") != name]
        if len(kept) != len(cur if isinstance(cur, list) else []):
            p.write_text(json.dumps(kept))
            self.activity.add("people", f"Removed {name}")
        return self.people()

    def sync_contacts(self) -> dict:
        """Pull macOS Contacts into the People registry. Keeps the people you
        added by hand; replaces the previous contacts pull. Synced entries carry
        source:"contacts"."""
        try:
            contacts = self._contacts_reader(self.config)
        except Exception:
            contacts = []
        p = self.cfg_dir / "people.json"
        try:
            cur = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            cur = []
        if not isinstance(cur, list):
            cur = []
        manual = [e for e in cur if e.get("source") != "contacts"]
        manual_names = {e.get("name") for e in manual}
        synced = []
        for c in contacts:
            if not c.get("name") or c["name"] in manual_names:
                continue                                   # never shadow a manual entry
            note = "  •  ".join([x for x in (c.get("company"), c.get("role")) if x])
            synced.append({"name": c["name"], "note": note, "tags": [],
                           "ts": time.time(), "source": "contacts",
                           "email": c.get("email", "")})
        p.write_text(json.dumps(manual + synced))
        self.last_contacts_sync = time.time()
        self.activity.add("people", f"Synced {len(synced)} contact(s)")
        self.saga_record("contacts")
        return {"items": self.people(), "synced": len(synced)}

    # -- reminders: open to-dos from macOS Reminders --------------------

    def reminders(self) -> list:
        """Open reminders, dated first. Backed by <cfg>/reminders.json."""
        p = self.cfg_dir / "reminders.json"
        try:
            data = json.loads(p.read_text()) if p.exists() else []
        except Exception:
            data = []
        out = [e for e in (data if isinstance(data, list) else []) if e.get("title")]
        out.sort(key=lambda e: (float(e.get("ts", 0) or 0) == 0, float(e.get("ts", 0) or 0)))
        return out

    def sync_reminders(self) -> dict:
        """Pull open macOS reminders into <cfg>/reminders.json (full replace)."""
        try:
            items = self._reminders_reader(self.config)
        except Exception:
            items = []
        clean = [{"title": r["title"], "ts": float(r.get("ts", 0) or 0),
                  "list": r.get("list", "")} for r in items if r.get("title")]
        (self.cfg_dir / "reminders.json").write_text(json.dumps(clean))
        self.last_reminders_sync = time.time()
        self.activity.add("reminders", f"Synced {len(clean)} reminder(s)")
        self.saga_record("reminders")
        return {"items": self.reminders(), "synced": len(clean)}

    def list_reminder_lists(self) -> list:
        try:
            return self._reminder_lister()
        except Exception:
            return []

    def saga_record(self, event: str, count: int | None = None) -> list:
        """Advance the Saga profile for an ecosystem event and unlock any badges
        (feature use + the level milestones it crosses). Returns newly-unlocked
        names; logs them to the activity feed."""
        fresh = (self.saga.record(event, count=count) if count is not None
                 else self.saga.record(event))
        fresh += self.saga.note_level(self.saga.snapshot()["level"])
        return fresh

    def _load_profile(self) -> dict:
        p = self.cfg_dir / "profile.json"
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                return {}
        return {}

    # -- social people mirror (hub -> Brain -> phone People screen) ----------

    def _load_people(self) -> list:
        p = self.cfg_dir / "social_people.json"
        if p.exists():
            try:
                return json.loads(p.read_text()) or []
            except Exception:
                return []
        return []

    def _save_people(self) -> None:
        try:
            (self.cfg_dir / "social_people.json").write_text(
                json.dumps(self.social_people))
        except Exception:
            pass

    def social_people_state(self) -> dict:
        return {"people": self.social_people}

    def receive_people(self, payload: dict) -> dict:
        """Store the snapshot the hub pushed (merging so phone-side edits made
        while the hub was offline aren't clobbered by name that isn't present)."""
        incoming = (payload or {}).get("people") or []
        self.social_people = list(incoming)
        self._save_people()
        return {"ok": True, "count": len(self.social_people)}

    def edit_person(self, body: dict) -> dict:
        """Apply a phone edit to a person in the mirror: add a note, set the
        relationship, remove a note, or settle debts. Returns the updated
        person, or {ok:False} if the id isn't in the mirror."""
        b = body or {}
        cid = str(b.get("contact_id", ""))
        action = str(b.get("action", ""))
        person = next((p for p in self.social_people
                       if p.get("contact_id") == cid), None)
        if person is None:
            return {"ok": False, "error": "no such person"}
        if action == "note":
            note = str(b.get("value", "")).strip()
            if note:
                person.setdefault("notes", []).append(note)
        elif action == "remove_note":
            note = str(b.get("value", ""))
            person["notes"] = [n for n in person.get("notes", []) if n != note]
        elif action == "relation":
            person["relation"] = str(b.get("value", "")).strip()
        elif action == "settle":
            person["debts"] = []
        else:
            return {"ok": False, "error": "unknown action"}
        self._save_people()
        return {"ok": True, "person": person}

    def _find_person(self, name: str):
        nl = (name or "").strip().lower()
        if not nl:
            return None
        exact = next((p for p in self.social_people
                      if p.get("name", "").lower() == nl), None)
        if exact:
            return exact
        # unique first-name match
        starts = [p for p in self.social_people
                  if p.get("name", "").lower().split()[:1] == [nl]]
        return starts[0] if len(starts) == 1 else None

    def voice_social(self, intent: str, args: dict) -> dict:
        """Full-parity social voice from the phone's typed box: note / meet /
        debt / settle, applied to the people mirror the People screen reads.
        The hub owns the truth on-glass; this keeps the phone consistent when
        you type instead of speaking to the glasses."""
        a = args or {}
        who = str(a.get("who") or "").strip()

        if intent == "meet_person":
            if not who:
                return {"intent": intent, "ok": False, "say": "Who is this?"}
            person = self._find_person(who)
            if person is None:
                safe = "".join(c for c in who.lower() if c.isalnum()) or "person"
                person = {"contact_id": f"phone_{safe}", "name": who,
                          "relation": "", "company": "", "role": "",
                          "last_met": "", "last_seen": "", "notes": [],
                          "debts": [], "topics": []}
                self.social_people.append(person)
            if a.get("relation"):
                person["relation"] = str(a["relation"]).strip()
            if a.get("note"):
                person.setdefault("notes", []).append(str(a["note"]).strip())
            self._save_people()
            return {"intent": intent, "ok": True, "who": who,
                    "say": f"Good to meet {who}."}

        if not who:
            return {"intent": intent, "ok": False,
                    "say": "Who do you mean? Say their name."}
        person = self._find_person(who)
        if person is None:
            return {"intent": intent, "ok": False,
                    "say": f"I don't know who {who} is yet."}
        name = person["name"]
        if intent == "note_person":
            note = str(a.get("note") or "").strip()
            if note:
                person.setdefault("notes", []).append(note)
            say = f"Got it — I'll remember that about {name}."
        elif intent == "debt":
            what = str(a.get("what") or "").strip()
            if a.get("dir") == "they_owe":
                person.setdefault("debts", []).append(f"owes you {what}")
                say = f"Noted — {name} owes you {what}."
            else:
                person.setdefault("debts", []).append(f"you owe {what}")
                say = f"Noted — you owe {name} {what}."
        elif intent == "debt_settle":
            person["debts"] = []
            say = f"Squared up with {name}."
        else:
            return {"intent": intent, "ok": False, "say": ""}
        self._save_people()
        return {"intent": intent, "ok": True, "who": name, "say": say}

    # -- waypath: where you left your things ---------------------------------

    def _load_waypath(self) -> None:
        p = self.cfg_dir / "waypath.json"
        if not p.exists():
            return
        try:
            rows = json.loads(p.read_text()) or []
        except Exception:
            return
        for a in rows if isinstance(rows, list) else []:
            try:                       # one bad row must not drop the rest
                self.waypath.remember(
                    a.get("subject", ""), bearing_deg=a.get("bearing_deg"),
                    distance_m=a.get("distance_m"), place=a.get("place", ""),
                    ts=a.get("ts"))
            except Exception:
                continue

    def _save_waypath(self) -> None:
        try:
            anchors = [{"subject": a.subject, "bearing_deg": a.bearing_deg,
                        "distance_m": a.distance_m, "place": a.place, "ts": a.ts}
                       for a in self.waypath.anchors()]
            # atomic: the server is threaded, and a torn write would silently
            # lose every anchor on the next load
            tmp = self.cfg_dir / "waypath.json.tmp"
            tmp.write_text(json.dumps(anchors))
            os.replace(tmp, self.cfg_dir / "waypath.json")
        except Exception:
            pass

    def purge_memories(self) -> dict:
        """The phone's "Erase all memories" honored where the memories actually
        live: every Waypath anchor is dropped and the store rewritten, so a
        later refresh can't quietly resurrect what the user erased. People and
        reminders are mirrors of their own surfaces (People tab, Reminders) and
        are not deleted here — erasing memories is not deleting your contacts."""
        n = self.waypath.forget_all()
        self._save_waypath()
        self.activity.add("privacy", f"Erased kept memories ({n} anchor(s))")
        return {"ok": True, "purged": n}

    def waypath_stash(self, subject: str, place: str) -> dict:
        subject = (subject or "").strip()
        place = (place or "").strip()
        if not subject:
            return {"intent": "stash", "ok": False, "say": "Left what where?"}
        self.waypath.remember_place(subject, place)
        self._save_waypath()
        say = (f"Got it — your {subject} is at {place}." if place
               else f"Got it — I'll remember your {subject}.")
        return {"intent": "stash", "ok": True, "say": say,
                "subject": subject, "place": place}

    def waypath_locate(self, subject: str) -> dict:
        subject = (subject or "").strip()
        if not subject:
            return {"intent": "locate", "ok": False, "say": "Find what?"}
        cue = self.waypath.locate(subject)
        if not cue.found:
            return {"intent": "locate", "ok": False, "found": False,
                    "say": f"I don't have a spot saved for your {subject} yet."}
        return {"intent": "locate", "ok": True, "found": True,
                "subject": cue.subject, "place": cue.place, "detail": cue.text,
                "say": f"Your {cue.subject} — {cue.text}."}

    def missed(self, since: float = 0.0) -> dict:
        """"What did I miss?" — the incoming texts and emails since you last
        looked, spoken as a short line. Uses the same message source as the
        brief; `since` defaults to the last few hours."""
        import time as _t
        if since <= 0:
            since = _t.time() - 6 * 3600
        try:
            msgs = self._messages_fn(self.config, 40) if self.config.email_enabled else []
        except Exception:
            msgs = []
        incoming = [m for m in msgs if not m.get("from_me") and m.get("ts", 0) > since]
        texts = [m for m in incoming if m.get("channel") != "email"]
        emails = [m for m in incoming if m.get("channel") == "email"]
        if not incoming:
            return {"intent": "missed", "ok": True, "texts": 0, "emails": 0,
                    "say": "Nothing while you were away."}
        who = ", ".join(dict.fromkeys(
            (m.get("who") or "").strip() for m in texts if m.get("who")))
        bits = []
        if texts:
            bits.append(f"{len(texts)} text{'s' if len(texts) != 1 else ''}"
                        + (f" from {who[:60]}" if who else ""))
        if emails:
            bits.append(f"{len(emails)} email{'s' if len(emails) != 1 else ''}")
        return {"intent": "missed", "ok": True, "texts": len(texts),
                "emails": len(emails), "say": "You missed " + " and ".join(bits) + "."}

    def voice_reply(self, to: str, text: str) -> dict:
        """A spoken/typed "reply to Priya saying on my way" — stage the reply
        (drafting one with the model if you didn't dictate the words) and hand it
        back for the app to send. Never auto-sends: sending stays a deliberate
        tap in Messages."""
        to = (to or "").strip()
        text = (text or "").strip()
        if not to:
            return {"intent": "reply", "ok": False, "say": "Reply to whom?"}
        if not text:
            sug = self.suggest_replies(f"(reply to {to})", n=1)
            text = sug[0] if sug else ""
        return {"intent": "reply", "ok": True, "to": to, "text": text,
                "say": (f"Reply to {to}: “{text}” — open Messages to send."
                        if text else f"Open Messages to reply to {to}.")}

    def memories(self, limit: int = 40) -> dict:
        """A read of DreamLayer's own kept memory for the phone's Memories tab,
        assembled from what the Brain holds: places you saved (Waypath), people
        you've met and favors owed (Social Lens), and dated reminders. Not raw
        recordings — the moments that matter. Timestamped rows sort newest
        first (an upcoming reminder floats to the very top); people and open
        debts are living memory with no event time, so they carry ts=0 and
        settle at the bottom instead of masquerading as fresh."""
        import time as _t
        from datetime import date
        now = _t.time()
        today = date.fromtimestamp(now)

        def when(ts: float) -> str:
            if not ts:
                return ""
            # calendar days, not 24h buckets — so tomorrow's reminder reads
            # "Tomorrow", not "Yesterday", and a same-day dawn stash stays today
            days = (date.fromtimestamp(ts) - today).days
            clock = _t.strftime("%-I:%M %p", _t.localtime(ts))
            if days == 0:
                return clock
            if days == -1:
                return "Yesterday, " + clock
            if days == 1:
                return "Tomorrow, " + clock
            if -7 < days < 7:
                return _t.strftime("%a, ", _t.localtime(ts)) + clock
            return _t.strftime("%b %-d, ", _t.localtime(ts)) + clock

        rows = []
        # places you saved (Waypath) — real timestamps
        for a in self.waypath.anchors():
            loc = f"at {a.place}" if a.place else "somewhere you saved"
            rows.append(("Place", f"Your {a.subject} — {loc}", a.ts or now, when(a.ts)))
        # people you've met + favors owed (Social Lens) — living memory, undated
        for p in self.social_people:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            detail = ", ".join([x for x in [p.get("relation", "")]
                                + (p.get("notes") or [])[:1] if x])
            rows.append(("Person", name + (f" — {detail}" if detail else ""),
                         0.0, p.get("last_seen", "") or ""))
            for d in (p.get("debts") or []):
                dl = d.strip()
                low = dl.lower()
                if low.startswith("you owe"):
                    s = f"You owe {name} {dl[7:].strip()}"
                elif low.startswith("owes you"):
                    s = f"{name} {dl}"
                else:
                    s = f"{name}: {dl}"
                rows.append(("Promise", s, 0.0, "open"))
        # dated reminders (Promise)
        for r in self.reminders():
            ts = float(r.get("ts", 0) or 0)
            if ts:
                rows.append(("Promise", r["title"], ts, when(ts)))

        rows.sort(key=lambda x: (-x[2], x[1].lower()))
        out = [{"id": f"m{i}", "kind": kind, "summary": summary,
                "createdAt": label, "ts": int(ts * 1000)}
               for i, (kind, summary, ts, label) in enumerate(rows[:limit])]
        return {"memories": out}

    def set_profile(self, data: dict) -> dict:
        """Store the Juno profile the glasses hub just pushed (a mirror, so the
        phone can read it). Keeps only the known shape; persists to profile.json."""
        d = data if isinstance(data, dict) else {}

        def _list(key, limit):
            v = d.get(key)
            return [str(x) for x in v][:limit] if isinstance(v, list) else []

        self.profile = {
            "name": str(d.get("name", "") or ""),
            "interests": _list("interests", 12),
            "people": _list("people", 12),
            "preferences": _list("preferences", 40),
            "observations": int(d.get("observations", 0) or 0),
        }
        try:
            (self.cfg_dir / "profile.json").write_text(json.dumps(self.profile))
        except Exception:
            pass
        return self.profile

    def pull_model(self, name: str) -> dict:
        """One-click Ollama model pull. Re-probes after so status updates."""
        from .backends import pull_model as _pull
        res = _pull(self.config, name)
        if res.get("ok"):
            self.activity.add("model", f"Pulled model {res.get('model', name)}")
            self._wire_model()
            self.saga_record("model")
        return res

    # -- rewind my day: one merged timeline of what happened -------------

    def rewind(self, now: float | None = None) -> dict:
        """Today, grouped into hour blocks: what the Brain did (activity), the
        messages it relayed, and the events on the agenda — one scrubable
        timeline for the phone. Reads only what the Brain already has."""
        now = now if now is not None else time.time()
        lt = time.localtime(now)
        day_start = now - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)
        items = []
        for a in self.activity.recent(200):
            ts = float(a.get("ts", 0) or 0)
            if ts >= day_start:
                items.append({"ts": ts, "kind": a.get("kind", "activity"),
                              "text": a.get("text", "")})
        try:
            msgs = self._messages_fn(self.config, 50) if self.config.email_enabled else []
            for m in msgs:
                ts = float(m.get("ts", 0) or 0)
                if ts >= day_start and not m.get("from_me"):
                    who = m.get("who", "")
                    body = m.get("subject") or m.get("text", "")
                    items.append({"ts": ts, "kind": "message",
                                  "text": f"{who}: {body}".strip(": ")})
        except Exception:
            pass
        for e in self.calendar(50):
            if day_start <= e["ts"] < day_start + 86400:
                items.append({"ts": e["ts"], "kind": "event", "text": e["title"]})
        blocks: dict[int, list] = {}
        for it in items:
            hr = int((it["ts"] - day_start) // 3600)
            blocks.setdefault(hr, []).append(it)
        out = []
        for hr in sorted(blocks):
            evs = sorted(blocks[hr], key=lambda x: x["ts"])
            out.append({"hour": hr, "label": _hour_label(day_start + hr * 3600),
                        "count": len(evs), "items": evs})
        return {"blocks": out, "count": len(items)}

    def suggest_replies(self, text: str, n: int = 3) -> list:
        """A few short, natural replies to an incoming message — pick one by
        tap now, by voice later. Model-generated with a canned fallback."""
        text = (text or "").strip()
        if self._backend is not None and text:
            try:
                raw = self._backend.chat(
                    f"Suggest {n} short, natural one-line replies to this "
                    f"message. One per line, no numbering, no quotes:\n\n" + text)
                lines = [ln.strip("-•\" ").strip() for ln in raw.splitlines() if ln.strip()]
                if lines:
                    return lines[:n]
            except Exception:
                pass
        return ["On my way", "Give me a few", "Thanks!"][:n]

    def brief(self, agenda=None, since: float = 0.0, depth: str = "short",
              commitments=None, memories=None) -> dict:
        """A morning brief at one of two depths.

        `depth="short"` (default) is the one-glance version: today's agenda +
        what's new, turned by the model into a warm couple of sentences (or the
        structured points with no model). `depth="long"` walks the whole
        morning in sections — Today, Due, Waiting on you, Messages, Yesterday —
        each item spelled out, and the model writes a few skimmable paragraphs.

        The phone passes what only it holds: `agenda` (calendar/commitment
        lines it already folds), `commitments` (open promises), and `memories`
        (yesterday's kept moments). `since` powers 'what did I miss'.
        """
        long = str(depth).lower() == "long"
        agenda = [a for a in (agenda or []) if a]
        events = []
        for e in self.calendar(8 if long else 5):     # today's events lead the brief
            when = time.strftime("%I:%M %p", time.localtime(e["ts"])).lstrip("0") if e["ts"] else ""
            events.append(e["title"] + (f" at {when}" if when else ""))
        day_end = time.time() + 86400
        due = [r for r in self.reminders() if 0 < r.get("ts", 0) <= day_end]
        due_lines = ["Reminder: " + r["title"] for r in due[:(8 if long else 3)]]
        try:
            msgs = self._messages_fn(self.config, 30 if long else 20) if self.config.email_enabled else []
        except Exception:
            msgs = []
        incoming = [m for m in msgs if not m.get("from_me") and m.get("ts", 0) > since]
        texts = [m for m in incoming if m.get("channel") != "email"]
        emails = [m for m in incoming if m.get("channel") == "email"]
        commitments = [c for c in (commitments or []) if c]
        memories = [m for m in (memories or []) if m]

        # -- the short brief: the original one-glance contract, unchanged ------
        if not long:
            bullets = list(agenda) + events + due_lines
            if texts:
                who = ", ".join(dict.fromkeys(m.get("who", "") for m in texts if m.get("who")))
                bullets.append(f"{len(texts)} new text{'s' if len(texts) != 1 else ''}"
                               + (f" (from {who[:60]})" if who else ""))
            for m in emails[:3]:
                subj = (m.get("subject") or m.get("text", "")[:40]).strip()
                if subj:
                    bullets.append(f"Email: {subj}")
            if not bullets:
                bullets = ["Nothing pressing — a clear morning."]
            text = "  ·  ".join(bullets)
            if self._backend is not None:
                try:
                    s = self._backend.chat(
                        "Write a warm, two-sentence morning brief from these points. "
                        "Be concrete, natural, and brief — no preamble:\n\n"
                        + "\n".join("- " + b for b in bullets))
                    if s and s.strip():
                        text = s.strip()
                except Exception:
                    pass
            self.saga_record("brief")
            return {"text": text, "bullets": bullets, "depth": "short",
                    "missed": {"texts": len(texts), "emails": len(emails)}}

        # -- the long brief: sectioned, each item spelled out ------------------
        text_lines = []
        for m in texts:
            who = (m.get("who") or "Someone").strip()
            body = (m.get("text") or "").strip().replace("\n", " ")
            text_lines.append(f"{who}: {_clip_brief(body, 80)}" if body else who)
        email_lines = []
        for m in emails:
            subj = (m.get("subject") or m.get("text", "")[:60]).strip().replace("\n", " ")
            who = (m.get("who") or "").strip()
            if subj:
                email_lines.append(f"{who} — {subj}" if who else subj)

        sections = []
        if agenda or events:
            sections.append({"title": "Today", "items": list(agenda) + events})
        if due_lines:
            sections.append({"title": "Due", "items": [d.replace("Reminder: ", "") for d in due_lines]})
        if commitments:
            sections.append({"title": "Waiting on you", "items": commitments})
        if text_lines or email_lines:
            items = list(text_lines)
            if email_lines:
                items += ["✉ " + e for e in email_lines[:6]]
            sections.append({"title": "Messages", "items": items})
        if memories:
            sections.append({"title": "Yesterday", "items": memories})
        if not sections:
            sections = [{"title": "Today", "items": ["Nothing pressing — a clear morning."]}]

        bullets = [f"{s['title']}: " + "; ".join(s["items"]) for s in sections]
        text = "\n\n".join(f"{s['title']}\n" + "\n".join("• " + i for i in s["items"])
                           for s in sections)
        if self._backend is not None:
            try:
                prompt = (
                    "Write a thorough but skimmable morning brief in a few short "
                    "paragraphs. Lead with what's on today, then what's due and who's "
                    "waiting on the reader, then notable messages, then a line on "
                    "yesterday. Warm, concrete, second person, no preamble or headers:\n\n"
                    + "\n".join(f"[{s['title']}]\n" + "\n".join("- " + i for i in s["items"])
                                for s in sections))
                s = self._backend.chat(prompt)
                if s and s.strip():
                    text = s.strip()
            except Exception:
                pass
        self.saga_record("brief")
        return {"text": text, "bullets": bullets, "sections": sections,
                "depth": "long",
                "missed": {"texts": len(texts), "emails": len(emails)}}


def _memory_db_path(brain: Brain) -> Path:
    """Where the orchestrator's memory SQLite lives — the same file the CLI's
    `dreamlayer memories` resolves ($DREAMLAYER_DB, else <cfg_dir>/dreamlayer.db)."""
    import os
    raw = os.environ.get("DREAMLAYER_DB") or str(Path(brain.cfg_dir) / "dreamlayer.db")
    return Path(raw).expanduser()


def _memory_file(brain: Brain) -> dict:
    """Panel readout for 'your memory is a file' — no CLI needed."""
    from ...memory.datasette_app import MemoryExplorer
    p = _memory_db_path(brain)
    return {
        "path": str(p),
        "exists": p.exists(),
        "bytes": p.stat().st_size if p.exists() else 0,
        "datasette": MemoryExplorer.available,
        "browse_cmd": MemoryExplorer(str(p)).command(port=8001),
    }


def _memory_browse(brain: Brain) -> dict:
    """Launch the read-only Datasette browser over the memory file (local-only).
    Returns a URL when datasette is installed, else the command to run."""
    from ...memory.datasette_app import MemoryExplorer
    info = _memory_file(brain)
    if not info["exists"]:
        return {"available": False, "error": "no memory file yet", "command": info["browse_cmd"]}
    ex = MemoryExplorer(info["path"])
    if not MemoryExplorer.available:
        return {"available": False, "command": ex.command(port=8001)}
    import shlex
    import subprocess
    try:
        meta = ex.write_metadata()
        subprocess.Popen(shlex.split(ex.command(port=8001, metadata_path=meta)))
        return {"available": True, "url": "http://127.0.0.1:8001"}
    except Exception as exc:
        return {"available": False, "error": str(exc), "command": ex.command(port=8001)}


def _memory_export(brain: Brain, dest: str) -> dict:
    """Copy the memory file somewhere (local-only). It's the user's data."""
    import shutil
    info = _memory_file(brain)
    if not info["exists"]:
        return {"ok": False, "error": "no memory file to export"}
    if not (dest or "").strip():
        return {"ok": False, "error": "no destination given"}
    d = Path(dest).expanduser()
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(info["path"], d)
    return {"ok": True, "dest": str(d), "bytes": d.stat().st_size}


def _cloud_view_payload(brain: Brain) -> dict:
    """What DreamLayer Cloud can see — the opaque byte-shapes only, never content
    (INNOVATION_SESSION Category 6 / B16). The trust centerpiece: render the
    nothing. The server stores ciphertext, room ids, and counts; this reports
    exactly those, and names — in the client's own words — what it can never see.
    Honest today: with no cloud configured, the answer is 'the server holds
    nothing', which is the point."""
    try:
        caps = set(brain.plugin_capabilities())
    except Exception:
        caps = set()
    enabled = bool({"cloud_sync", "cloud_relay", "cloud_ai"} & caps)
    return {
        "enabled": enabled,
        # {bytes, last_backup_ts} once a ciphertext backup exists; None ⇒ nothing
        # stored. The server can never open it — the key is your passphrase.
        "vault": None,
        # rooms the device participates in: an opaque id + a member count, never
        # who. The relay routes; it does not read.
        "relay": {"rooms": []},
        "listings": 0,
        "cannot_see": [
            "your memories — the SQLite file never leaves the device unencrypted",
            "who you are — bonds are pairwise keys; the relay learns only a room id",
            "what a figment means — a dozen integers cross the wire, nothing more",
        ],
    }


def _builder_dir() -> "Optional[Path]":
    """Where the browser lens-builder assets live. Prefers a copy bundled into
    the package (an installed/notarized app), falls back to the repo's landing/
    (running from source, as here). None if neither is present."""
    here = Path(__file__).resolve()
    for cand in (here.parent / "assets" / "build",
                 here.parents[5] / "landing"):
        if (cand / "lens-builder.html").exists():
            return cand
    return None


def _builder_asset(name: str) -> "Optional[str]":
    d = _builder_dir()
    if d is None or "/" in name or ".." in name:
        return None
    fp = d / "assets" / "lens" / name
    return fp.read_text(encoding="utf-8") if fp.is_file() else None


_JUNO_CTYPES = {
    "js": "application/javascript; charset=utf-8",
    "mp4": "video/mp4", "webm": "video/webm",
    "webp": "image/webp", "png": "image/png",
}


def _juno_asset(name: str) -> "Optional[tuple[bytes, str]]":
    """Read a Juno sprite asset (script, packed clip, or poster) from the
    landing bundle. Binary-safe. None for anything unknown or path-escaping."""
    d = _builder_dir()
    if d is None or "/" in name or ".." in name:
        return None
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    ctype = _JUNO_CTYPES.get(ext)
    if ctype is None:
        return None
    fp = d / "assets" / "juno" / name
    return (fp.read_bytes(), ctype) if fp.is_file() else None


def _builder_page(token: str) -> "Optional[str]":
    """The builder HTML, rewritten to load figment.js from the Brain and told
    it's same-origin (so it hides the URL/token inputs and deploys relatively).
    The token rides in only for a localhost request — exactly like the panel."""
    d = _builder_dir()
    if d is None:
        return None
    html = (d / "lens-builder.html").read_text(encoding="utf-8")
    html = html.replace("./assets/lens/figment.js", "/dreamlayer/build/figment.js")
    html = html.replace("./assets/lens/qr.js", "/dreamlayer/build/qr.js")
    html = html.replace("./assets/lens/icons.js", "/dreamlayer/build/icons.js")
    inject = ("<script>window.__DL_BUILD__="
              + json.dumps({"token": token, "sameOrigin": True})
              + ";</script>")
    return html.replace("</head>", inject + "</head>", 1)


def _brain_view_payload(brain: Brain) -> dict:
    """The Brain as a cartridge (INNOVATION_SESSION 3.1): the live tier ladder —
    on-device → Mac mini → cloud — each with the round-trip latency the router
    actually measured (health ledger), plus which model is loaded and the cloud/
    incognito switches. Makes the router's judgment visible and swappable."""
    seams = {}
    try:
        seams = brain.health.snapshot()
    except Exception:
        seams = {}
    cloud_on = bool(brain.config.cloud_enabled) and not brain.config.lan_only
    incognito = brain.incognito_now()

    def tier(seam_key, name, note, enabled):
        s = seams.get(f"brain:{seam_key}", {})
        ok, fail = int(s.get("successes", 0)), int(s.get("failures", 0))
        total = ok + fail
        return {
            "id": seam_key, "name": name, "note": note, "enabled": enabled,
            "latency_ms": s.get("latency_ms"),          # None until it has answered
            "answered": ok, "failed": fail,
            "reliability": round(ok / total, 2) if total else None,
            "seen": total > 0,
        }

    mac_on = not brain.config.lan_only            # local-only ("phone is the brain") drops the remote tier
    tiers = [
        tier("device", "On-device", "small, instant, always yours", True),
        tier("mac_mini", "Mac mini", "bigger local model, over your own files", mac_on),
        tier("cloud", "Cloud",
             "the hardest, non-personal asks" if cloud_on else "off — nothing leaves the device",
             cloud_on and not incognito),
    ]
    # the tier that would answer now = the highest-preference enabled one
    active = next((t["id"] for t in tiers if t["enabled"]), "device")
    return {
        "model": brain.config.model,               # the loaded cartridge
        "cloud_provider": getattr(brain.config, "cloud_provider", "") or "",
        "cloud": cloud_on,
        "incognito": incognito,
        "active_tier": active,
        "tiers": tiers,
    }


def _capability_payload(brain: Brain) -> dict:
    """Live optional-capability report for the panel (dreamlayer/capabilities.py)
    with the panel's own persisted off-switches applied. Env DL_DISABLE_* still
    works as the ops-level override; `config.disabled_caps` is the same switch
    made durable, since the bundled .app has no env of its own to edit."""
    import os
    import sys
    from ...capabilities import PROFILES, packs_report, report, summary
    env = dict(os.environ)
    for key in brain.config.disabled_caps:
        env.setdefault("DL_DISABLE_" + key.upper(), "1")
    packs = packs_report(env=env)
    for p in packs:                             # overlay live install progress
        job = _PACK_JOBS.get(p["key"])
        if job:
            p["install"] = dict(job)
    return {"items": report(env=env), "summary": summary(env=env),
            "profiles": {k: list(v) for k, v in PROFILES.items()},
            "disabled": list(brain.config.disabled_caps),
            "packs": packs,
            # py2app sets sys.frozen — the panel words install hints accordingly
            # (a sealed, signed bundle can't pip-install into itself)
            "frozen": bool(getattr(sys, "frozen", False))}


# --- pack installer ----------------------------------------------------------
# One-click upgrade for SOURCE installs: pip-installs a curated pack's pinned
# requirements into this very environment, in a background thread, one pack at
# a time. The frozen .app refuses (a sealed signed bundle can't modify itself)
# and the panel words that honestly. `_PACK_RUNNER` is injectable for tests.

_PACK_JOBS: dict = {}            # pack key -> {"state","detail","ts"}
_PACK_LOCK = threading.Lock()


def _run_pip(reqs: list) -> tuple:
    """Default pack runner: pip install into this interpreter's environment.
    Returns (ok, last_output_lines)."""
    import subprocess
    import sys
    cmd = [sys.executable, "-m", "pip", "install", *reqs]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-6:]
        return proc.returncode == 0, "\n".join(tail)
    except Exception as exc:                     # pip missing, timeout, ...
        return False, str(exc)


_PACK_RUNNER = _run_pip


def _install_pack(brain: Brain, pack_key: str) -> dict:
    """Validate and launch a pack install. Returns the job dict (or an error)."""
    import sys
    from ...capabilities import pack_requirements
    if getattr(sys, "frozen", False):
        return {"error": "this bundled app can't install into itself — "
                         "packs install on a source-run Brain"}
    reqs = pack_requirements(pack_key)
    if not reqs:
        return {"error": f"unknown pack: {pack_key}"}
    with _PACK_LOCK:
        if any(j.get("state") == "installing" for j in _PACK_JOBS.values()):
            return {"error": "another pack is already installing"}
        job = {"state": "installing", "detail": f"{len(reqs)} packages", "ts": time.time()}
        _PACK_JOBS[pack_key] = job

    def work():
        ok, detail = _PACK_RUNNER(reqs)
        job["state"] = "done" if ok else "failed"
        job["detail"] = ("installed — restart the Brain to light it up"
                         if ok else detail[-400:])
        job["ts"] = time.time()
        brain.activity.add("config", f"Pack {pack_key} install "
                           + ("finished" if ok else "failed"))

    threading.Thread(target=work, daemon=True).start()
    brain.activity.add("config", f"Pack {pack_key} install started")
    return job


def make_brain_server(brain: Brain, host: str = "127.0.0.1",
                      port: int = 7777) -> ThreadingHTTPServer:
    token = brain.config.token

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        # -- helpers ----------------------------------------------------
        def _json(self, code, obj):
            # Deliberately NO CORS headers. The Brain is a local API that can hold
            # secrets (backup, token, memory) and its default token is empty, so
            # cross-origin *reads* must stay blocked — a drive-by page a wearer
            # visits connects from loopback and would otherwise pass the local
            # gates. One-click "Deploy to my Brain" works because the builder is
            # served *same-origin* at /dreamlayer/build; the phone uses native
            # networking (not subject to CORS). A cross-origin web tool cannot
            # reach this API, by design.
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            tok = brain.config.token        # read live so token rotation applies
            ok = not tok or self.headers.get(TOKEN_HEADER) == tok
            # a successful token-carrying request from off-box is the phone
            if ok and tok and not self._from_localhost():
                brain._last_phone_ts = time.time()
            return ok

        def _from_localhost(self) -> bool:
            return self.client_address[0] in ("127.0.0.1", "::1")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                return json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                return {}

        def _raw(self) -> bytes:
            n = int(self.headers.get("Content-Length", 0) or 0)
            return self.rfile.read(n) if n else b""

        # -- routing ----------------------------------------------------
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)
            if path == "/":
                html = render_panel(brain.config.token if self._from_localhost() else "")
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/dreamlayer/build":
                # serve the no-code lens builder same-origin (INNOVATION 5,
                # Category 1) so "Deploy to my Brain" needs no CORS and no
                # pasted token. Same posture as the panel: the token is injected
                # only for a localhost request.
                # NB: no CORS header here on purpose. This HTML carries the
                # injected Brain token (localhost only), so it must stay
                # same-origin — a page on another site must not be able to
                # fetch() and read it. It's loaded by navigation, never fetch.
                html = _builder_page(brain.config.token if self._from_localhost() else "")
                if html is None:
                    self._json(404, {"error": "builder assets not found"}); return
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path in ("/dreamlayer/build/figment.js", "/dreamlayer/build/qr.js",
                        "/dreamlayer/build/icons.js"):
                # same-origin assets for the served page — no CORS needed
                js = _builder_asset(path.rsplit("/", 1)[1])
                if js is None:
                    self._json(404, {"error": "not found"}); return
                body = js.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/dreamlayer/build/juno/"):
                # Juno's sprite kit for the panel: her UMD compositor script and
                # the packed colour+matte clips it composites (mp4/webm) plus the
                # still poster (webp). Same-origin, static, no token — the page
                # just needs to paint her.
                name = path[len("/dreamlayer/build/juno/"):]
                data = _juno_asset(name)
                if data is None:
                    self._json(404, {"error": "not found"}); return
                body, ctype = data
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/panel-assets/"):
                # bundled panel imagery (cinematic stills, HUD thumbnails) —
                # static, read-only, no token needed so the page can paint.
                name = path[len("/panel-assets/"):]
                if "/" in name or ".." in name:
                    self._json(404, {"error": "not found"}); return
                fp = Path(__file__).resolve().parent / "assets" / name
                if not fp.is_file():
                    self._json(404, {"error": "not found"}); return
                ctype = {"webp": "image/webp", "png": "image/png",
                         "jpg": "image/jpeg", "svg": "image/svg+xml",
                         "woff2": "font/woff2"}.get(
                             name.rsplit(".", 1)[-1].lower(),
                             "application/octet-stream")
                data = fp.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(data)
                return
            if not self._authed():
                self._json(401, {"error": "unauthorised"}); return
            if path == "/dreamlayer/config":
                self._json(200, {"config": brain.config.public(),
                                 "stats": brain.index.stats(),
                                 "plan": brain.plan_summary()})
            elif path == "/dreamlayer/brain/tiers":
                # the Brain ceremony (3.1): tier ladder + measured latency
                self._json(200, _brain_view_payload(brain))
            elif path == "/dreamlayer/status":
                ago = None
                if brain._last_phone_ts:
                    ago = max(0, int(time.time() - brain._last_phone_ts))
                idx_ago = (int(time.time() - brain.last_index_ts)
                           if brain.last_index_ts else None)
                self._json(200, {
                    "brain": True,
                    "model": brain.config.model,
                    "cloud": bool(brain.config.cloud_enabled) and not brain.config.lan_only,
                    "cloud_ready": brain.config.cloud_ready(),
                    "cloud_calls": brain.config.cloud_calls,
                    "incognito": brain.incognito_now(),
                    "quiet": brain.incognito_now() and not brain.config.lan_only,
                    "phone_ago": ago,
                    "index_ago": idx_ago,
                    "missing": brain.missing_folders(),
                    "email_docs": brain.email_docs,
                    "stats": brain.index.stats(),
                })
            elif path == "/dreamlayer/token":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                self._json(200, {"token": brain.config.token})
            elif path == "/dreamlayer/backup":
                if not self._from_localhost():
                    self._json(403, {"error": "backup is local-only"}); return
                self._json(200, brain.export_backup())
            elif path == "/dreamlayer/health":
                import shutil
                try:
                    du = sum(f.stat().st_size for f in brain.cfg_dir.rglob("*") if f.is_file())
                except OSError:
                    du = 0
                oms = None
                if brain.config.model == "ollama":
                    t0 = time.time()
                    if probe_ollama(brain.config, timeout=3).get("reachable"):
                        oms = int((time.time() - t0) * 1000)
                self._json(200, {"version": _version(), "disk_kb": du // 1000,
                                 "ollama_ms": oms,
                                 "uptime_s": int(time.time() - brain._started_ts),
                                 "seams": brain.health.snapshot()})
            elif path == "/dreamlayer/capabilities":
                self._json(200, _capability_payload(brain))
            elif path == "/dreamlayer/cloud":
                self._json(200, _cloud_view_payload(brain))
            elif path == "/dreamlayer/memory/file":
                self._json(200, _memory_file(brain))
            elif path == "/dreamlayer/history":
                self._json(200, {"items": _activity_feed(brain, 40)})
            elif path == "/dreamlayer/calendar":
                self._json(200, {"items": brain.calendar()})
            elif path == "/dreamlayer/people":
                self._json(200, {"items": brain.people()})
            elif path == "/dreamlayer/calendars":
                # available macOS calendars + current sync settings (for the picker)
                self._json(200, {"items": brain.list_calendars(),
                                 "sync": brain.config.calendar_sync,
                                 "selected": brain.config.calendar_names,
                                 "last_sync": brain.last_calendar_sync})
            elif path == "/dreamlayer/contacts":
                self._json(200, {"sync": brain.config.contacts_sync,
                                 "last_sync": brain.last_contacts_sync,
                                 "count": len([p for p in brain.people()
                                               if p.get("source") == "contacts"])})
            elif path == "/dreamlayer/reminders":
                self._json(200, {"items": brain.reminders(),
                                 "lists": brain.list_reminder_lists(),
                                 "sync": brain.config.reminders_sync,
                                 "selected": brain.config.reminder_lists,
                                 "last_sync": brain.last_reminders_sync})
            elif path == "/dreamlayer/rewind":
                self._json(200, brain.rewind())
            elif path == "/dreamlayer/saga":
                self._json(200, brain.saga.snapshot())
            elif path == "/dreamlayer/plugins":
                self._json(200, brain.plugins_state())
            elif path == "/dreamlayer/rc/repertoire":
                # the Reality Compiler Repertoire: kept figments the phone lists
                self._json(200, brain.rc_repertoire())
            elif path == "/dreamlayer/social/people":
                # your social memory: everyone met, notes, relations, debts
                self._json(200, brain.social_people_state())
            elif path == "/dreamlayer/memories":
                # the phone's Memories tab: places you saved, people met, favors
                # owed, dated reminders — assembled from what the Brain holds
                self._json(200, brain.memories())
            elif path == "/dreamlayer/profile":
                # what the Juno has learned about you (mirrored from the hub)
                self._json(200, brain.profile)
            elif path == "/dreamlayer/brief/latest":
                self._json(200, brain.last_brief or {})
            elif path == "/dreamlayer/brief/long/latest":
                self._json(200, brain.last_long_brief or {})
            elif path == "/dreamlayer/messages/recent":
                # the live Messages/Mail feed the glasses read hands-free
                if not brain.config.email_enabled:
                    self._json(200, {"items": [], "enabled": False}); return
                try:
                    items = brain._messages_fn(brain.config, 20)
                except Exception:
                    items = []
                if brain.config.summarize_emails:
                    for it in items:
                        if it.get("channel") == "email":
                            it["summary"] = brain.summarize(it.get("text", ""))
                self._json(200, {"items": items, "enabled": True,
                                 "summarize_emails": brain.config.summarize_emails})
            elif path == "/dreamlayer/model/status":
                self._json(200, probe_ollama(brain.config))
            elif path == "/dreamlayer/browse":
                # a server-side folder picker (the panel navigates the Mac's
                # own filesystem) — local-only, like pairing
                if not self._from_localhost():
                    self._json(403, {"error": "browse is local-only"}); return
                self._json(200, _browse_dir(qs.get("path", [""])[0]))
            elif path == "/dreamlayer/pair":
                # a pairing code for the phone — only handed to the local panel
                if not self._from_localhost():
                    self._json(403, {"error": "pairing is local-only"}); return
                from ...pairing import PairingBundle, encode_pairing
                # the code must point the phone at an address it can reach on the
                # LAN — never the loopback/Host the local browser used.
                port = self.server.server_address[1]
                ip = lan_ip()
                if ip and ip != "127.0.0.1":
                    url = f"http://{ip}:{port}"
                else:
                    url = "http://" + (self.headers.get("Host") or f"127.0.0.1:{port}")
                bundle = PairingBundle(brain_url=url, token=brain.config.token)
                brain.activity.add("pair", "Generated a pairing code for the phone")
                brain.saga_record("pair")
                code = encode_pairing(bundle)
                from .qr import to_svg
                self._json(200, {"code": code, "url": url, "qr": to_svg(code)})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
            if not self._authed():
                self._json(401, {"error": "unauthorised"}); return
            if path == "/dreamlayer/memory/browse":
                if not self._from_localhost():
                    self._json(403, {"error": "browsing memory is local-only"}); return
                self._json(200, _memory_browse(brain))
                return
            if path == "/dreamlayer/memory/export":
                if not self._from_localhost():
                    self._json(403, {"error": "export is local-only"}); return
                self._json(200, _memory_export(brain, self._body().get("dest", "")))
                return
            if path == "/dreamlayer/folders":
                b = self._body()
                p = b.get("path", "")
                if b.get("action") == "add":
                    if brain.config.add_folder(p):
                        brain.activity.add("folder", f"Added folder {p}")
                        brain.saga_record("folder")
                elif b.get("action") == "remove":
                    brain.config.remove_folder(p)
                    brain.activity.add("folder", f"Removed folder {p}")
                brain.save(); brain.reindex()
                self._json(200, {"config": brain.config.public(),
                                 "stats": brain.index.stats()})
            elif path == "/dreamlayer/config":
                body = self._body()
                before = (brain.config.model, brain.config.cloud_enabled,
                          brain.config.network_mode, brain.config.email_enabled)
                brain.apply_config(body)
                brain.reindex()
                if "model" in body and brain.config.model != before[0]:
                    brain.activity.add("model", f"Model set to {brain.config.model}")
                if "cloud_enabled" in body and brain.config.cloud_enabled != before[1]:
                    brain.activity.add("cloud", "Cloud enabled" if brain.config.cloud_enabled else "Cloud disabled")
                if "network_mode" in body and brain.config.network_mode != before[2]:
                    brain.activity.add("privacy", "Incognito on" if brain.config.lan_only else "Incognito off")
                if "email_enabled" in body and brain.config.email_enabled != before[3]:
                    brain.activity.add("config", "Email & iMessage " + ("on" if brain.config.email_enabled else "off"))
                self._json(200, {"config": brain.config.public()})
            elif path == "/dreamlayer/capabilities":
                # one-click on/off for an INSTALLED optional capability — the
                # persisted twin of DL_DISABLE_<KEY>. Never installs anything.
                from ...capabilities import CAPABILITIES
                b = self._body()
                key = str(b.get("key", ""))
                if key not in {c.key for c in CAPABILITIES}:
                    self._json(400, {"error": f"unknown capability: {key}"}); return
                off = set(brain.config.disabled_caps)
                (off.add if b.get("disabled") else off.discard)(key)
                brain.config.disabled_caps = sorted(off)
                brain.save()
                brain.activity.add("config", f"Capability {key} "
                                   + ("switched off" if b.get("disabled") else "switched on"))
                self._json(200, _capability_payload(brain))
            elif path == "/dreamlayer/packs":
                # one-click pack install (source installs only; allowlisted —
                # the client names a curated pack, never a package)
                b = self._body()
                job = _install_pack(brain, str(b.get("pack", "")))
                if "error" in job:
                    self._json(400, job); return
                self._json(200, _capability_payload(brain))
            elif path == "/dreamlayer/upload":
                folder = (qs.get("folder", [""])[0])
                name = Path(qs.get("name", ["dropped.txt"])[0]).name
                ok = _write_upload(brain, folder, name, self._raw())
                if ok:
                    brain.activity.add("upload", f"Added {name}")
                brain.reindex()
                self._json(200 if ok else 400,
                           {"ok": ok, "stats": brain.index.stats()})
            elif path == "/dreamlayer/brain/ask":
                ans = brain.ask(self._body().get("query", ""))
                self._json(200, _answer_json(ans))
            elif path == "/dreamlayer/plugins/install":
                self._json(200, brain.install_plugin(self._body()))
            elif path == "/dreamlayer/plugins/remove":
                self._json(200, brain.remove_plugin(self._body().get("name", "")))
            elif path == "/dreamlayer/rc/rehearse":
                b = self._body()
                self._json(200, brain.rc_rehearse(b.get("name", ""),
                                                  b.get("beats") or []))
            elif path == "/dreamlayer/rc/keep":
                self._json(200, brain.rc_keep(self._body().get("figment_id", "")))
            elif path == "/dreamlayer/rc/deploy":
                self._json(200, brain.rc_deploy(self._body().get("figment_id", "")))
            elif path == "/dreamlayer/rc/revoke":
                self._json(200, brain.rc_revoke(self._body().get("figment_id", "")))
            elif path == "/dreamlayer/rc/compose":
                # "Ask Juno" — describe a lens in words, get a verified figment
                # back into the builder (offline intent parser; not deployed)
                self._json(200, brain.rc_compose(self._body().get("prompt", "")))
            elif path == "/dreamlayer/rc/feed":
                # stream host text (translation / camera label / memory) into the
                # running lens's {slot} — the world-facing showcases' live wire
                b = self._body()
                self._json(200, brain.rc_feed(b.get("text", ""), b.get("source", "")))
            elif path == "/dreamlayer/rc/emit":
                # the lens emitted a tag; act on it and stream the result back
                # (emit "ask" → Brain answers into the slot). Closes the loop.
                b = self._body()
                self._json(200, brain.rc_emit(b.get("tag", ""), b.get("text", "")))
            elif path == "/dreamlayer/rc/import":
                # the no-code browser builder's "Deploy to my Brain"
                self._json(200, brain.rc_import(self._body().get("figment") or self._body()))
            elif path.startswith("/dreamlayer/event/"):
                # the $6 physical-events kit (INNOVATION 1.6): a sensor out in
                # the world POSTs a named signal to the figment on stage.
                #   /dreamlayer/event/ble/3  → "ble:3"   (numeric code channel)
                #   /dreamlayer/event/mail   → "mail"    (named)
                rest = path[len("/dreamlayer/event/"):].strip("/")
                parts = rest.split("/")
                if parts[0] == "ble" and len(parts) == 2 and parts[1].isdigit():
                    name = f"ble:{parts[1]}"
                else:
                    name = parts[0]
                self._json(200, brain.rc_event(name))
            elif path == "/dreamlayer/social/people":
                # the hub pushes its social-memory snapshot here
                self._json(200, brain.receive_people(self._body()))
            elif path == "/dreamlayer/social/people/edit":
                # a phone edit: add/remove a note, set relation, settle debts
                self._json(200, brain.edit_person(self._body()))
            elif path == "/dreamlayer/memories/purge":
                # "Erase all memories" from the phone's danger zone — honored
                # here so a later refresh can't resurrect what was erased
                self._json(200, brain.purge_memories())
            elif path == "/dreamlayer/brief":
                b = self._body()
                out = brain.brief(agenda=b.get("agenda"),
                                  since=b.get("since", 0) or 0,
                                  depth=b.get("depth", "short"),
                                  commitments=b.get("commitments"),
                                  memories=b.get("memories"))
                if out.get("depth") == "long":     # keep the last long brief for the phone
                    brain.last_long_brief = {**out, "ts": time.time()}
                self._json(200, out)
            elif path == "/dreamlayer/replies":
                b = self._body()
                self._json(200, {"replies": brain.suggest_replies(b.get("text", ""))})
            elif path == "/dreamlayer/voice":
                # route a spoken/typed line: ask/recall answered here, the rest
                # returned as a structured intent for the app to act on
                from ...orchestrator.voice import parse_intent
                it = parse_intent(self._body().get("text", ""))
                if it.kind in ("ask", "recall"):
                    ans = brain.ask(it.args.get("query", ""))
                    self._json(200, {"intent": it.kind, "query": it.args.get("query", ""),
                                     "answer": ans.text if ans is not None else ""})
                elif it.kind == "brief":
                    self._json(200, {"intent": "brief", **brain.brief()})
                elif it.kind in ("timer", "interval", "clock"):
                    # native behaviors Juno builds & runs (docs/RC_V2): a
                    # timer/interval compiles to a Figment on the stage; a
                    # clock time-query just answers
                    self._json(200, brain.rc_native(it.kind, it.args))
                elif it.kind == "timer_cancel":
                    self._json(200, brain.rc_native_cancel())
                elif it.kind in ("note_person", "meet_person", "debt", "debt_settle"):
                    # full parity with the hub: apply to the people mirror the
                    # People screen reads, so typed voice works like spoken
                    self._json(200, brain.voice_social(it.kind, it.args))
                elif it.kind == "stash":
                    self._json(200, brain.waypath_stash(
                        it.args.get("subject", ""), it.args.get("place", "")))
                elif it.kind == "locate":
                    self._json(200, brain.waypath_locate(it.args.get("subject", "")))
                elif it.kind == "missed":
                    self._json(200, brain.missed(it.args.get("since", 0) or 0))
                elif it.kind == "reply":
                    self._json(200, brain.voice_reply(
                        it.args.get("to", ""), it.args.get("text", "")))
                else:
                    self._json(200, {"intent": it.kind, **it.args})
            elif path == "/dreamlayer/calendar":
                # add or remove an agenda event ({title, ts, place[, remove]})
                b = self._body()
                if b.get("remove"):
                    items = brain.remove_event(b.get("title", ""), b.get("ts"))
                else:
                    items = brain.add_event(b.get("title", ""),
                                            b.get("ts", 0) or 0, b.get("place", ""))
                self._json(200, {"items": items})
            elif path == "/dreamlayer/calendar/sync":
                # pull macOS Calendar.app into the agenda now
                self._json(200, brain.sync_calendar())
            elif path == "/dreamlayer/contacts/sync":
                self._json(200, brain.sync_contacts())
            elif path == "/dreamlayer/reminders/sync":
                self._json(200, brain.sync_reminders())
            elif path == "/dreamlayer/saga/record":
                # the hub / phone reports an ecosystem event it drove (e.g. a
                # voice wake, a dossier, focus, rewind) so its badge can unlock
                ev = self._body().get("event", "")
                self._json(200, {"unlocked": brain.saga_record(ev) if ev else [],
                                 "saga": brain.saga.snapshot()})
            elif path == "/dreamlayer/profile":
                # the glasses hub pushes its Juno profile snapshot so the phone
                # can read it (the hub->Brain bridge). Mirror-only.
                self._json(200, brain.set_profile(self._body()))
            elif path == "/dreamlayer/model/pull":
                # one-click Ollama pull — local-only (it runs a long job on the box)
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                self._json(200, brain.pull_model(self._body().get("model", "")))
            elif path == "/dreamlayer/people":
                # introduce/update or remove a person ({name, note, tags[, remove]})
                b = self._body()
                if b.get("remove"):
                    items = brain.remove_person(b.get("name", ""))
                else:
                    items = brain.add_person(b.get("name", ""), b.get("note", ""),
                                             b.get("tags"))
                self._json(200, {"items": items})
            elif path == "/dreamlayer/brain/explain":
                b = self._body()
                ans = brain.explain(b.get("label", ""), b.get("image"),
                                    b.get("want", "quick"))
                self._json(200, _answer_json(ans))
            elif path == "/dreamlayer/reindex":
                stats = brain.reindex()
                brain.activity.add("index", "Re-indexed your folders")
                self._json(200, {"stats": stats, "missing": brain.missing_folders()})
            elif path == "/dreamlayer/token/rotate":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                import secrets
                brain.config.token = secrets.token_hex(8)
                brain.save()
                brain.activity.add("privacy", "Rotated the pairing token — devices must re-pair")
                self._json(200, {"token": brain.config.token})
            elif path == "/dreamlayer/clear":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                what = self._body().get("what", "")
                if what in ("history", "all"): brain.history.clear()
                if what in ("activity", "all"): brain.activity.clear()
                if what in ("folders", "all"):
                    brain.config.folders = []; brain.save(); brain.reindex()
                # don't re-seed the activity log we just cleared
                if what in ("history", "folders"):
                    brain.activity.add("config", f"Cleared {what}")
                self._json(200, {"ok": True, "stats": brain.index.stats()})
            elif path == "/dreamlayer/cloud/test":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                from .backends import cloud_test
                self._json(200, cloud_test(brain.config))
            elif path == "/dreamlayer/restore":
                if not self._from_localhost():
                    self._json(403, {"error": "restore is local-only"}); return
                brain.import_backup(self._body())
                brain.activity.add("config", "Restored from a backup")
                self._json(200, {"ok": True, "config": brain.config.public()})
            elif path == "/dreamlayer/message/draft":
                from .macos_sources import MessageDraft, build_send_script
                b = self._body()
                d = MessageDraft(channel=b.get("channel", "imessage"),
                                 to=b.get("to", ""), subject=b.get("subject", ""),
                                 text=b.get("text", ""))
                self._json(200, {"script": build_send_script(d)})
            elif path == "/dreamlayer/message/send":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                from .macos_sources import MessageDraft, send_message
                b = self._body()
                d = MessageDraft(channel=b.get("channel", "imessage"),
                                 to=b.get("to", ""), subject=b.get("subject", ""),
                                 text=b.get("text", ""))
                try:
                    res = send_message(d, approved=bool(b.get("approved")))
                    brain.activity.add("message", f"Sent a {d.channel} to {d.to}")
                    self._json(200, res)
                except Exception as e:  # noqa: BLE001
                    self._json(400, {"error": str(e)[:200]})
            else:
                self._json(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler)


def _write_upload(brain: Brain, folder: str, name: str, data: bytes) -> bool:
    # only into a folder the Brain already watches (no arbitrary writes)
    target = str(Path(folder).expanduser())
    if target not in brain.config.folders:
        return False
    dest = Path(target) / name
    try:
        dest.write_bytes(data)
        return True
    except OSError:
        return False


def _clip_brief(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _version() -> str:
    try:
        import dreamlayer
        return getattr(dreamlayer, "__version__", "0.0.0")
    except Exception:
        return "0.0.0"


def _answer_json(ans: Optional[Answer]) -> dict:
    if ans is None:
        return {"text": "", "tier": "", "sources": [], "confidence": 0.0}
    return {"text": ans.text, "tier": ans.tier, "sources": ans.sources,
            "confidence": ans.confidence}


def _activity_feed(brain: Brain, n: int = 40) -> list[dict]:
    """One newest-first feed: questions + every action the Brain took."""
    items = []
    for h in brain.history.recent(n):
        items.append({"ts": h.get("ts", 0), "kind": "ask",
                      "query": h.get("query", ""), "text": h.get("answer", ""),
                      "tier": h.get("tier", "")})
    for a in brain.activity.recent(n):
        items.append({"ts": a.get("ts", 0), "kind": a.get("kind", "event"),
                      "text": a.get("text", "")})
    items.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return items[:n]


def _browse_dir(raw: str) -> dict:
    """List the subfolders of a directory so the panel can walk the Mac's own
    filesystem — folders only, hidden entries skipped."""
    base = Path(raw).expanduser() if raw else Path.home()
    try:
        base = base.resolve()
    except OSError:
        base = Path.home()
    if not base.is_dir():
        base = Path.home()
    dirs = []
    try:
        for e in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if e.is_dir() and not e.name.startswith("."):
                dirs.append(e.name)
    except OSError:
        pass
    parent = str(base.parent) if base.parent != base else ""
    return {"path": str(base), "parent": parent, "dirs": dirs,
            "home": str(Path.home())}
