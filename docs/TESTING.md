# Testing DreamLayer — the Mac Brain + the phone app

This is the hands-on guide for trying DreamLayer end to end: the **Brain**
(the software that runs on your Mac / Mac mini) and the **phone app** that
pairs to it. Neither needs the glasses to test — both run and demo on their
own.

> **TL;DR**
> - **Brain:** `cd host-python && pip install -e . && python -m dreamlayer.ai_brain.server --token rune-birch` → open the printed URL.
> - **Phone:** `cd phone-app && npm install && npx expo start` → scan the QR with Expo Go.
> - **Pair them:** Brain panel → *Pair a phone* → copy code → phone *Brain* tab → *Pair a device* → paste.

---

## Part 1 — The Mac Brain

The Brain is a small local server: a control panel in your browser + the API
the phone calls. It runs on Python's standard library alone, so **keyword
search works with zero extra setup**; adding [Ollama](OLLAMA_SETUP.md) later
turns on written answers and vision.

### 1a. Quickest path (any Mac, ~2 min)

Requires Python 3.11+ (`python3 --version`). A venv is recommended.

```bash
git clone <this repo> dreamlayer
cd dreamlayer
python3 -m venv .venv && source .venv/bin/activate
pip install -e ./host-python           # installs the `dreamlayer` package
python -m dreamlayer.ai_brain.server --token rune-birch
```

(You can run that last line from anywhere once installed — the old `cd
host-python` requirement is gone.)

You'll see:

```
DreamLayer Brain — control panel at http://192.168.x.x:7777/
  watching 0 folder(s), 0 files indexed
  token: set   model: keyword
  Ctrl-C to stop.
```

Open that URL in Safari or Chrome. From the Mac itself the panel is
pre-authorised; from another device, you'll be asked for the token
(`rune-birch` above — pick your own).

**Try it:**
1. **Add a folder** — point it at a folder with a few `.md` / `.txt` / `.pdf`
   files (e.g. `~/Documents/DreamLayer`). Watch the file count climb.
2. **Drag & drop** a text file onto the drop zone — it's added and indexed live.
3. **Ask your stuff** — "what's in my notes about the lease?" The answer cites
   the file it came from.
4. **Flip Cloud / Incognito** — the top chips update instantly; Incognito
   forces Cloud off and greys it out.
5. **History** shows every question with the tier that answered it.

### 1b. Always-on install (Mac mini)

For the real setup — Ollama models + launch-at-login so the Brain is always
running:

```bash
cd dreamlayer/laptop-companion
./install-macos.sh --token rune-birch
```

This installs Ollama, pulls the default models, writes
`~/.dreamlayer/brain_config.json`, and loads a LaunchAgent. See
[OLLAMA_SETUP.md](OLLAMA_SETUP.md) to tune which models it uses.

### 1c. See it work without a folder of your own

A scripted end-to-end run (boots the real server, seeds a couple of files,
asks questions over HTTP exactly like the phone does):

```bash
cd dreamlayer
python scripts/run_demo_brain_app.py
```

### Brain — options & troubleshooting

| Flag | Default | Meaning |
|---|---|---|
| `--token` | *(none)* | pairing secret the phone must send. Set one. |
| `--dir` | `~/.dreamlayer` | where config + history live |
| `--host` | `0.0.0.0` | listen address (LAN-reachable) |
| `--port` | `7777` | panel + API port |

- **"Can't reach it from my phone"** — phone and Mac must be on the same
  Wi-Fi. Use the `192.168.x.x` URL the server prints, not `127.0.0.1`.
- **"Unauthorised" on another device** — you need the token; it's only
  auto-filled when the panel is opened on the Mac itself.
- **Nothing indexes** — check the folder path is right and readable; the file
  count in the top chips is the source of truth.

---

## Part 2 — The phone app

Expo/React Native. You run it with Expo Go on your own phone — no Xcode or
Android Studio needed for a test drive.

### 2a. Run it

Requires Node 18+.

```bash
cd dreamlayer/phone-app
npm install
npx expo start
```

A QR code appears in the terminal. On your phone:
- **iOS:** install **Expo Go** from the App Store, open the Camera, point it at
  the QR, tap the banner.
- **Android:** install **Expo Go**, open it, tap *Scan QR code*.

The app loads over your local network. Or press `w` in the terminal to open it
in a browser, `i` for the iOS simulator, `a` for an Android emulator if you
have them.

### 2b. What to test

The app opens on the **Brain** tab — the hub:

1. **Brain modes** — you start as *phone is the brain*. It works fully offline;
   this is the honest default.
2. **Cloud switch** — its own toggle with a plain-language note on what extra
   reach it buys. Flip it; the header line updates.
3. **Incognito** — forces cloud off and pauses capture; the Cloud switch greys
   out to show it's held.
4. **Ask your brain** — type a question. Unpaired, it answers from DreamLayer's
   own memory; paired to a Mac mini (below), it searches your files.
5. **Now tab** — the live Halo mirror, status pill, and quick actions.
6. **Memories tab** — grouped by day, kind-colored; *Settings → Erase all
   memories* clears them to see the empty state.
7. **Rehearsal / Confluence** — the Reality Compiler and the entangled-sky
   surfaces.

Every button springs on press; every screen and card rises in on open — that's
the design system (see [phone-app/DESIGN.md](../phone-app/DESIGN.md)).

### 2c. Pair the phone to the Brain (the whole point)

1. On the **Mac Brain panel** → *Connections* → **Pair a phone** → **Copy code**
   (a `dreamlayer:…` string).
2. In the **phone app** → **Brain** tab → **＋ Pair a device** → paste the code →
   **Connect**.
3. The phone flips to *Mac mini is the brain*, and **Ask your brain** now
   searches your indexed files. One code also carries the glasses' id when you
   have them.

> The pairing code is a compact base64 of `{brain_url, token, glasses_id}`. The
> phone decodes it with the exact same codec the Brain encodes with
> (`phone-app/src/services/pairing.ts` ↔ `host-python/.../pairing.py`), verified
> byte-for-byte in the test suite.

### Phone — troubleshooting

- **QR won't load** — phone and computer must share a network; try `npx expo
  start --tunnel` if you're on a locked-down Wi-Fi.
- **"Couldn't reach your Brain"** after pairing — the Mac Brain must be awake
  and on the same LAN; re-open the panel to confirm it's serving.
- **Bluetooth / glasses** — Web Bluetooth isn't available on iOS, so the shipping
  app talks to the Halo through a thin native module; in Expo Go the glasses
  pairing is simulated (the rest is real).

---

## Running the automated tests

```bash
# Brain + all host logic (Python) — install with the dev extra first:
#   pip install -e ./host-python[dev]   (pytest, pytest-asyncio, lupa)
cd host-python && python -m pytest -q

# Phone app tests + type check (needs deps installed)
cd phone-app && npm install && npm test && npx tsc --noEmit
```

The host suite (3,022 tests) covers the Brain server, the router/switches, the
pairing codec, and every lens.
