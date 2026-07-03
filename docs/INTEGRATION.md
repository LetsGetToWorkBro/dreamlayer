# DreamLayer — integration & device seams

The map for wiring DreamLayer onto real hardware: the full **Brain HTTP API**,
the **hub (orchestrator)** capabilities the phone drives, and the **seams** —
the handful of places where a real microphone, radio, or OS reader plugs in.
Everything not listed as a seam is built and tested; the seams are where the
device world meets the code.

```
  Halo glasses  ──BLE──▶  Phone / hub (orchestrator)  ──HTTP──▶  Mac mini Brain
   render + mic            anticipation · voice · polling         API below
        ▲ seam: BLE + ASR         ▲ seam: http_get                ▲ seams: macOS readers
```

---

## 1. Brain HTTP API

Base URL: `http://<mac-mini>:7777`. Every `/dreamlayer/*` call needs the pairing
token header **`X-DreamLayer-Token: <token>`** (the panel injects it on
localhost). Some are additionally **local-only** (403 from off-box) because
they expose the filesystem, secrets, or hand out pairing material.

### Read (GET)

| Endpoint | Auth | Returns |
|---|---|---|
| `/` | — | the control panel (HTML) |
| `/dreamlayer/status` | token | live state: model, cloud, incognito, phone-last-seen, index, missing folders, cloud egress count |
| `/dreamlayer/config` | token | full config (token + cloud key masked) + index stats |
| `/dreamlayer/health` | token | version, index disk size, Ollama latency, uptime |
| `/dreamlayer/history` | token | unified activity feed (asks + folder/upload/cloud/pair events) |
| `/dreamlayer/messages/recent` | token | recent Messages + Mail for the glasses **(seam: macOS reader)** |
| `/dreamlayer/calendar` | token | upcoming events **(seam: agenda.json / EventKit)** |
| `/dreamlayer/model/status` | token | Ollama reachability + which configured models are pulled |
| `/dreamlayer/people` | token | the dossier registry — everyone you've introduced `{name, note, tags, ts}` |
| `/dreamlayer/calendars` | token | macOS calendars available to sync + current settings `{items[], sync, selected[], last_sync}` **(seam: AppleScript)** |
| `/dreamlayer/contacts` | token | Contacts sync state `{sync, last_sync, count}` |
| `/dreamlayer/reminders` | token | open reminders + lists + sync state `{items[], lists[], sync, selected[]}` **(seam: AppleScript)** |
| `/dreamlayer/rewind` | token | today merged into hour blocks — activity + messages + events `{blocks[], count}` |
| `/dreamlayer/browse?path=` | **local** | subfolders of a directory (the folder picker) |
| `/dreamlayer/token` | **local** | the current pairing token (for the panel) |
| `/dreamlayer/pair` | **local** | a `dreamlayer:` pairing code carrying the **LAN** brain_url + token |
| `/dreamlayer/backup` | **local** | full restorable snapshot (config incl. secrets, history, activity, agenda) |

### Write (POST, JSON body)

| Endpoint | Auth | Body → effect |
|---|---|---|
| `/dreamlayer/brain/ask` | token | `{query}` → `Answer` (device → Mac mini → cloud, egress logged) |
| `/dreamlayer/brain/explain` | token | `{label, image?, want?}` → object `Answer` |
| `/dreamlayer/brief` | token | `{agenda?, since?}` → morning brief `{text, bullets, missed}` |
| `/dreamlayer/replies` | token | `{text}` → `{replies: [3 short replies]}` |
| `/dreamlayer/folders` | token | `{action: add\|remove, path}` → reindex |
| `/dreamlayer/calendar` | token | `{title, ts, place}` adds an event; `{remove:true, title, ts}` removes → `{items}` |
| `/dreamlayer/people` | token | `{name, note?, tags?}` upserts a person; `{remove:true, name}` removes → `{items}` |
| `/dreamlayer/calendar/sync` | token | `{}` → pull macOS Calendar.app into the agenda now `{items, synced}` |
| `/dreamlayer/contacts/sync` | token | `{}` → pull Contacts.app into the People registry `{items, synced}` |
| `/dreamlayer/reminders/sync` | token | `{}` → pull open Reminders.app to-dos `{items, synced}` |
| `/dreamlayer/upload?folder=&name=` | token | raw file body → dropped into a watched folder |
| `/dreamlayer/config` | token | partial config patch (model, cloud, filters, quiet hours, …) |
| `/dreamlayer/reindex` | token | `{}` → rebuild the index now |
| `/dreamlayer/model/pull` | **local** | `{model}` → one-click `ollama pull` via Ollama's HTTP API `{ok, status, model}` |
| `/dreamlayer/message/draft` | token | `{channel,to,subject?,text}` → the exact send script (preview) |
| `/dreamlayer/message/send` | **local** | `{…, approved:true}` → sends **(seam: osascript)**; unapproved is refused |
| `/dreamlayer/cloud/test` | **local** | `{}` → `{ok, reply\|error}` round-trip to the cloud provider |
| `/dreamlayer/token/rotate` | **local** | `{}` → new token (every paired device must re-pair) |
| `/dreamlayer/clear` | **local** | `{what: history\|activity\|folders\|all}` |
| `/dreamlayer/restore` | **local** | a backup snapshot → writes config + logs + agenda back |

---

## 2. Hub (orchestrator) capabilities

These run on the phone hub and drive the glasses. They're pure/tested; the
device seams are the callables they accept.

- **Anticipation** — `orchestrator.anticipate_tick(Context)` ties place + time +
  person into ranked, de-duped, veil-gated cards
  (`orchestrator/anticipation.py`: `Context`, `Event`, `Anchor`, `Commitment`).
  Feed it live context each tick.
- **Oracle (wake + voice)** — `orchestrator.hear(text)` is the wake pipeline:
  "Hey Oracle …" wakes the assistant and runs the command; while it's listening
  (a ~20s session) follow-ups need no wake word (continuous-conversation mode);
  otherwise the line is ignored. `activate(source)` wakes it hands-free by
  **tap / gaze / raise** (`set_wake_source` toggles each). On wake it shows a
  **Listening** ring plus an earcon + haptic tick (`set_wake_feedback` toggles
  visual/audio/haptic). Underneath, `handle_voice(text)` routes an intent
  (recall/locate/reply/brief/missed/ask); `voice.py: detect_wake / parse_intent`
  is the grammar. **Seam:** the mic + ASR that produces `text`, the tap/gaze/
  raise signals, and the runtime that plays the earcon / buzzes the haptic.
- **Message pop-ups** — `orchestrator.poll_messages_once(http_get)` /
  `start_message_polling()` fetch the Brain feed and flash new incoming
  messages (idempotent, veil-gated, per-channel toggles). **Seam:** `http_get`
  defaults to `urllib`; swap for your platform's client if needed.
- **Look at someone → dossier** — `orchestrator.look_at_person(frame)` matches
  the face against *your own* contacts (`social_lens`, on-device, never a
  stranger lookup) and follows the identity card with the conversation dossier
  when the ledger knows them. Contacts sync fills `self.social`. **Seam:** the
  camera frame + the face-embedding model (MobileFaceNet/NPU).
- **Spoken commitments** — `ingest_caption` runs `conversation.parse_commitment`
  on your own lines, so "I'll send you the lease by Friday" becomes a tracked
  commitment (`db.add_commitment`, attributed to whoever you're talking to) that
  feeds the dossier, anticipation, and quest/drift. Veil-gated.
- **Conversation ledger** — `orchestrator/conversation.py: ConversationLedger`
  turns transcribed speech into four things:
  `ingest_caption(text, speaker)` records a line and flashes it as a live
  caption (veil-gated; `set_captions(False)` keeps the ledger but hides the
  HUD); `recall_conversation(topic, person=None)` answers "what did they say
  about X" (user-initiated, not veil-gated); `rewind_day()` returns an
  hour-grouped digest of today; `greet(person)` surfaces a **person dossier**
  card (last seen, recurring topics, most recent line) for anyone the ledger
  knows. Cards: `hud/cards.py: spoken_caption`, `person_dossier`. **Seam:** the
  same mic + ASR that feeds voice, plus optional speaker diarization for the
  `speaker` label.
- **Brief at wake** — `orchestrator.wake(http_get)` fetches the brief the
  Brain's scheduler last delivered (`GET /dreamlayer/brief/latest`) and flashes
  it as a `MorningBriefCard` the moment the Halo goes on. Veil-gated; silent
  with no brief or no paired Mac mini. **Seam:** the glasses' wear/wake signal.
- **Scrubbable rewind** — `orchestrator.rewind_scrub()` loads today's moments
  into the time-scrub engine and flashes the latest node on the glasses;
  `scrub("back"|"forward")` walks the day and re-renders (the phone Rewind shows
  the same day as a list). **Seam:** the twist/tap gesture that drives `scrub`.
- **Focus mode** — `orchestrator.set_focus(minutes)` / `clear_focus()` /
  `focus_active()` turns the *interruptions* down (anticipation cards, live
  captions, message pop-ups) for a stretch while **capture keeps running** —
  distinct from Incognito, which pauses capture. The gates live in
  `anticipate_tick`, `ingest_caption`, and `poll_messages`.
- **Proactive-cue picker** — `orchestrator.set_cue(kind, on)` /
  `cue_kinds()` toggle which anticipatory kinds surface (`event` / `person` /
  `place`); the engine (`AnticipationEngine.set_kind`) drops muted kinds before
  the cooldown pass.
- **Brain routing** — `BrainRouter` (device → Mac mini → cloud) with the three
  switches (`connect_mac_mini` / `use_cloud` / `set_incognito`).

---

## 3. Device & infra seams — the wiring checklist

Everything above is code; here is the short list of what a real build supplies.

| Seam | Where it plugs in | What to wire |
|---|---|---|
| **BLE render + input** | `bridge/` (Lua ↔ phone) → `halo-lua/` | Send the card dicts to the Halo; deliver taps/gestures back. Cards are plain dicts (`hud/cards.py`). |
| **Microphone + ASR** | feeds `orchestrator.handle_voice(text)` | On-device speech-to-text → text; wake-word ("Hey DreamLayer") spotting. |
| **macOS Messages/Mail reader** | `ai_brain/server/macos_sources.py: recent_messages()` (`messages_fn` seam on `Brain`) | Real read of `chat.db` / Mail (returns structured items; `[]` off macOS today). |
| **macOS send** | `macos_sources.send_message(draft, approved=True)` | `osascript` dispatch — only ever on explicit approval. |
| **Calendar sync** | `macos_sources.read_calendar_events` / `list_calendars` (`calendar_reader_fn` / `calendar_list_fn` seams on `Brain`) | Reads Calendar.app via AppleScript and merges into `agenda.json` (keeps hand-added events; synced ones carry `source:"calendar"`). Toggle + calendar picker in the panel; `[]` off macOS. Swap the reader for EventKit if preferred. |
| **iOS/Android notifications** | `phone-app/src/services/notify.ts` | `npm install` picks up `expo-notifications`; grant permission on the device. |
| **Reach-anywhere relay** | pairing `relay_url` + `brainFetch` fallback | Host a secure relay/tunnel to the Mac mini; put its URL in the pairing bundle. The phone client already prefers LAN and falls back to it. |
| **Local model (optional)** | `ai_brain/server/backends.py` (Ollama) | Ollama on the Mac mini powers written answers, vision, summaries, brief, and smart replies. Keyword works with none. See `OLLAMA_SETUP.md`. |
| **Cloud model (optional)** | Brain config `cloud_*` | An OpenAI-compatible key/model, set in the panel; only ever a fallback, logged on every call. |

## 3b. Mac appliance

- **Menu-bar app** — `python -m dreamlayer.ai_brain.menubar` (`rumps`, macOS):
  a status dot (green / yellow-unconfigured / sunglasses-incognito / offline),
  "Open panel", one-click "Sync now" (calendar+contacts+reminders) and
  "Incognito". Pure core (`status_summary`, `launch_agent_plist`) is tested.
- **Launch at login** — `python -m dreamlayer.ai_brain.menubar --install-login`
  writes a `~/Library/LaunchAgents/vision.dreamlayer.brain.plist` that starts
  the Brain server at login (`RunAtLoad` + `KeepAlive`).
- **One-click model pull** — the panel's model card shows a **⬇ Pull** button
  per missing Ollama model, calling `POST /dreamlayer/model/pull` (local-only).

## 4. Privacy invariants (hold at every seam)

- The **Privacy Veil** (`privacy.allow_capture()`) gates capture, pop-ups, and
  anticipation — one gesture silences all.
- **On-device by default**; the Mac mini stays on your LAN; **cloud is opt-in**
  and every egress is counted + logged (`/dreamlayer/status` `cloud_calls`,
  activity `cloud-egress`).
- **Nothing sends silently** — outbound messages require `approved:true`.
- **Local-only endpoints** never answer off-box (pairing, secrets, filesystem,
  backup, restore, sends).

---

See also: [`AI_BRAIN.md`](AI_BRAIN.md) (tiered brain + the three switches),
[`TESTING.md`](TESTING.md) (run it), [`PRIVACY_MODEL.md`](PRIVACY_MODEL.md).
