---
name: refute-remediation
description: >-
  Adversarially re-audit a security remediation to find the gaps the fix's own
  author could not see. Use AFTER any security-remediation wave — privacy/veil,
  auth, sandbox/plugin-isolation, cloud-egress, or concurrency fixes — and
  ESPECIALLY when the fix was written and reviewed by the same session, which
  shares its blind spots by construction. Spawns independent auditors each
  tasked to REFUTE (not confirm) a slice of the fix, verifies every claim in
  raw code, then fixes the verified findings. Triggers on: "re-audit the
  fixes", "refute the remediation", "adversarial pass on the fixes", "did the
  audit actually close it", "verify the security fix", after merging any
  security/privacy remediation PR.
---

# Refute a remediation

## Why this exists

A remediation graded and reviewed by the same session that wrote it inherits
that session's blind spots. Passing tests and a confident PR writeup are not
evidence the finding is closed — they are evidence of what the author thought
to check. Twice now, the "verify the fixes, not just the bugs" pass has caught
a **live privacy leak** that a green suite and an audit writeup both declared
closed (a phone client that never sent the `no_cloud` posture on two of three
Brain endpoints; before that, a `purge_all` primitive that wiped rows but not
the ember sidecar). This is not occasional diligence — after a security
remediation it is a required step.

The stance is **refutation, not confirmation**. Each auditor's job is to make
the fix fail, not to bless it. Default to skepticism; assume every gate is fake
until you see the check on the hot path.

## The method

1. **Decompose the remediation into slices** — one per fix or per subsystem
   (e.g. "cloud egress completeness", "veil-gate vacuity", "plugin jail
   bypass", "the removed-code regression + concurrency tail"). Aim for 3–5
   slices that partition the diff.

2. **Spawn one independent auditor per slice** (the `Agent` tool,
   `general-purpose`, run in background, in parallel — one message, multiple
   calls). Each auditor gets: the repo root, the exact claim it must REFUTE,
   the specific files, and a mandate to read the *real merged code end to end*,
   not the PR prose. Require every finding to carry `file:line`, a concrete
   failure scenario (inputs/state → what leaks/breaks), and a verdict —
   **CONFIRMED** (traced end to end) or **PLAUSIBLE** (looks wrong, not fully
   traced). Tell each auditor to also state plainly what genuinely held.

3. **Verify every surfaced finding yourself before fixing.** An auditor claim
   is a lead, not a fact — open the cited lines, confirm the path is reachable,
   confirm the guard that should stop it doesn't. Downgrade or drop anything
   that doesn't reproduce in the code.

4. **Fix verified findings at the primitive, not the call-site** — the same
   by-construction discipline the remediation should have used. Each fix gets a
   regression test that **fails on revert** (assert the leak/break, not just
   the happy path). One coherent PR through the full gate.

5. **Report honestly, both ways.** State what was CONFIRMED and fixed, what was
   PLAUSIBLE and deferred, and — importantly — **what held**. A remediation
   that survives the pass mostly intact is the normal, good outcome; say so
   instead of manufacturing findings.

## The recurring blind-spot classes

These are where self-written remediations leak. Point auditors at them
explicitly:

- **Sibling call-sites.** The author patched and tested the path they were
  looking at; the same sink is reached by other endpoints/clients that were
  missed. *Enumerate every caller of the sensitive sink, not just the obvious
  one.* (The `no_cloud` leak: `/brain/ask` fixed, `/voice` + `/rc/emit` +
  the phone client missed.)
- **Vacuous gating.** A `privacy`/gate object is passed into a constructor or
  stored on `self`, but the hot path never calls `allow_capture()`/
  `allow_recall()`. Wired ≠ checked. *Find the check on the line that does the
  sensitive thing, or it isn't gated.*
- **Alternate load / entry paths.** The jail is closed on one door
  (`store.py`) but code still runs untrusted via entry-points, dev-mode,
  direct registration, or a discovery loader. *Enumerate every way the thing
  executes.*
- **Fail-open defaults / silence = permission.** A missing/malformed field, an
  absent gate, or a swallowed exception defaults to *allow*. *A privacy or
  trust primitive with no explicit signal must deny, not permit.*
- **Fixed-tmp / no-lock "atomic" writes.** `tmp = path + ".tmp"; write; replace`
  is atomic in the *rename* only — a shared tmp name with no lock lets two
  threads interleave into it. *Per-writer tmp + a lock.*
- **Neutralized-but-still-computed signals.** A channel zeroed in the verdict
  but still computed from live data can surface elsewhere (dominant-channel,
  a displayed z-score). *Neutral must mean neutral everywhere, including
  display.*

## Scale

Match the fan-out to the remediation. A one-file fix: one or two auditors,
single-vote verify. A multi-subsystem security wave: 4–5 auditors, each on a
distinct slice, then hand-verify. Don't run the fan-out for non-security
changes — this is for fixes where a missed gap is a live vulnerability.
