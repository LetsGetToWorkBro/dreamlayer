# Your privacy

Glasses that listen and remember are only acceptable if *you* hold the off
switch — physically, obviously, and everywhere at once. This chapter is the
plain-language contract.

## The one gesture that stops everything

**Hold the button.** The glasses go completely deaf and blind: no seeing, no
hearing, no remembering, no cards, nothing. A shield fills the display so
there is never any doubt about the state you are in. Hold again to come
back.

![The Privacy Veil](../assets/demo/catalog/features/veil/preview.webp)

This is not a "mute" that some features ignore. Every single capability in
the product checks this one gate before doing anything.

## Three levels of quiet

People confuse these in every product; DreamLayer keeps them distinct:

| You want | Use | What happens |
|---|---|---|
| "Stop interrupting me" | **Focus mode** — "Hey Juno, focus mode" | Cards, captions, and pop-ups pause for 25 minutes. It still remembers quietly. True emergencies still get through. |
| "Stop remembering for a while" | **Incognito** — "go incognito" | Nothing is kept, and the cloud is forced off, until you say "back on the record." |
| "Be off. Completely." | **The Veil** — hold the button | Deaf and blind. Nothing in, nothing out, nothing kept. |

## Where your data lives

Short version: **on your own devices, and it works that way by default.**

- Your memories, your people, your promises, and everything Juno has
  learned about you live on your phone and (if you added one) your Mac.
  The Mac reads your files *in place* on your own machine — nothing is
  uploaded to make search work.
- The **cloud switch** exists for one thing: rare, hard, general-knowledge
  questions that nothing in your home can answer. When it is off, the
  product simply says "nothing local matches" instead of reaching out.
- Even when cloud is **on**, your personal things — files, faces, people,
  memories, messages — are never what gets sent. And every single time
  anything does go out, it is counted and listed in plain sight on the Mac
  panel, so "how often does this thing phone home" has an exact, visible
  answer at all times.

![The panel's privacy controls: the egress counter, backup, erase](../assets/panel/privacy.png)

## People — the hard line

- **There is no giant face database to search.** Nothing is ever looked up
  outside your own hardware — no public database, no cloud face search, by
  design. Out of the box it recognizes nobody at all: the face model is not
  even installed. Turn it on and it recognizes the people who were introduced
  to you; turn **auto-enrol** on as well and it also keeps a nameless record
  of a face nobody introduced, so it can tell you you have seen them before.
  That second switch is the one to think hard about — see "What was
  deliberately not built" below.
- **Names come only from introductions.** When someone says "Hi, I'm Maya"
  — or you say "meet my colleague Sarah" — the name is kept and a card
  says so plainly ("KEPT - on your device"). Only a real introduction ever
  matches: ambient chatter, an overheard name, a bystander — none of it
  qualifies. Erase it from the Memories screen; the Veil closes the ear
  entirely. (Prefer the old ask-first flow? The offer-and-confirm mode
  still exists as a setting.)
- **No recordings.** DreamLayer keeps meaning — "Maya mentioned the lease" —
  never audio or video of anyone.

## Everyday controls worth knowing

- **"Forget that."** *Designed, not built.* The intent is a scoped undo of the
  last capture. What exists today is the all-or-nothing erase in Settings —
  there is no command that removes just the last thing.
- **Private zones.** *Designed, not built.* The intent is to mark a place
  never-record and have it honoured automatically. There is no way to mark one
  yet.
- **Nothing sends silently.** If you use it to reply to a message, you see
  the exact message and approve it first — the product physically cannot
  send without that approval.
- **Quiet hours.** Set a nightly window where the cloud is off on a
  schedule.
- **Erase and take-out.** The Mac panel can erase your history selectively,
  and can download a complete backup of everything it knows — your data is
  yours to take.

All the switches live together in the phone's Settings:

![Privacy settings on the phone](../assets/phone/settings.png)

## What was deliberately not built

No voice cloning. No covert recording modes. These are not features waiting
behind a setting — they were designed out of the product on purpose.

Face recognition used to be on that list. It is not any more. It ships as an
opt-in capability: the face model is in no install profile, so you have to add
it deliberately; recognition is off by default; and nothing runs until you
accept a consent whose exact wording is recorded — reword it and it has to be
accepted again. Beyond that sits **auto-enrol**, a further switch, also off by
default. With it off, a face that matches nobody you introduced is discarded
the instant it is compared — not stored, not counted, not logged. With it on,
that face is kept instead, so it is recognised the next time you see it, and
that includes people who never agreed and cannot agree here: the consent is
yours, taken on their behalf. We would rather say that plainly than keep a
promise the build no longer keeps.

What stays true either way: only the face you are actually looking at is ever
turned into a template — one per frame, and only if it is large enough in
view, so someone in the background is not — a stored face nobody named is
never given an invented name, nothing is ever looked up outside your own
hardware, unnamed faces age out on your retention window unless you name them,
the Privacy Veil stops the whole path, and erasing everything erases them.
