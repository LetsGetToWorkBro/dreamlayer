# DreamLayer laptop companion

The small program you run **on your laptop** so the Object Lens can show your
recent files and battery when you look at it through the glasses.

It reads that from your OS and serves it on your local network on the
DreamLayer companion contract:

```
GET  http://<this-laptop>:7777/dreamlayer/context
header  X-DreamLayer-Token: <shared pairing token>
200  {"recent_files": [...], "battery": 82, "hostname": "studio-mbp"}
```

Everything stays on your LAN — the phone (the DreamLayer hub) fetches it
directly. Nothing goes to any cloud, and only your paired phone (holding the
token) can read it. Stdlib Python only — no dependencies.

## Run it

```bash
python3 dreamlayer_companion.py --token rune-birch
```

Pick any token; pair the phone with the **same** token. It prints the URL to
point the phone at. Leave it running.

- `--token`   the pairing secret (or set `DREAMLAYER_TOKEN`). Required to
  serve on the LAN — it refuses to expose your files without one.
- `--host`    bind address; `0.0.0.0` (default) is reachable from your phone
  on the same network. Use `127.0.0.1` to keep it to this machine only.
- `--port`    default `7777`.

What it reads: the most recently modified files in your `Desktop`,
`Documents`, and `Downloads` (basenames only — never contents), plus battery
level. That's the whole surface; edit `build_context()` to add or remove
what you expose.

## Leave it running (launch at login)

**macOS** — `~/Library/LaunchAgents/vision.dreamlayer.companion.plist`:

```xml
<plist version="1.0"><dict>
  <key>Label</key><string>vision.dreamlayer.companion</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/full/path/to/dreamlayer_companion.py</string>
    <string>--token</string><string>rune-birch</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
```
`launchctl load ~/Library/LaunchAgents/vision.dreamlayer.companion.plist`

**Linux** — `~/.config/systemd/user/dreamlayer-companion.service`:

```ini
[Unit]
Description=DreamLayer laptop companion
[Service]
ExecStart=/usr/bin/python3 /full/path/to/dreamlayer_companion.py --token rune-birch
Restart=on-failure
[Install]
WantedBy=default.target
```
`systemctl --user enable --now dreamlayer-companion`

**Windows** — Task Scheduler → Create Task → Trigger: *At log on* → Action:
`python`, arguments `C:\path\dreamlayer_companion.py --token rune-birch`.

## The bigger Brain (files, model, history, control panel)

This companion serves *live* context (recent files, battery). The **DreamLayer
Brain** is the larger app that turns your Mac mini into a private knowledge +
AI node — index chosen folders, drag-drop files in, pick your model (Ollama),
ask questions grounded in your own files, and keep a query history, all from a
web control panel:

One-command Mac mini setup (Ollama + models + launch-at-login):

```bash
./install-macos.sh --token rune-birch
# then open the control panel at http://<mac-mini>:7777/
```

Or run it directly: `python -m dreamlayer.ai_brain.server --token rune-birch`.
It also reads iMessage + Mail (when enabled) and can draft→approve→send.
See [`docs/AI_BRAIN.md`](../docs/AI_BRAIN.md) and
[`docs/OLLAMA_SETUP.md`](../docs/OLLAMA_SETUP.md). The phone connects with
`connect_brain(router, url, token)`.

## How it fits DreamLayer

The phone side is already built (`object_lens.integrations.laptop_data_source`
wrapped in a `PolledSource`, feeding `LaptopProvider`). This agent is the
other end of that contract. Anything else that answers those three lines — a
different language, a soil sensor, an OBD dongle — plugs into the exact same
phone-side machinery; only the reader changes.

## Security

- Never serves on the LAN without a token (returns exit code 2 and refuses).
- Wrong/absent token → `401`.
- Serves basenames and a battery number — never file contents. Widen only
  what you choose in `build_context()`.
