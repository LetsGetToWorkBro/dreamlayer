# DreamLayer — Privacy Model

## Philosophy
DreamLayer is a *trusted* memory layer, not a surveillance product. Privacy is a
first-class, visible feature.

## Capture model
- Capture is event/activity driven, never an always-on raw recorder by default.
- Captured signal is converted to **structured memory** (entities, places,
  commitments, summaries) as early as possible.
- Raw media is, by default, **not retained** after extraction.

## Paused state
- Long-press (or `privacy_pause` command) instantly enters `paused`.
- A dedicated **PrivacyVeilCard** makes the state unmistakable in-eye.
- While paused, capture helpers **bypass** all camera/mic triggers (enforced in
  `capture/scheduler.lua` and tested in `test_privacy.py`).

## People
- **Name capture is automatic — and bounded.** When someone introduces
  themselves out loud ("Hi, I'm Maya"), the name — and the face in front of
  you — is kept as your own local contact the moment it is given, and the
  conversation ledger grows a dossier (last met, topics, their last line,
  your notes) from there. The KeptCard states the saved fact in-eye.
- **The boundary is the closed grammar.** Only a spoken self-introduction
  triggers capture. Ambient chatter, overheard third-party mentions, and
  people who never addressed you produce nothing — bystanders are never
  enrolled. There is no stranger lookup, no public database, no network.
- **The veil wins.** While the Privacy Veil is down the ear is closed: no
  name is kept or offered, no face is grabbed. "Forget that" erases a kept
  introduction; the consent flow (offer + deliberate confirm) remains
  available via `auto_keep_introductions=False`.

## Retention guidance
- Store structured summaries, not raw audio/video.
- Per-session capture enable/disable persisted via `system/settings.lua`.
- Deletion hooks exist (`memory/privacy.py: purge_memory`, `purge_all`) for future
  memory-management UI.

## What is / is not stored
| Stored (structured)        | Not stored by default |
|----------------------------|-----------------------|
| memory summaries           | raw video frames |
| entities, places           | raw audio waveforms |
| commitments, timestamps    | continuous transcripts |
| confidence scores          | raw media of any kind |
| kept contacts' face embeddings (local only) | biometric identifiers of strangers |

## Retention lifecycle
"Structured, never raw" is also a *lifecycle* claim (`memory/retention.py`):
the hot ring (24 h of the day's events) is purged after the nightly REM run;
warm memories expire after 90 days unless the dreamer kept voting for them
(REM promotion) or they're pinned; only cold **entities** — people you were
introduced to, places, promises, taught facts — persist indefinitely, and
each has an explicit "forget that" path. The honest answer to *"what does
the device retain about last March?"* is: entity summaries, nothing else.

## Bystander biometrics — the legal reality *(flagged for counsel review)*

The Veil protects the **wearer**; biometric-privacy law protects **everyone
else**, and a face embedding is the regulated artifact even though no image
is stored. This section states the design's legal theory so it can be
reviewed by an actual privacy lawyer — the repo is public now, and that
review is still a tracked owner action (docs/AUDIT_ACTIONS.md).

- **The laws that bite.** Texas CUBI (Tex. Bus. & Com. Code §503.001)
  requires informed consent from the *individual whose* biometric identifier
  is captured for a commercial purpose — the wearer's consent is not the
  subject's — and the Texas AG has been the most aggressive enforcer in the
  country. Illinois BIPA adds a private right of action (statutory damages
  per capture). GDPR art. 9 treats face embeddings as special-category data.
- **The design's legal theory.** Social Lens computes embeddings only for
  people who *spoke their name to the wearer* (the closed introduction
  grammar) — a deliberate, verbal, in-person act directed at the device's
  owner. DreamLayer treats that as the documented consent event: it is
  timestamped in the kept contact, revocable at any time ("forget that"
  erases the embedding, not just the name), and never happens while the
  Veil is down. Bystanders who never addressed the wearer are structurally
  incapable of enrollment; stranger lookup is a refused capability, not a
  setting.
- **The honest caveats.** (1) An introduction is strong *evidence* of
  consent to be remembered; whether it satisfies each statute's *informed*
  consent standard is exactly the counsel question. (2) Matching requires
  embedding the face *in view* before knowing whether it's a kept contact —
  the transient probe embedding is computed and discarded, never stored for
  strangers; counsel should confirm transient computation is defensible per
  jurisdiction. (3) Until that review lands, deployments in two-party-consent
  or BIPA-class jurisdictions should treat face matching as an explicit
  per-jurisdiction opt-in, off by default.
- **What this section is not.** Legal advice, or a substitute for the
  review. It exists so the first public conversation about "glasses that
  scan faces" happens on the project's terms, with the architecture's
  genuine consent-first design stated precisely.
