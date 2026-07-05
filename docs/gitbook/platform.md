# The platform — plugins, the mesh, and the store

DreamLayer is becoming a platform: a supported way for anyone to extend the
glasses without forking the product. The plan is five pillars
(`docs/PLATFORM.md`), built in dependency order, and all five have landed
their first working layer. The through-line: the codebase already ran on
declarative registries (object-lens providers, glance candidates, brain
tiers) — the platform work formalizes those seams instead of inventing new
ones.

## Pillar 1 — real perception at Tier 0

`ai_brain/perception.py` gives the glasses' own silicon a first-class seat.
A `Perceptor` protocol (mirroring `VisionBrain`) emits typed
`PerceptSignals` — face present, text density, form fields, a question, an
object, a language guess — and a `PerceptionRouter` holds perceptors in
preference order, exactly like the brain router:

- **`HeuristicPerceptor`** ships today: zero-model coarse cues (text density
  from gradient statistics, object-ness from contrast) that feed the Glance
  Arbiter's cheap first pass.
- **`NpuPerceptor`** is the seam: `vision_fn` / `audio_fn` are where a
  Vela-compiled model for the Halo's Ethos-U55 NPU (about 46 GOPS int8)
  plugs in. It returns `None` until a model is wired, and the router falls
  back to the heuristic — so the arbiter gets model-grade signals the day
  hardware arrives, with no change to its logic.

## Pillar 2 — GhostMode mesh and The Beacon

Confluence's two-wearer bond, lifted to a **group** (`confluence/mesh.py`):
form a circle with a three-word code, and up to a whole crew shares one
ambient layer for a night (groups expire after 8 hours; a quiet member
fades from the circle in 12 seconds).

The privacy properties are structural: only *feeling* crosses the wire — a
weather scalar, a bearing, a gesture symbol — never speech, never
coordinates, never names (members are anonymous ids; names live only in
your local alias map). Packets are HMAC-signed with a key derived from the
group code; forged, replayed, stranger, and stale-group traffic drops
silently; the Veil silences your side of the mesh like everything else.

**The Beacon** is the first thing built on it: "find my group" as a feel,
not a map. Each member broadcasts a coarse bearing and a distance band
(close / near / far — never coordinates); your rim renders one pulse per
fresh member, nearer means brighter and faster, and a **BeaconCard** names
them from your local aliases ("Maya - close, ahead-left"). **Seam:** the
LE Coded PHY radio transport; an in-memory bus stands in for it in tests
and demos (15 tests cover the crypto, the drops, and the veil).

## Pillar 3 — the Plugin API

`plugins/base.py` is the supported extension surface. A plugin is a name, a
version, a list of required **capabilities**, and one `register(ctx)` call.
The `PluginContext` exposes exactly six hooks and nothing else:

| Hook | What it extends |
|---|---|
| `add_object_provider` | a panel when you look at a matching object |
| `add_glance_candidate` | a lens the look can route to |
| `add_vision_brain` / `add_knowledge_brain` | a new brain tier |
| `add_perceptor` | a Tier-0 perception tier |
| `add_card_renderer` | how a custom card draws |
| `add_shop_provider` | a TasteLens data connector |

Capabilities are the permission system: a plugin declares what it needs
(`network`, `midi`, `mesh`, `cards`, `perception`...) and the host grants
only what it can and will — `fs` and `subprocess` are withheld by default,
`network` is revoked while the Veil is down, and a plugin requiring a
capability the device cannot grant is refused at install. A throwing
plugin is isolated; the registry records loaded / skipped / failed.

## Pillar 4 — TasteLens

The first-party lens built *on* the plugin seams, proving them: the ranking
engine is core, but its data connectors are ordinary plugins through
`add_shop_provider`. Full chapter: [Scholar and TasteLens](world-lenses.md).

## Pillar 5 — the WebBLE playground

Drive the actual glasses from a browser tab — no app store, no install.
`web/playground.html` (also live on the site at
[dreamlayer.app/playground](https://dreamlayer.app/playground.html)) speaks
Lua over the Nordic UART BLE service, the same transport the phone hub
uses: connect, run canned HUD demos, or type Lua into a live REPL. Works in
Chrome and Edge on desktop and Android; it detects browsers without Web
Bluetooth (every iOS browser, Firefox) and says so honestly instead of
showing a dead button.

The first plugin shipped with it: **Face Synth** — head yaw picks the note
(quantized to a scale, so there are no wrong notes), pitch bends
expression, a tap plays, and several wearers become a band over the mesh,
one MIDI channel each. **Seam:** the MIDI bridge (`midi_out`); the plugin
stays dormant until one exists.

## The marketplace

A plugin ships as a **package**: a manifest (name, semver, entry point,
required capabilities, sha256 checksum of the source, author copy and
screenshot kept outside the checksum so copy edits do not re-sign code)
plus one Python file. Every install — store or sideload — passes a
**four-line validation gate**:

1. Manifest shape (name/version/entry/api rules, only known capabilities).
2. Integrity — the checksum must match, twice (registry-advertised and
   fetched).
3. A static AST scan — `subprocess`, sockets, `ctypes`, file deletion,
   `eval`/`exec`/`pickle` are flagged; each allowed only if the matching
   capability was declared, some forbidden outright.
4. A smoke load against a mock context granting only declared capabilities.

The honest limit, stated in `docs/MARKETPLACE.md`: in-process Python cannot
be perfectly sandboxed — the gate is defense-in-depth for a curated,
reviewed registry, with signatures and real isolation as the hardening
path.

### The store, in three places

- **The website — [dreamlayer.app/plugins](https://dreamlayer.app/plugins.html):**
  browse, search, Featured / Top rated / Most downloaded tabs, per-plugin
  detail with the author's screenshot, plain-English permissions, star
  rating, and a copy-install action.
- **The phone** — the Plugins screen (Settings, "Build on the layer"):
  same catalog, install/remove, one-tap rating, and a permissions alert
  before any install ("This plugin will be able to use: ..."). The phone
  never runs plugin code — it posts intent to the paired Brain.
- **The Mac panel** — the Plugins card: what is installed, what this Brain
  can grant, per-plugin remove, and a sideload box that passes the same
  gate:

![The panel's Plugins card — two real installs; hud-reactions was refused because this Brain cannot grant mesh](assets/panel/plugins.png)

*A real session: two registry plugins installed; a third (hud-reactions)
was refused at the gate because this machine could not grant the `mesh`
capability it requires.*

![The phone's plugin store](assets/phone/plugins.png)

### The social layer — live at api.dreamlayer.app

Ratings, downloads, and comments live in a deliberately separate service:
a Cloudflare Worker at **[api.dreamlayer.app](https://api.dreamlayer.app)**
(`registry-api/`, KV-backed; the bare root redirects to the store). The
contract is five routes: list stats, per-plugin stats and comments, rate,
comment, record a download. The split is a security decision — **the API
serves only numbers, never plugin code**. The catalog itself is git-backed
and validated (`registry/`), and clients merge the two by name, falling
back to their bundled snapshot when the API is unreachable. Compromising
the social service cannot ship code to anyone.

### The registry today

Six plugins, every one passing the gate in CI (`registry/packages/`):

| Plugin | What it does | Needs |
|---|---|---|
| `open-food-facts` | TasteLens connector — Nutri-Score to rating, allergens flagged | network |
| `currency-converter` | look at a foreign price tag, see your money, live rates | object_lens, network |
| `hud-reactions` | throw a reaction onto your HUD, shared to your GhostMode circle | cards, mesh |
| `filler-word-counter` | a perceptor that tallies "um / uh / like" as you speak | perception, cards |
| `face-synth` | your head as a MIDI instrument; wearers form a band over the mesh | midi |
| `air-drums` | gesture-zone drum kit on MIDI channel 10 | midi |

## Hardening in the record

One more platform property worth naming: **a performance can never crash
the Brain.** The Reality Compiler's rehearsal endpoint wraps inference in a
last-resort net — any pathological beat combination returns an honest
"CAN'T DO THAT" teach card instead of a 500 — and the choreographer was
fixed so repeated counting beats feed one counter. The store, the gate, and
the rehearsal surface are all built on the same assumption: outside input
is hostile until proven otherwise.
