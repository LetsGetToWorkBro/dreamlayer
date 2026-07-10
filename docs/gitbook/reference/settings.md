# Reference — settings and modes

Every user-facing setting in the ecosystem, its default, what it does, and
what it drives. Three surfaces expose them: the phone app, the Brain panel,
and the Juno's voice commands; underneath they converge on orchestrator
setters and Brain config keys.

## Phone app toggles

From `phone-app/src/state/useBrainStore.ts` (defaults) and the Brain and
Settings screens (placement). Persisted to AsyncStorage unless noted.

| Setting | Screen | Default | Effect / endpoint |
|---|---|---|---|
| Mac mini connected | Brain | off | phone-vs-Mac brain; gates all Brain-backed screens; `connectMacMini` |
| Glasses connected | Brain / onboarding | off | pairing state for the Halo |
| Use cloud for hard cases | Brain | **on** | `POST /dreamlayer/config {cloud_enabled}`; disabled while incognito |
| Incognito | Brain, Settings | off | forces cloud off and pauses capture; `POST /dreamlayer/config {network_mode}` |
| Pause memory capture | Brain, Now, Settings | off | the capture pause; drives the Now tab's Live/Paused pill |
| Proactive cards | Settings | on | master switch for anticipatory cards |
| Events cue | Settings (nested) | on | "leave in 8 min" cards |
| People cue | Settings (nested) | on | who-is-in-front-of-you cards |
| Places cue | Settings (nested) | on | what-you-left-here cards |
| Focus mode | Settings | off | hush interruptions, capture keeps running; unlocks the Deep Focus badge via `POST /dreamlayer/saga/record` |
| Text pop-ups on glasses | Settings | on | iMessage pop-up notifications |
| Email pop-ups on glasses | Settings | on | email pop-up notifications |
| Summarize long emails | Settings | off | `POST /dreamlayer/config {summarize_emails}` |
| Proactive alerts | Settings | on | the hark policy ("Listen!" / "Watch out!") |
| Live fact-checker | Settings | **off** | Veritas |
| Answer-ahead | Settings | **off** | the conversational copilot |
| Wake by voice / tap / gaze / raise | Settings | all on | Juno wake sources |
| Listening feedback: visual / audio / haptic | Settings | all on | wake ring, earcon, haptic tick |
| Wake word | Settings | "Hey Juno" | fixed label today (not editable) |
| Erase all memories | Settings (danger) | — | clears the local memory store, confirmed |

## Orchestrator setters

The hub's programmatic surface (`orchestrator/orchestrator.py`), for
completeness — the phone toggles above map onto these:

| Setter | Default | Notes |
|---|---|---|
| `connect_mac_mini(on)` | off | also `brain.set_local_only(not on)` |
| `use_cloud(on)` | on | preference restored when incognito lifts |
| `set_incognito(on)` | off | forces cloud off for the session |
| `set_focus(minutes)` / `clear_focus()` | off; 25 min via voice | do-not-disturb window |
| `set_captions(on)` | on | display only; ledger keeps recording |
| `set_factcheck(on)` | **off** | Veritas |
| `set_truthlens(on)` | **off** | delivery reads |
| `set_copilot(on)` | **off** | answer-ahead |
| `set_attention(on)` | on | the hark policy |
| `set_anticipation(on)` | on | proactive cards |
| `set_cue(kind, on)` | all on | event / person / place |
| `set_wake_source(source, on)` | all on | voice / tap / gaze / raise |
| `set_wake_feedback(kind, on)` | all on | visual / audio / haptic |
| `set_text_notifications(on)` / `set_email_notifications(on)` | on / on | message pop-ups per channel |
| `pause()` / `resume()` | — | the Privacy Veil |
| `enter_dream()` / `exit_dream()` | — | Dream Mode |
| `start_message_polling(interval=8.0)` / `stop_message_polling()` | — | background feed |
| `start_pulse(context_fn, interval=15.0)` / `stop_pulse()` | — | the proactive heartbeat |

## Brain config keys

`server/store.py: BrainConfig` — patched via `POST /dreamlayer/config`,
persisted as `brain_config.json`, secrets masked on read:

| Key | Default | Meaning |
|---|---|---|
| `folders` | `[]` | watched directories |
| `model` | `"keyword"` | `keyword` or `ollama` |
| `ollama_url` | `http://127.0.0.1:11434` | |
| `ollama_chat_model` | `llama3.2` | answers, brief, replies, summaries |
| `ollama_vision_model` | `llama3.2-vision` | object explain |
| `ollama_embed_model` | `nomic-embed-text` | semantic search |
| `email_enabled` | false | fold Messages/Mail into the index |
| `summarize_emails` | false | one-line email glances |
| `network_mode` | `"connected"` | `lan_only` = incognito |
| `cloud_enabled` | **true** | the cloud switch |
| `cloud_base_url` | `https://api.openai.com` | any OpenAI-compatible provider |
| `cloud_api_key` | empty | masked to "set" on read |
| `cloud_model` | `gpt-4o-mini` | |
| `cloud_calls` | 0 | lifetime egress counter (read-only in practice) |
| `token` | empty | pairing secret; masked on read |
| `semantic_search` | false | embeddings on/off |
| `index_extensions` | `[]` | empty = the default text set |
| `max_file_kb` | 2000 | per-file indexing cap |
| `exclude_globs` | `[]` | skip patterns |
| `quiet_hours` | empty | e.g. `"22:00-07:00"` — scheduled incognito |
| `retention_days` | 0 | prune history/activity on boot (0 = keep) |
| `brief_hour` | -1 | daily brief hour (-1 = off) |
| `calendar_sync` / `calendar_names` / `calendar_days` | off / all / 14 | macOS Calendar seam |
| `contacts_sync` | off | macOS Contacts seam |
| `reminders_sync` / `reminder_lists` | off / all | macOS Reminders seam |

## Modes, disambiguated

| Mode | Capture | Cloud | Interruptions | Set by |
|---|---|---|---|---|
| Normal | on | per switch | per toggles | — |
| **Focus** | on | per switch | held (urgent watch-outs pierce) | phone, voice |
| **Incognito** | paused | forced off | moot | phone, panel, voice |
| **Privacy Veil** | off — deaf and blind | no asks at all | none | long press on the glasses |
| **Quiet hours** | on | forced off | per toggles | panel schedule |
| **Dream Mode** | dream sensors only | — | ambient only | double tap |
