#!/usr/bin/env python3
"""
scripts/run_demo_rc_v2.py — Reality Compiler v2 (Rehearsal): five sessions.

Each session walks end-to-end: the user's request, the authoring
interaction (beats on the stage), the compilation output (Figment +
budget proof), the Halo-side render, and 30 seconds of runtime behavior.
Frame sequences export to out/rc_v2/<session>/.

Sessions
  1_v1_round_timer   v1 plain-English phrasing, lifted — backward compat
  2_rolling_rounds   the flagship rehearsal (3:00 rolls, 10 s pulse, loop)
  3_spar_night       impossible in v1: two phases + tap counting + bounded
                     rounds + until-hold, one rehearsal
  4_strobe_refused   unsafe request → TeachCard → corrected by re-performing
                     one beat — the teachability model
  5_hot_swap_revoke  sign → deploy → hot-swap mid-run → revoke, no reboot

Run:  cd host-python && python ../scripts/run_demo_rc_v2.py
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "host-python" / "src"))

from dreamlayer.reality_compiler.v2 import (           # noqa: E402
    RealityCompilerV2, Stage, render_png, transcript,
)

OUT = REPO_ROOT / "out" / "rc_v2"

# Windows forbids  < > : " / \ | ? *  in filenames, so a frame label carrying a
# clock ("2:48") would emit a colon filename that can't be cloned on Windows
# (fixed once in #210; sanitize here so a regeneration can't reintroduce it).
# Space -> "_" preserves the existing golden naming; the illegal set -> "-".
_LABEL_SANITIZE = str.maketrans({" ": "_", **{c: "-" for c in '<>:"/\\|?*'}})


def _safe_label(label: str) -> str:
    return label.translate(_LABEL_SANITIZE)


def banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def export_playback(frames, outdir: Path) -> int:
    outdir.mkdir(parents=True, exist_ok=True)
    n = 0
    for i, pf in enumerate(frames):
        path = outdir / f"{i:03d}_{_safe_label(pf.label[:28])}.png"
        if render_png(pf.frame, str(path)):
            n += 1
    (outdir / "transcript.txt").write_text(transcript(frames) + "\n")
    return n


def run_30s(fig, outdir: Path, events=(), seed: int = 7,
            battery: int = 100) -> list[str]:
    """Simulate 30 s of runtime at 1 s ticks, exporting changed frames."""
    outdir.mkdir(parents=True, exist_ok=True)
    stage = Stage(fig, rng=random.Random(seed), battery_level=battery)
    events = sorted(events, key=lambda e: e[0])
    log: list[str] = []
    last_render = None
    saved = 0
    for sec in range(31):
        while events and events[0][0] <= sec:
            _, ev = events.pop(0)
            extra = ev.split("=", 1)
            if extra[0] == "text":
                stage.inject("text", extra[1])
            else:
                stage.inject(ev)
            log.append(f"t={sec:02d}s  event {ev} → scene {stage.current}")
        frame = stage.frame()
        key = (frame.scene, tuple((l.text, l.color) for l in frame.lines),
               frame.pulse_on)
        if key != last_render and saved < 24:
            path = outdir / f"run_{sec:02d}s_{_safe_label(frame.scene)}.png"
            render_png(frame, str(path))
            saved += 1
            last_render = key
        body = " / ".join(l.text for l in frame.lines) or "(blank)"
        log.append(f"t={sec:02d}s  [{frame.scene}]"
                   f"{' ●' if frame.pulse_on else '  '} {body}")
        stage.step(1.0)
        if stage.ended:
            log.append(f"t={sec:02d}s  figment ended — stage goes ambient")
            break
    for t, tag in stage.emits:
        log.append(f"emit @ {t:.0f}s: {tag!r} → phone")
    (outdir / "runtime.txt").write_text("\n".join(log) + "\n")
    return log


def main() -> None:
    vault_dir = Path(tempfile.mkdtemp(prefix="rc_v2_demo_vault_"))
    rc = RealityCompilerV2(vault_dir=vault_dir)
    report: dict = {"sessions": {}}

    # ------------------------------------------------------------------
    # Session 1 — v1 phrasing, lifted (backward compat, 1:1)
    # ------------------------------------------------------------------
    banner("SESSION 1 — v1 template, unchanged phrasing (backward compat)")
    text = "3 minute round timer with 20 seconds overtime"
    print(f'user (v1 surface): "{text}"')
    res = rc.compile_text(text)
    print(f"lifted v1 intent : {res.figment.meta['v1_type']}")
    print(res.figment.describe())
    print(res.report)
    outdir = OUT / "1_v1_round_timer"
    n = export_playback(res.playback, outdir / "playback")
    run_30s(res.figment, outdir / "runtime",
            events=[(1, "double")])
    entry = rc.keep(res.figment)
    rec = rc.deploy(res.figment.id)
    print(f"signed {entry.sig[:16]}… → {rec.message}")
    report["sessions"]["1_v1_round_timer"] = {
        "ok": res.ok, "playback_frames": n, "deployed": rec.success}

    # ------------------------------------------------------------------
    # Session 2 — the flagship rehearsal
    # ------------------------------------------------------------------
    banner("SESSION 2 — Rehearsal: 3-minute rolls, 10 s pulse, repeats")
    print('user: "keep a 3-minute timer going during my rolls'
          ' with a 10-second pulse at the end"')
    s = rc.rehearse("Rolling rounds")
    beats = [s.double_tap(), s.say("rolling - three minutes"),
             s.say("last ten seconds, pulse"),
             s.say("then it starts again")]
    for b in beats:
        print(f"  beat {b.index + 1}: {b.reading()}")
    r = s.finish()
    print(f"\nrun-through ({len(r.playback)} frames, time-folded):")
    print(transcript(r.playback[:8]))
    print("  …")
    print(r.report)
    outdir = OUT / "2_rolling_rounds"
    n = export_playback(r.playback, outdir / "playback")
    run_30s(r.figment, outdir / "runtime", events=[(1, "double")])
    entry = rc.keep(r.figment)
    rec = rc.deploy(r.figment.id)
    print(f"kept + signed {entry.sig[:16]}… → {rec.message}")
    report["sessions"]["2_rolling_rounds"] = {
        "ok": r.ok, "playback_frames": n, "deployed": rec.success,
        "authoring_beats": len(beats)}

    # ------------------------------------------------------------------
    # Session 3 — impossible in v1
    # ------------------------------------------------------------------
    banner("SESSION 3 — impossible in v1: phases + counting + bounded loop")
    print('user: "one minute drilling then three minutes rolling, pulse at'
          ' the end, count my taps, five rounds, until I hold"')
    s = rc.rehearse("Spar night")
    beats = [s.double_tap(),
             s.say("drilling - one minute"),
             s.say("rolling - three minutes"),
             s.say("last ten seconds, pulse"),
             s.say("count this"),
             s.say("again 5 times"),
             s.say("until I hold")]
    for b in beats:
        print(f"  beat {b.index + 1}: {b.reading()}")
    r = s.finish()
    print()
    print(r.figment.describe())
    print(r.report)
    outdir = OUT / "3_spar_night"
    n = export_playback(r.playback, outdir / "playback")
    # 30 s of runtime: start, tap points during drilling, hold to exit
    run_30s(r.figment, outdir / "runtime",
            events=[(1, "double"), (5, "double"), (9, "double"),
                    (28, "long")])
    entry = rc.keep(r.figment)
    rec = rc.deploy(r.figment.id)
    print(f"kept + signed → {rec.message}")
    print("v1 could not express any of: two phases, a counter during a "
          "timer,\nbounded rounds with progress, or an until-gesture exit.")
    report["sessions"]["3_spar_night"] = {
        "ok": r.ok, "playback_frames": n, "deployed": rec.success}

    # ------------------------------------------------------------------
    # Session 4 — unsafe request → teachable failure → corrected
    # ------------------------------------------------------------------
    banner("SESSION 4 — unsafe request refused, then corrected (teachability)")
    print('user: "thirty seconds… strobe thirty times a second"')
    s = rc.rehearse("Strobe drill")
    s.say("thirty seconds")
    bad = s.say("strobe thirty times a second")
    r = s.finish()
    assert not r.ok
    print("\nHUD teach card:")
    for line in r.teach.hud_lines():
        print(f"   | {line}")
    outdir = OUT / "4_strobe_refused"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "teach_card.txt").write_text(str(r.teach) + "\n" +
                                           str(r.report) + "\n")
    print(f"\nuser re-performs beat {bad.index + 1}: \"last ten seconds, pulse\"")
    s.redo(bad.index, "last ten seconds, pulse")   # the stage reopens at that beat
    r2 = s.finish()
    print(r2.report)
    n = export_playback(r2.playback, outdir / "playback")
    run_30s(r2.figment, outdir / "runtime")
    print("corrected rehearsal compiles — the failure cost one beat.")
    report["sessions"]["4_strobe_refused"] = {
        "refused": not r.ok, "teach": str(r.teach),
        "corrected_ok": r2.ok, "playback_frames": n}

    # ------------------------------------------------------------------
    # Session 5 — sign, deploy, hot-swap mid-run, revoke; no reboot
    # ------------------------------------------------------------------
    banner("SESSION 5 — hot-swap and revoke at runtime")
    s = rc.rehearse("Water break")
    s.say("water break - twenty seconds")
    r = s.finish()
    rc.keep(r.figment)
    water_id = r.figment.id

    print("repertoire:", ", ".join(f"{e.figment.name} ({e.figment.id[:6]}…)"
                                   for e in rc.repertoire()))
    rec1 = rc.deploy(water_id)
    print(f"deploy      → {rec1.message}")
    print(f"  envelopes : {[e['t'] for e in rec1.envelopes]}")
    rec2 = rc.deploy(rc.repertoire()[0].figment.id)  # hot-swap to another
    print(f"hot-swap    → {rec2.message}")
    print(f"  envelopes : {[e['t'] for e in rec2.envelopes]}")
    rec3 = rc.revoke(water_id)
    print(f"revoke      → {rec3.message}")
    rec4 = rc.deploy(water_id)
    print(f"redeploy revoked → success={rec4.success}: {rec4.message}")
    outdir = OUT / "5_hot_swap_revoke"
    outdir.mkdir(parents=True, exist_ok=True)
    n = export_playback(r.playback, outdir / "playback")
    (outdir / "envelopes.json").write_text(json.dumps(
        rc.deployer.sent, indent=1)[:4000])
    report["sessions"]["5_hot_swap_revoke"] = {
        "deploy": rec1.success, "swap": rec2.success,
        "revoke": rec3.success, "revoked_redeploy_refused": not rec4.success}

    # ------------------------------------------------------------------
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    banner("DONE")
    print(f"frames + transcripts under {OUT}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
