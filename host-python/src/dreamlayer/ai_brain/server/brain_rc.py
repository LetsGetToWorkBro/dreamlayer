"""ai_brain/server/brain_rc.py — the Reality Compiler method cluster.

A mixin the Brain inherits (behaviour-preserving extraction). Every method
here still runs on the coordinator instance (shared ``self``), so ``self.rc``,
``self.activity``, ``self.health`` and ``self.ask`` resolve exactly as before —
no logic changed in the move. This is the ``ops_*`` pattern the orchestrator
uses, applied to the Brain.
"""
from __future__ import annotations

from ._brain_host import BrainHost

import time


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


class RCOps(BrainHost):
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
            assert fig is not None      # ok=True always carries a figment
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

    def _active_figment(self):
        """The Figment on stage right now, loaded from the vault, or None."""
        if self._rc_active is None:
            return None
        try:
            return self.rc.vault.load(self._rc_active).figment
        except Exception:
            return None

    def _cap_ask(self, text: str, no_cloud: bool = False) -> tuple[str, dict]:
        """The `ask` capability: run the Brain over the spoken question and hand
        back the answer (+ which tier answered it) to stream onto the glass.
        no_cloud carries the wearer's session posture (incognito / cloud-off) so
        a lens-driven ask honors the Veil at the same sink /brain/ask does."""
        ans = self.ask(text or "", no_cloud=no_cloud)
        reply = (ans.text if ans and not ans.is_empty() else "") or "no answer yet"
        self.activity.add("rc", "Lens asked → Brain answered")
        return reply, {"answer": reply, "tier": ans.tier if ans else ""}

    def rc_emit(self, tag: str, text: str = "", no_cloud: bool = False) -> dict:
        """Close the loop glass → Brain → glass. A running lens emits a tag and
        the Brain acts on it, streaming the result back into the lens's slot.

        The reaction is gated by the **capability contract**
        (reality_compiler/v2/capabilities.py): a tag that names a capability
        (``ask``/``translate``/``look``) is honored only if the active lens
        declared it in ``requires`` — the runtime twin of the author-time
        validator, so a forged figment can't invoke a power it never asked for.

          ``ask``            → host-computed: run your Brain over the question,
                               push the answer (your files/memory, or cloud if
                               allowed)
          other capability   → carry the tag's own text payload to the slot (a
                               camera label from ``look``, a hub translation)
          free/local tag     → acknowledged, left for a plugin/hub to interpret

        Refused when no lens is on stage."""
        from ...reality_compiler.v2.figment import MAX_EMIT_TAG_LEN
        from ...reality_compiler.v2.capabilities import (
            capability_for, declared_requires,
        )
        tag = str(tag or "")[:MAX_EMIT_TAG_LEN]
        if not tag:
            return {"ok": False, "error": "empty emit tag"}
        if self._rc_active is None:
            return {"ok": False, "error": "no lens on stage"}

        cap = capability_for(tag)
        if cap:
            fig = self._active_figment()
            if fig is None or cap not in declared_requires(fig):
                return {"ok": False, "tag": tag, "active": self._rc_active,
                        "error": f"lens did not declare capability {cap!r}"}
            handler = self._capability_handlers.get(cap)
            if handler:
                reply, extra = handler(text or "", no_cloud=no_cloud)
                return {**self.rc_feed(reply, source=cap), "tag": tag, **extra}
            # a declared capability the phone/hub fulfills (translate/look):
            # its payload is the result — route it straight to the slot
            if text:
                return {**self.rc_feed(text, source=f"emit:{tag}"), "tag": tag}
            return {"ok": True, "tag": tag, "active": self._rc_active, "noted": True}

        # a free/local emit with no built-in reaction: acknowledged, left for a
        # plugin/hub to interpret, never an error
        if text:
            return {**self.rc_feed(text, source=f"emit:{tag}"), "tag": tag}
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
        except Exception as exc:
            self.health.record_failure("rc:vault_revoke", exc)
        self.activity.add("rc", f"Juno started {fig.name!r}")
        return {"ok": record.success, "intent": intent, "say": say,
                "figment_id": fig.id, "name": fig.name}

    def rc_native_cancel(self) -> dict:
        """Clear whatever native behavior is on the stage."""
        if self._rc_active:
            self.rc.revoke(self._rc_active)
            self._rc_active = None
        return {"ok": True, "say": "Stopped.", "intent": "timer_cancel"}
