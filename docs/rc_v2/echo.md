# Echo — Deep Dive (Phase 3 survivor)

> You never author anything — the glasses notice what you keep doing and
> offer to keep doing it for you.

## 1. Full paradigm description

Echo deletes the authoring session. The system observes *manual, on-device
usage* — which figments/templates the user arms, when, where, what they
override — and mines the event stream for recurrences. When a pattern crosses
a confidence threshold, Echo materializes it as a **proposal**: a fully
formed, verified, *unsigned* Figment plus a one-line plain-words reading,
delivered as a single card at a contextually quiet moment. One tap adopts it
(sign + vault + arm-on-context); one long-press declines and suppresses the
pattern. Corrections are the same loop at smaller scale: if the user keeps
manually overriding a parameter of an adopted figment, Echo proposes the
amendment.

Echo's authoring input is therefore *the user's life*, and its entire syntax
is two gestures: tap (yes) and long-press (no).

## 2. The complete surface

In-eye proposal card (the only new HUD state):

```
        .-----------------.
      /      NOTICED         \
     |  Tuesdays around 6pm   |
     |  you run 3:00 rounds   |
     |    with an end pulse   |
     |                        |
     |  tap: run them for you |
      \  hold: don't ask     /
        '-----------------'
```

Phone side: a **Habits** pane listing adopted echoes (name, context trigger,
last fired, revoke) and declined patterns (so a "no" can be un-said). No
editor — an adopted echo that needs reshaping opens in whichever authoring
surface exists (Rehearsal/Loom), pre-loaded.

Voice grammar: none. Gesture set: tap / long-press on the proposal card.

## 3. Safety model

Proposals are machines, so the substrate is again the shared one: mined
pattern → Figment → static verifier → (on adoption) sign → vault → deploy to
the fixed stage. Two Echo-specific rules:

- **Nothing self-adopts.** A proposal is inert data until the tap; Echo can
  never deploy, schedule, or emit without the explicit gesture. Declined
  patterns enter a suppression list checked before any future proposal.
- **Observation is local.** The usage stream Echo mines is the same
  structured, on-phone event log the privacy model already governs — raw
  media is never consulted, the log never leaves the phone, and pausing
  capture pauses Echo's observation too.

## 4. Teachability model

Echo cannot "fail to compile" for the user — the user never composes.
Its failure modes are *bad guesses*, and the teachability channel is the
proposal card itself: every proposal states its evidence in the user's terms
("Tuesdays around 6pm you run 3:00 rounds"). A declined proposal teaches Echo
(suppression + threshold raise); a wrong adopted echo is revocable in one
gesture from the card it produces ("hold: stop doing this"). The system
explains itself *before* acting, in the sentence that asks permission.

## 5. Runtime model

Phone: an observer that folds the orchestrator's event stream into
per-pattern statistics (context keys: weekday band, hour band, place id,
figment id, parameter vector); a proposer that turns a stable cluster into a
Figment via the shared builders; the shared verify/sign/vault/deploy path.
Halo: unchanged — the fixed stage plus one new proposal card type. BLE:
unchanged envelopes plus the proposal card payload.

## 6. Backward-compat story

v1 templates are Echo's *vocabulary of things worth noticing*: the 15 lifted
Figments (shared `compat.lift`) seed the pattern space, so Echo can recognize
"this manual stopwatch usage matches round_timer-shaped behavior" from day
one. Every v1 behavior continues to work untouched; Echo only ever proposes
on top.

## 7. End-to-end trace: "3-minute rolls timer, 10-second pulse"

Nothing is authored. Week 1, Tuesday: user manually arms a stopwatch at the
gym, resets ~every 3:00, ten times; the observer logs each cycle. Week 2,
Tuesday: same shape; the cluster (place=gym, weekday=Tue, period≈180 s,
reset-by=double-tap) crosses threshold. Wednesday morning, quiet moment:
proposal card appears (wireframe above) — the proposer has already built and
verified a `ROLLING 3:00 → pulse 10 s → re-arm` Figment. User taps. Signed,
vaulted as "Tuesday rounds", context-armed. Next Tuesday at the gym the HUD
shows `ROUNDS READY — double-tap`; the user double-taps and lives inside the
behavior they never wrote.

## 8. The one test that proves the paradigm

**The two-Tuesdays test.** Feed the observer two weeks of synthetic usage
logs containing (a) the Tuesday round pattern with natural jitter (±20 s
periods, ±40 min start), (b) heavy unrelated noise, and (c) a
*nearly*-recurring decoy that appears once. Assert exactly one proposal is
produced, that its Figment verifies and semantically matches the pattern
(180 s ± tolerance, pulse, re-arm), and that the decoy and noise produce
none. Echo lives or dies on precision — a system that proposes wrongly even
occasionally is creepy and gets turned off — so the paradigm's proof is a
false-positive rate of zero on adversarial logs, not a capability demo.
