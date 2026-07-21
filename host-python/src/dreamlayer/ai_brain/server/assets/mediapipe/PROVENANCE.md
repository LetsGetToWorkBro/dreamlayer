# Vendored on-device detector — provenance

These files are third-party artifacts, vendored **same-origin** so the Live Lens
in-browser object detector loads with **zero external fetch** (the live page's CSP
forbids off-origin, so camera frames never leave the phone for the on-device
pass). They are served read-only + public by `_get_live_asset`
(`/dreamlayer/live/assets/…`).

Pinned so a change to any committed binary is auditable (recompute with
`sha256sum` and compare):

| File | sha256 | Source |
|------|--------|--------|
| `vision_bundle.mjs` | `e77f281f9619150d937023c355bae170e9120e3b9e43f1e23a2a7bee07197669` | `@mediapipe/tasks-vision@0.10.14` (npm / jsDelivr) |
| `wasm/vision_wasm_internal.js` | `9440cf0cc0cea21800e31581ec32aeedcc5fbf9df4509796bbc7d3f99e52ab9c` | `@mediapipe/tasks-vision@0.10.14` (npm / jsDelivr) |
| `wasm/vision_wasm_internal.wasm` | `f82a8e6c05e08a44cc9f9e7ec5f845935bcbb1b1500ebe8c2f4812fb4e2917dc` | `@mediapipe/tasks-vision@0.10.14` (npm / jsDelivr) |
| `models/efficientdet_lite0.tflite` | `0720bf247bd76e6594ea28fa9c6f7c5242be774818997dbbeffc4da460c723bb` | MediaPipe EfficientDet-Lite0, **int8**, `object_detector/efficientdet_lite0/int8/latest` (storage.googleapis.com/mediapipe-models) |
| `models/gesture_recognizer.task` | `97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482` | MediaPipe Gesture Recognizer, **float16**, `gesture_recognizer/gesture_recognizer/float16/1` (storage.googleapis.com/mediapipe-models) |

## Notes
- `vision_wasm_internal.*` is the **SIMD** build. A browser without WASM SIMD
  will 404 the (deliberately un-vendored) no-SIMD variant; the page then degrades
  to the Brain ambient loop — recognition still works.
- `efficientdet_lite0` detects the 80 **COCO** object classes. It is an object
  detector, not a face/identity model: it can only emit generic class names,
  never a person's identity. The client additionally never boxes or labels the
  `person` class.
- `gesture_recognizer.task` bundles a hand-landmark model + a small canned-
  gesture classifier (Open_Palm, Closed_Fist, Pointing_Up, Thumb_Up/Down,
  Victory, ILoveYou). It reads **hand geometry only** — 21 landmarks and a
  gesture enum, never a face, never identity — and runs entirely in-browser on
  the phone's `<video>`, so nothing about the hand ever leaves the device. It
  drives HUD navigation (look / dismiss / pause), not recognition, so it never
  reaches the server look path or `person_guard`.
- Licenses: MediaPipe Tasks (Apache-2.0), EfficientDet-Lite0 model (Apache-2.0),
  Gesture Recognizer model (Apache-2.0). These are static assets, not a Python
  dependency, so they are not in `models.lock` (which pins the Brain's own
  Python-loaded ML models).

## Refresh
To update to a new upstream version, re-download from the sources above, replace
the files, recompute the hashes here, and re-run the live-lens Playwright E2E
(it verifies the detector loads under the page CSP).
