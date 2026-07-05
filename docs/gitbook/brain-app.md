# The desktop Brain app

The Brain (`host-python/src/dreamlayer/ai_brain/server/`) turns an always-on
Mac — a Mac mini is the reference — into your private knowledge node. It is
a single Python server: the index, the API, the scheduler, and a complete
control panel served as one self-contained HTML page (no build step, no
external requests). It runs anywhere Python runs; the macOS-specific readers
degrade to empty lists elsewhere.

```bash
pip install -e ./host-python
python -m dreamlayer.ai_brain.server --token <your-token>
# panel at http://<mac>:7777/  (token auto-injected when opened on the Mac itself)
```

*Every screenshot below is the actual panel, booted from this repository and
captured headlessly with a seeded index (three notes, two people, two
events).*

## What's connected — the system card

![Status](assets/panel/status.png)

Live status, polled every four seconds: Brain online, active model, cloud
state ("On - not configured" until you wire a key), incognito, whether a
phone has checked in, and the index size. Missing watched folders surface
here too.

## Morning brief and agenda

![Agenda](assets/panel/agenda.png)

The agenda merges hand-added events with macOS Calendar when sync is on
(**Seam:** the AppleScript reader; per-calendar picker, 14-day horizon,
15-minute background sync). "Brief me" composes the morning brief on demand;
the Ops card schedules it daily. Add and remove events inline.

The brief comes at two depths (`POST /dreamlayer/brief` with `depth`):

- **`short`** (default) — the one-glance version the glasses wake to: today's
  agenda plus what's new, turned into a warm couple of sentences.
- **`long`** — the extended brief, walked in sections: **Today** (agenda),
  **Due** (reminders), **Waiting on you** (open commitments the phone passes),
  **Messages** (each new text and email spelled out, not just counted), and
  **Yesterday** (kept moments the phone passes). The model writes a few
  skimmable paragraphs; the structured `sections` ride alongside. The last
  long brief is kept at `GET /dreamlayer/brief/long/latest`, and the phone's
  **Brief** screen composes it on demand and stores it to read anytime — even
  back offline.

## People and reminders

![People](assets/panel/people.png)

The dossier registry — everyone you have introduced, with notes and tags —
fed by hand, by Contacts sync (**seam**), or by the glasses' consented name
capture via the API. Reminders mirrors open Reminders.app to-dos with a
per-list picker (**seam**).

## Reach and devices — pairing and the switches

![Pairing](assets/panel/reach_pairing.png)

The Cloud and Incognito switches (identical semantics to the phone — see
[Privacy](privacy.md#the-three-brain-switches)), and **Pair a phone**: one
QR / one `dreamlayer:` code carrying the LAN URL and token. Local-only — the
pairing code is never served off-box.

## The cloud tier

![Cloud config](assets/panel/cloud.png)

Any OpenAI-compatible provider: base URL, key (stored, never re-displayed —
`GET /config` masks it to "set"), model name, and **Test connection** for a
one-word round trip. The cloud is only ever a fallback tier; every use is
counted and logged.

## Folders it reads

![Folders](assets/panel/folders.png)

The knowledge base is folders you choose: add by server-side browser (modal,
local-only) or pasted path, drop files straight onto the page into a chosen
folder, re-index on demand — plus auto-reindex whenever a watched folder's
modification signature changes (3-second poll). Advanced filters: semantic
search on/off, an extension whitelist (defaults cover text, markdown, csv,
json, code and more), a per-file size cap (2 MB default), and exclude globs.

![Folder browser](assets/panel/folder_browser.png)

## Ask your stuff

![Ask](assets/panel/ask.png)

The same `POST /dreamlayer/brain/ask` the glasses and phone use. Here it has
found the answer in a seeded note — tier `laptop`, source shown. With the
keyword model the answer is the best passage; with Ollama it is synthesized
prose.

## Model — keyword or Ollama

![Model](assets/panel/model.png)

Two modes, honestly framed:

- **Keyword** — zero setup, token-overlap retrieval. Works today, offline.
- **Ollama** — a local LLM upgrade: chat model (default `llama3.2`), vision
  model (`llama3.2-vision`), embedding model (`nomic-embed-text`) for
  semantic search. The status card probes Ollama live, lists which
  configured models are pulled, and offers a one-click **Pull** per missing
  model (local-only, drives Ollama's own API). "Read email and iMessage"
  folds Messages and Mail into the index (**seam:** the chat.db / .emlx
  readers).

## Privacy controls

![Privacy](assets/panel/privacy.png)

The pairing token (show / rotate — rotating de-pairs every device), the
lifetime **cloud egress counter**, backup (full restorable snapshot,
local-only) and restore, and selective erase: questions, activity, or
folders.

## Plugins — extend the Brain

![Plugins](assets/panel/plugins.png)

Community plugins this Brain runs, each validated on the way in (integrity
checksum, a static capability scan, a smoke load) — the shot above is a
real session where two registry plugins installed and a third was refused
because this machine could not grant the `mesh` capability it requires. The
card lists what this Brain can grant, links to the store at
[dreamlayer.app/plugins](https://dreamlayer.app/plugins.html), and takes a
pasted package for sideloading through the same gate. The full platform
story — the API, the marketplace, the live social layer at
api.dreamlayer.app — is in [The platform](platform.md).

## Messages, activity, health

![Activity](assets/panel/activity.png)

The unified activity feed: asks with their tier, folder changes, uploads,
sync runs, pairing, cloud egress — the audit trail of the whole node. The
Messages card (hidden until email is enabled) shows the recent feed with the
"summarize long emails" toggle.

![Ops](assets/panel/ops.png)

Health and schedule: version, index disk size, Ollama latency, uptime;
**quiet hours** (scheduled incognito), the **morning brief hour**, and
**retention days** for history pruning.

## The Mac appliance pieces

- **Menu-bar app** — `python -m dreamlayer.ai_brain.menubar` (rumps, macOS):
  a status dot (online / cloud-unconfigured / incognito / offline), Open
  panel, one-click Sync now (calendar + contacts + reminders), and an
  Incognito toggle. Its pure core (status mapping, plist generation) is
  tested cross-platform.
- **Launch at login** — `python -m dreamlayer.ai_brain.menubar
  --install-login` writes `~/Library/LaunchAgents/vision.dreamlayer.brain.plist`
  (RunAtLoad + KeepAlive).
- **Installer** — `laptop-companion/install-macos.sh` installs Ollama, pulls
  the three default models, seeds the config with `model: "ollama"`, and
  installs the launch agent in one run.
- **The companion agent** — `laptop-companion/dreamlayer_companion.py` is a
  separate, minimal, stdlib-only agent for *any* laptop: one endpoint
  (`GET /dreamlayer/context` — recent file names, hostname, battery), the
  same token header, and a refusal to serve on the LAN without a token. It
  feeds the Object Lens's "your laptop" panel; it is not the Brain.

## The full panel

![The whole panel](assets/panel/panel_full.png)
