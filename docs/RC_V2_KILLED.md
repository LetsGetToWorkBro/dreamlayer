# Reality Compiler v2 — Phase 2: Obituaries

Eight concepts entered (`RC_V2_IDEAS.md`). Scored against the constraint
envelope (safety-by-construction, offline authoring, backward compat,
signing/hot-swap) and the taste bar ("wait, do it again" — not "a nicer
template picker"). Five die here. Survivors: **Rehearsal**, **Loom**, **Echo**.

---

## Séance (conversational compiler) — killed

What was compelling: answering with living previews instead of sentences is
genuinely right for glasses, and the tilt-to-choose disambiguation loop is the
best failure-teachability story of the eight — the system never has to
*explain* a misunderstanding, it just shows both readings. What was fatal:
Séance is v1's plain-English input wearing better clothes. Its ceiling is
still "what the utterance→parameter mapper can hear," its offline story
degrades to exactly v1's pattern-matcher, and Rule 4 of the brief ("NL to a
model that emits behavior is not the leap") applies in spirit even though
Séance never emits code. A smart friend watching the demo says "nice
clarifying questions" — that's a template picker with manners. To live, Séance
would need the *previews themselves* to be manipulable objects rather than
menu options — at which point it has become Rehearsal's playback loop and
should be shipped as that: the disambiguation-by-preview idea survives inside
Rehearsal's correction pass.

## Clockface (mechanical instruments) — killed

What was compelling: mechanical semantics give boundedness *by metaphor* —
springs run down, drums hold finite pins — which is the most elegant restating
of the totality constraint in the whole field, and glanceability is inherited
from three centuries of horology. What was fatal: the metaphor stops
composing exactly where users start wanting v2 behaviors. A timer is a
beautiful mainspring; "show the coach's cue *and* pause my intervals *and*
resume after" is a gear train only a watchmaker could love, and every new
domain (subtitles, teleprompter, coach bytes) demands a new invented mechanism
with its own learning curve. The paradigm's charm is also its cap — it trades
v1's 15 templates for ~8 movements. To live, Clockface would need a
composition story that doesn't require users to reason about escapements;
its winding gesture (head-roll to set a duration) is stolen gratefully as an
optional Rehearsal input.

## Grimoire (signed charm deck) — killed

What was compelling: the social layer. Behaviors as signed, provenance-carrying,
bendable charms is the correct *distribution* model for this ecosystem, and
"bend three sliders" is the fastest time-to-deployed-behavior of all eight.
What was fatal: it isn't an authoring paradigm — it's a marketplace for the
output of one. Someone must still author the first charm of every kind, so
Grimoire presupposes the very system we're inventing; day one the deck is
empty, and the founder's north star ("*I* programmed my glasses") becomes "I
downloaded a nicer preset." It also drags in a trust surface (imported charms)
that the constraint envelope handles but this PR shouldn't lead with. To
live, Grimoire needs a v2 that fills the deck — which is precisely the plan:
Figments are already signed, exportable, and provenance-stamped, so Grimoire
is the natural *follow-up release* on top of Rehearsal, not a competitor to it.

## Semaphore (gestural composition language) — killed

What was compelling: the only paradigm needing neither phone nor voice —
composable silently with busy hands, and the regular grammar means every
phrase is either compilable or rejected at the exact offending gesture. What
was fatal: it's a programming language you wear. The vocabulary must be
memorized before anything can be authored; error rates on IMU gestures turn
"stretch time to 3:00" into a comedy of nods; and the taste bar inverts — the
user *constantly* feels like they're programming, in the least forgiving
editor imaginable. The founder's north star fails in the first minute of use.
To live, Semaphore would need gestures so few and so natural they stop being
a vocabulary — which is what Rehearsal's beats already are (tap, speak, done):
Rehearsal is Semaphore with the grammar deleted and speech carrying the load.

## Tidepool (reactive pools) — killed

What was compelling: continuous sensor→display bindings are stated *directly*
instead of encoded in control flow, structural acyclicity makes termination
free, and the six-pool cap is honest HUD-scale minimalism. What was fatal:
it's a desktop mind transplanted — the spreadsheet is the most successful
end-user programming model in history *on a screen you stare at for hours*,
and none of its virtues survive the transplant: pools are abstract state the
user must name and hold in their head, exactly what a glanceable HUD promises
to remove. The rolls-timer example needs a subtraction and a reset rule; the
user is doing algebra to get a countdown. To live, Tidepool would have to
hide the pools behind domain nouns ("time left in round") — at which point
it's a template library with cells. Its one enduring idea — acyclic-by-
construction reactive updates — survives as the *internal* form of the
Figment tick rule, where it belongs: in the compiler, not in the user's face.

---

**Survivors → Phase 3:** `docs/rc_v2/rehearsal.md`, `docs/rc_v2/loom.md`,
`docs/rc_v2/echo.md`.
