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
| `/dreamlayer/config` | token | full config (token and cloud key masked) plus index stats |
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
| `/dreamlayer/profile` | token | the mirrored Oracle user-model profile |
| `/dreamlayer/brief/latest` | token | the scheduler's most recent morning brief (or `{}`) |
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
| `/dreamlayer/voice` | token | `{text}` → intent routing: ask/recall answered inline, brief inlined, others returned as `{intent, ...args}` |
| `/dreamlayer/brief` | token | `{agenda?, since?}` → `{text, bullets, missed}` |
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
