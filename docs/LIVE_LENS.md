# Live Lens — any phone's browser becomes the glasses

Open one URL. Grant the camera. You are looking through DreamLayer — before
the hardware exists, without installing anything.

```
your camera ──▶ your Brain (your LAN) ──▶ the real HUD, on your screen
```

## What is genuinely 1:1

The Live Lens is not a demo reel. Every layer in the loop is the production
system:

| Layer | What runs |
|---|---|
| Answers | The real Brain — `/dreamlayer/brain/ask`, with recall, tiers, and cloud escalation exactly as configured |
| Looks | **One unified pipeline** (`live.world_look`) shared with the phone app's `/dreamlayer/brain/look` — a tap here and a shutter there run the same code and return the same glass lines |
| Vision | The full World lens: the VLM-backed structured recognizer when a vision model is configured (a price tag comes back with its amount + currency), with the real classifier ladder (YOLO / moondream / CLIP / the pixel-reading heuristic) as its always-on rung |
| Plugins | Your installed connectors light up on a look — the Currency converter turns €20 into your home currency on the glass, Open Library rates the book spine — through the same capability-gated, sandboxed store path the glasses will use. A provider sees the extracted label/fields, **never the pixels** |
| Display budget | The canonical unit all four interpreters share — `MAX_LINES` (5) × `MAX_TEXT_LEN` (24 UTF-8 bytes), from `reality_compiler.v2.figment` — applied by one formatter (`live.panel_lines`) for every surface |
| Privacy posture | The veil toggle sends `no_cloud` on every ask — the same contract the glasses' incognito enforces. Under the Brain's egress shield (LAN-only / quiet hours) a look is **local-only**: the in-process classifier answers, plugins and any remote vision are not consulted, and no ledger trace is written. In every posture the frame is decoded in memory and never written to disk |
| Security | The same token gate, CSRF origin check, body-size caps (a frame over 4 MiB is refused before it is read), and brute-force lockout as the rest of the Brain's surface |

## What is honestly not 1:1 (the physical ceiling)

A phone is not a see-through waveguide on your face. No software closes these:

- **Optics** — Halo's display is monochrome, ~256 px, transparent, floating in
  your periphery at a fixed focal depth. A phone screen is opaque, full-color,
  and at arm's length. The pixels match; the *presence* cannot.
- **Framing** — the glasses camera looks where you look. A phone you point.
- **Ambience** — the real thing is passively there all day. A browser tab is
  foreground-only and hungry.

The Live Lens is the real *system* minus the physical glass. The page says so.

## Setup

1. Start the Brain reachable + secure (phone cameras require an https page):

   ```
   python -m dreamlayer.ai_brain.server --host 0.0.0.0 --tls
   ```

   `--tls` mints a self-signed certificate once into `~/.dreamlayer/tls/`
   (needs the `cryptography` package — `pip install 'dreamlayer[verify]'`) and
   serves https on `port + 1` (override with `--tls-port`). Without `--tls`
   everything still works over http except the camera, and the page explains
   exactly that.

2. On the Brain's machine, open the panel → **Connections → Live Lens →
   Get the link**, and scan the QR with the phone's camera.

3. The phone shows a one-time certificate warning — it is *your own Brain's*
   certificate (the standard LAN-appliance pattern). Accept it. The camera
   works from then on.

4. Tap the lens to **look**. Type (or speak) below to **ask**. Toggle the
   **veil** to force on-device-only answers.

## The trust model, plainly

- The link/QR **is** the credential — it carries the pairing token in the URL
  *fragment* (`#t=…`), which browsers never transmit, so it cannot appear in
  request lines or server logs. The panel hands it out local-only, exactly
  like the pairing code. Treat the QR like the pairing QR.
- The page itself is inert: it embeds no token, no matter who fetches it.
- Voice input, if you use it, goes through **your phone's** speech service
  (Apple/Google), not the Brain's on-device ASR — the mic button says so.
  Typing stays entirely on your LAN.
- If the Brain's LAN IP changes, the certificate is re-minted on the next
  `--tls` start so its names stay true.
