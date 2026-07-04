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
