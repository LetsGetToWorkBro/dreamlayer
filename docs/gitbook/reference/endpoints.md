# Reference — the Brain HTTP API

Base URL: `http://<mac>:7777`. Every `/dreamlayer/*` call requires the
pairing token header **`X-DreamLayer-Token`** (the panel injects it
automatically when opened on the machine itself). Endpoints marked
**local** additionally refuse any off-box client (403) because they expose
secrets, the filesystem, or outbound action. Any token-bearing off-box
request also stamps the "phone last seen" heartbeat.

Source: `host-python/src/dreamlayer/ai_brain/server/server.py`. This table
is the complete surface — including three endpoints
(`/dreamlayer/voice`, the profile pair, `/dreamlayer/brief/latest`) that
exist in code beyond the summary tables in `docs/INTEGRATION.md`.

## Read (GET)

| Endpoint | Auth | Returns |
|---|---|---|
| `/` | none | the control panel (HTML; token injected only on localhost) |
| `/dreamlayer/status` | token | live state: model, cloud, cloud_ready, cloud_calls, incognito, quiet, phone_ago, index_ago, missing folders, index stats |
| `/dreamlayer/config` | token | full config (token and cloud key masked) plus index stats and the `plan` summary |
| `/dreamlayer/health` | token | version, index disk size, Ollama latency, uptime |
| `/dreamlayer/history` | token | unified activity feed (asks plus folder / upload / cloud / pair events) |
| `/dreamlayer/messages/recent` | token | recent Messages + Mail `{items, enabled, summarize_emails}` — **seam:** macOS readers |
| `/dreamlayer/calendar` | token | upcoming agenda `{items}` |
| `/dreamlayer/calendars` | token | macOS calendars + sync settings `{items, sync, selected, last_sync}` — **seam** |
| `/dreamlayer/contacts` | token | Contacts sync state `{sync, last_sync, count}` — **seam** |
| `/dreamlayer/reminders` | token | open reminders + lists + sync state — **seam** |
| `/dreamlayer/people` | token | the dossier registry `{items: [{name, note, tags, ts}]}` |
| `/dreamlayer/rewind` | token | today in hour blocks `{blocks, count}` |
| `/dreamlayer/saga` | token | the progression profile: rank, level, XP, every achievement |
| `/dreamlayer/profile` | token | the mirrored Juno user-model profile |
| `/dreamlayer/brief/latest` | token | the scheduler's most recent morning brief (or `{}`) |
| `/dreamlayer/brief/long/latest` | token | the last extended (long) brief (or `{}`) |
| `/dreamlayer/social/people` | token | the mirrored social memory: people with relations, notes, debts, topics |
| `/dreamlayer/plugins` | token | installed plugins + the capabilities this Brain can grant |
| `/dreamlayer/capabilities` | token | the live capability report `{items, summary, profiles, disabled, packs, frozen}` |
| `/dreamlayer/memories` | token | assembled kept memory: saved places, people met, owed favors, dated reminders |
| `/panel-assets/<name>` | none | bundled panel imagery (cinematic stills, explainer cards) |
| `/dreamlayer/rc/repertoire` | token | kept Reality Compiler figments `{items, active}` |
| `/dreamlayer/model/status` | token | Ollama reachability + which configured models are pulled |
| `/dreamlayer/browse?path=` | **local** | subfolders of a directory (the panel's folder picker) |
| `/dreamlayer/token` | **local** | the current pairing token |
| `/dreamlayer/pair` | **local** | a `dreamlayer:` pairing code (LAN URL + token) with QR SVG |
| `/dreamlayer/backup` | **local** | full restorable snapshot (config incl. secrets, history, activity, agenda) |

## Write (POST, JSON)

| Endpoint | Auth | Body → effect |
|---|---|---|
| `/dreamlayer/brain/ask` | token | `{query}` → `Answer {text, tier, sources, confidence}`; logged; may cross to cloud under the gate |
| `/dreamlayer/brain/explain` | token | `{label, image?, want?}` → object `Answer` |
| `/dreamlayer/voice` | token | `{text}` → intent routing: ask/recall/brief answered inline; timers/intervals/clock compiled and deployed (`rc_native`); notes/meet/debts/settle applied to the people mirror (`voice_social`); locate/stash answered from Waypath; missed and reply handled in place; others returned as `{intent, ...args}` |
| `/dreamlayer/brief` | token | `{agenda?, since?, depth?, commitments?, memories?}` → `{text, bullets, missed}`; `depth: "long"` adds `sections` and is cached for `brief/long/latest` |
| `/dreamlayer/replies` | token | `{text}` → `{replies: [three short replies]}` |
| `/dreamlayer/folders` | token | `{action: add\|remove, path}` → save + reindex |
| `/dreamlayer/config` | token | partial config patch (whitelisted keys) → apply + reindex |
| `/dreamlayer/upload?folder=&name=` | token | raw body → written into a *watched* folder only, then reindex |
| `/dreamlayer/calendar` | token | `{title, ts, place}` adds; `{remove: true, title, ts}` removes → `{items}` |
| `/dreamlayer/calendar/sync` | token | `{}` → pull Calendar.app now `{items, synced}` — **seam** |
| `/dreamlayer/contacts/sync` | token | `{}` → pull Contacts.app `{items, synced}` — **seam** |
| `/dreamlayer/reminders/sync` | token | `{}` → pull Reminders.app `{items, synced}` — **seam** |
| `/dreamlayer/people` | token | `{name, note?, tags?}` upsert; `{remove: true, name}` → `{items}` |
| `/dreamlayer/saga/record` | token | `{event}` → `{unlocked, saga}` |
| `/dreamlayer/profile` | token | hub pushes the user-model snapshot; Brain mirrors, never authors |
| `/dreamlayer/reindex` | token | `{}` → rebuild now `{stats, missing}` |
| `/dreamlayer/social/people` | token | the hub pushes the social-memory snapshot; the Brain mirrors, never authors |
| `/dreamlayer/social/people/edit` | token | `{contact_id, action: note\|remove_note\|relation\|settle, value?}` → phone edits `{items}` |
| `/dreamlayer/rc/rehearse` | token | `{name, beats[]}` → live score, budget report, teach card; never 500s on a pathological performance |
| `/dreamlayer/rc/keep` | token | `{figment_id}` → sign + vault |
| `/dreamlayer/rc/deploy` | token | `{figment_id}` → hot-swap onto the stage (BLE envelopes recorded until the glasses transport attaches) |
| `/dreamlayer/rc/revoke` | token | `{figment_id}` → pull it from the stage/vault |
| `/dreamlayer/plugins/install` | token | `{name}` from the registry or a sideloaded `{manifest, source}` → validated install `{ok, errors, warnings, state}` |
| `/dreamlayer/plugins/remove` | token | `{name}` → uninstall |
| `/dreamlayer/capabilities` | token | `{key, disabled}` → one-click capability on/off (persisted as `disabled_caps`) |
| `/dreamlayer/packs` | token | `{pack}` → background pip-install of a capability pack (refused in the sealed app) |
| `/dreamlayer/memories/purge` | token | `{}` → drop every saved place (people and reminders deliberately survive) |
| `/dreamlayer/message/draft` | token | `{channel, to, subject?, text}` → `{script}` — preview only, nothing sent |
| `/dreamlayer/message/send` | **local** | same + `approved: true` → osascript send — **seam**; refused without approval |
| `/dreamlayer/model/pull` | **local** | `{model}` → blocking `ollama pull` `{ok, status, model}` |
| `/dreamlayer/cloud/test` | **local** | `{}` → `{ok, reply\|error}` provider round trip |
| `/dreamlayer/token/rotate` | **local** | `{}` → new token; every paired device must re-pair |
| `/dreamlayer/clear` | **local** | `{what: history\|activity\|folders\|all}` |
| `/dreamlayer/restore` | **local** | a backup snapshot → config, logs, agenda written back |

## Conventions

- **Answers:** `{text, tier, sources, confidence}`; an empty answer is
  `{"", "", [], 0.0}`.
- **Egress:** any cloud-tier answer increments `cloud_calls` and logs a
  `cloud-egress` activity entry — there is no other egress point.
- **Pairing code:** `dreamlayer:` + base64url JSON
  `{brain_url, token, glasses_id?, label?, relay_url?}`; `brain_url` is the
  LAN address, never loopback.
- The **laptop companion** (a different, minimal agent) serves exactly one
  route on its own port: `GET /dreamlayer/context` → recent file names,
  hostname, battery; token required to serve beyond localhost.
- The **plugin social API** is a separate public service at
  `https://api.dreamlayer.app` (Cloudflare Worker, `registry-api/`):
  `GET /api/plugins`, `GET /api/plugins/<name>`, and
  `POST /api/plugins/<name>/{rate|comment|download}`. It serves only
  ratings/downloads/comments — never plugin code — and clients fall back to
  their bundled catalog when it is unreachable.
