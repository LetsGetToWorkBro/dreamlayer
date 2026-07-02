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
| confidence scores          | biometric identifiers |
