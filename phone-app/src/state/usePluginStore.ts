/**
 * usePluginStore — the phone's view of the plugin marketplace.
 *
 * Mirrors host-python/src/dreamlayer/plugins (docs/MARKETPLACE.md). The phone
 * *browses* the git-backed registry and manages *intent*: installing a plugin
 * grants it the capabilities it asked for and tells the paired hub/Mac to fetch
 * and run it — where the validation gate (integrity + capability scan + smoke
 * test) actually executes. The phone never runs plugin code itself.
 *
 * The installed set persists across launches (AsyncStorage). Install/remove are
 * best-effort POSTed to the Mac Brain when one is paired; failures are swallowed
 * (local UI is the source of truth and re-syncs on next change).
 */
import { create } from "zustand";
import AsyncStorage from "@react-native-async-storage/async-storage";

// The registry is served from the deployed site first (the deploy workflow
// copies registry/ into the Pages build), with raw GitHub as the fallback —
// raw.githubusercontent 404s while the repo is private, which used to make
// every install a dead end.
const INDEX_URLS = [
  "https://dreamlayer.app/registry/index.json",
  "https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/registry/index.json",
];

// Where the actual signed packages (manifest + source) live. Installing fetches
// the package here and *sideloads* it to the paired Brain, which validates it
// (integrity + capability scan + smoke test) and runs it — the phone never
// runs plugin code, and a name alone can't install (the Brain has no registry).
const PACKAGE_BASES = [
  "https://dreamlayer.app/registry/packages/",
  "https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/registry/packages/",
];

// The deployed social-API Worker (registry-api/): live downloads/ratings and
// one-tap rating. The catalogue comes from the snapshot/index; the API only
// supplies the numbers, merged by name. Empty ⇒ static, git-backed store.
const SOCIAL_API = "https://api.dreamlayer.app";

const STORAGE_KEY = "dreamlayer.plugins.installed.v1";
const UID_KEY = "dreamlayer.plugins.uid.v1";

export type PluginEntry = {
  name: string;
  version: string;
  author: string;
  /** First-party plugin, published and maintained by the DreamLayer team. */
  official?: boolean;
  /** Plugin API version the manifest targets ("1" | "2"). */
  api?: string;
  /** Reserved pricing seam — every plugin is free today ({ model: "free" }). */
  pricing?: { model: string; [k: string]: unknown };
  description: string;
  homepage?: string;
  requires: string[];
  tags: string[];
  downloads: number;
  rating: number;
  ratings_count: number;
  comments_count: number;
  // Detail copy the author ships with the plugin (travels in the registry).
  long: string[];
  forwho: string;
  screenshot: string;
};

export type InstalledPlugin = {
  name: string;
  version: string;
  grantedCapabilities: string[];
  installedAt: number;
  /** "installed" once the hub confirms; "pending" while it's queued for a hub. */
  status: "installed" | "pending";
};

/** Shipped snapshot so the store renders before the network answers. */
const SNAPSHOT: PluginEntry[] = [
  {
    name: "face-synth",
    version: "0.1.0",
    author: "DreamLayer Team",
    official: true,
    description:
      "Your head is a MIDI controller — yaw picks the note, pitch bends the filter, a tap plays it. Multiple wearers become a distributed band over the mesh.",
    homepage:
      "https://github.com/LetsGetToWorkBro/dreamlayer/blob/main/host-python/src/dreamlayer/plugins/face_synth.py",
    requires: ["midi"],
    tags: ["music", "creative", "mesh", "featured"],
    downloads: 0,
    rating: 0,
    ratings_count: 0,
    comments_count: 0,
    screenshot: "https://dreamlayer.app/plugin-shots/face-synth.png",
    forwho: "For musicians, performers, and tinkerers who want to play the world.",
    long: [
      "Turn your glasses into a musical instrument — no controller, no hands. Tilt your head to choose a note, tap to play it, and how loud you are sets how hard it hits.",
      "You can’t play a wrong note: pitches are locked to a scale, so every move lands in key.",
      "Jam together — everyone on a GhostMode circle becomes a separate voice in one band, their notes carried over the mesh so every rig hears the whole ensemble.",
    ],
  },
  {
    name: "open-food-facts",
    version: "0.1.0",
    author: "DreamLayer Team",
    official: true,
    description:
      "Rank a shelf by Open Food Facts — Nutri-Score becomes a rating, allergens are flagged. A real TasteLens connector, no key, open data.",
    homepage:
      "https://github.com/LetsGetToWorkBro/dreamlayer/blob/main/host-python/src/dreamlayer/plugins/openfoodfacts.py",
    requires: ["network"],
    tags: ["shopping", "food", "connector", "tastelens", "featured"],
    downloads: 0,
    rating: 0,
    ratings_count: 0,
    comments_count: 0,
    screenshot: "https://dreamlayer.app/plugin-shots/open-food-facts.png",
    forwho: "For anyone with dietary goals or allergies — or who just wants the better pick.",
    long: [
      "Shop smarter. Look at a shelf or a menu and TasteLens ranks it against your rules — this connector is what gives it something to rank on.",
      "Every item is scored by its Nutri-Score (A is best, E worst) and its allergens are flagged, pulled live from Open Food Facts, a free community food database. No account, no API key.",
      "Private by design: your dietary rules stay on your device — only the product name leaves it, to look the item up.",
    ],
  },
  {
    name: "currency-converter",
    version: "0.1.0",
    author: "DreamLayer Team",
    official: true,
    description: "Look at a foreign price tag and see it in your own money — live rates, right on the panel.",
    homepage: "https://github.com/LetsGetToWorkBro/dreamlayer/blob/main/host-python/src/dreamlayer/plugins/currency.py",
    requires: ["object_lens", "network"],
    tags: ["travel", "shopping", "utility", "connector"],
    downloads: 0,
    rating: 0,
    ratings_count: 0,
    comments_count: 0,
    screenshot: "https://dreamlayer.app/plugin-shots/currency-converter.png",
    forwho: "For travellers and anyone shopping across currencies.",
    long: [
      "Abroad, prices stop being abstract. Look at a tag or a menu and the look-at-a-thing panel shows the amount in your home currency, inline — no phone, no mental math.",
      "It converts with live exchange rates (free, no account) and shows the rate it used, so you always know what you’re really paying.",
      "Private by design: only the number and its currency are looked up — never where you are or what you bought.",
    ],
  },
  {
    name: "hud-reactions",
    version: "0.1.0",
    author: "DreamLayer Team",
    official: true,
    description: "Throw 🎉 👏 ❤️ 🔥 onto your HUD — and everyone in your GhostMode circle sees it too.",
    homepage: "https://github.com/LetsGetToWorkBro/dreamlayer/blob/main/host-python/src/dreamlayer/plugins/reactions.py",
    requires: ["cards", "mesh"],
    tags: ["social", "fun", "mesh"],
    downloads: 0,
    rating: 0,
    ratings_count: 0,
    comments_count: 0,
    screenshot: "https://dreamlayer.app/plugin-shots/hud-reactions.png",
    forwho: "For friends, gigs, and anyone sharing a moment on the mesh.",
    long: [
      "Tap to react. A burst lands on your HUD, and if you’re in a GhostMode circle, it lands on theirs — a silent “yes!” across a room.",
      "Only the tiny symbol crosses the mesh, signed and small — never who you are or where you’re standing. It rides the same “only feeling travels” rule as the rest of GhostMode.",
      "Great for concerts, watch parties, and inside jokes with the people next to you.",
    ],
  },
  {
    name: "filler-word-counter",
    version: "0.1.0",
    author: "DreamLayer Team",
    official: true,
    description: "A quiet coach that tallies your “um / like / you know” as you speak.",
    homepage: "https://github.com/LetsGetToWorkBro/dreamlayer/blob/main/host-python/src/dreamlayer/plugins/filler.py",
    requires: ["perception", "cards"],
    tags: ["coaching", "speaking", "productivity"],
    downloads: 0,
    rating: 0,
    ratings_count: 0,
    comments_count: 0,
    screenshot: "https://dreamlayer.app/plugin-shots/filler-word-counter.png",
    forwho: "For anyone who presents, pitches, or records.",
    long: [
      "Public speaking, on your side. It listens to your own words and keeps a running count of filler words in the corner of your eye — so you hear yourself, and drop them.",
      "It knows the usual suspects — um, uh, like, you know, basically — and tracks a rough per-sentence rate as you go.",
      "Nothing is recorded or sent anywhere; the tally lives on your glasses and resets when you’re done.",
    ],
  },
  {
    name: "air-drums",
    version: "0.1.0",
    author: "DreamLayer Team",
    official: true,
    description: "Play a drum kit in the air — head-nods and taps fire real MIDI drums.",
    homepage: "https://github.com/LetsGetToWorkBro/dreamlayer/blob/main/host-python/src/dreamlayer/plugins/air_drums.py",
    requires: ["midi"],
    tags: ["music", "creative", "midi"],
    downloads: 0,
    rating: 0,
    ratings_count: 0,
    comments_count: 0,
    screenshot: "https://dreamlayer.app/plugin-shots/air-drums.png",
    forwho: "For drummers, producers, and fidgeters.",
    long: [
      "No sticks, no pads. Nod down for a kick, flick left for a snare, right for a hat, up for a crash — each gesture fires a General-MIDI drum on channel 10, into any DAW or drum machine.",
      "Velocity follows how hard you move, so it feels dynamic, not robotic.",
      "Pairs with Face Synth for a hands-free one-person band.",
    ],
  },
];

function normalize(p: any): PluginEntry {
  return {
    name: String(p?.name ?? ""),
    version: String(p?.version ?? ""),
    author: String(p?.author ?? "community"),
    official: Boolean(p?.official),
    api: String(p?.api ?? "1"),
    pricing:
      p?.pricing && typeof p.pricing === "object" ? p.pricing : { model: "free" },
    description: String(p?.description ?? ""),
    homepage: p?.homepage ? String(p.homepage) : undefined,
    requires: Array.isArray(p?.requires) ? p.requires.map(String) : [],
    tags: Array.isArray(p?.tags) ? p.tags.map(String) : [],
    downloads: Number(p?.downloads ?? 0) || 0,
    rating: Number(p?.rating ?? 0) || 0,
    ratings_count: Number(p?.ratings_count ?? 0) || 0,
    comments_count: Number(p?.comments_count ?? 0) || 0,
    long: Array.isArray(p?.long) ? p.long.map(String) : [],
    forwho: String(p?.forwho ?? ""),
    screenshot: String(p?.screenshot ?? ""),
  };
}

type MacTarget = { url: string; token: string } | null;

export type SortKey = "featured" | "rating" | "downloads" | "all";

type PluginState = {
  index: PluginEntry[];
  installed: Record<string, InstalledPlugin>;
  loading: boolean;
  loaded: boolean;
  /** True when no live registry mirror answered and we're showing the bundled snapshot. */
  offline: boolean;
  hydrate: () => Promise<void>;
  fetchIndex: () => Promise<void>;
  search: (query: string, sort: SortKey) => PluginEntry[];
  isInstalled: (name: string) => boolean;
  install: (entry: PluginEntry, mac?: MacTarget) => Promise<{ ok: boolean; error?: string }>;
  flushPending: (mac: MacTarget) => Promise<void>;
  remove: (name: string, mac?: MacTarget) => Promise<void>;
  rate: (name: string, stars: number) => Promise<void>;
};

async function userId(): Promise<string> {
  try {
    let u = await AsyncStorage.getItem(UID_KEY);
    if (!u) {
      u = "u" + Math.random().toString(36).slice(2);
      await AsyncStorage.setItem(UID_KEY, u);
    }
    return u;
  } catch {
    return "anon";
  }
}

async function persist(installed: Record<string, InstalledPlugin>) {
  try {
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(installed));
  } catch {
    /* local cache only; ignore */
  }
}

async function postToMac(mac: MacTarget, path: string, body: any): Promise<any | null> {
  if (!mac?.url) return null;
  try {
    const res = await fetch(mac.url.replace(/\/$/, "") + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-DreamLayer-Token": mac.token },
      body: JSON.stringify(body),
    });
    return await res.json().catch(() => ({}));
  } catch {
    return null; // hub unreachable
  }
}

/** Fetch the actual package (manifest + source) so a Brain can validate + run it.
 *  Tries each mirror in order; null when none answers (then only a name can be
 *  sent, which a Brain without a wired registry will refuse — surfaced to the
 *  user). The shape check also defeats Pages' SPA fallback, which answers 200
 *  text/html for missing paths. */
async function fetchPackage(
  entry: PluginEntry,
): Promise<{ manifest: any; source: string } | null> {
  const file = encodeURIComponent(`${entry.name}-${entry.version}.json`);
  for (const base of PACKAGE_BASES) {
    try {
      const res = await fetch(base + file, { cache: "no-store" } as any);
      if (!res.ok) continue;
      const d = await res.json();
      if (d?.manifest && d?.source) return { manifest: d.manifest, source: String(d.source) };
    } catch {
      /* mirror unreachable or served HTML — try the next */
    }
  }
  return null;
}

/** Fetch the package and sideload it to the Brain, returning the Brain's real
 *  verdict with an honest reason on failure (validation errors, auth, or a
 *  missing package — each reads differently to the user). */
async function sideload(
  entry: PluginEntry,
  mac: MacTarget,
): Promise<{ ok: boolean; error?: string }> {
  const pkg = await fetchPackage(entry);
  const body = pkg
    ? { manifest: pkg.manifest, source: pkg.source, grant: entry.requires }
    : { name: entry.name, version: entry.version, grant: entry.requires };
  const resp = await postToMac(mac, "/dreamlayer/plugins/install", body);
  if (resp?.ok) return { ok: true };
  const error =
    (Array.isArray(resp?.errors) && resp.errors[0]) ||
    (typeof resp?.error === "string" && resp.error) || // e.g. "unauthorised" — re-pair
    (resp == null
      ? "your hub didn't answer — check it's on the same network"
      : pkg
      ? "your hub couldn't validate it"
      : "couldn't fetch the plugin package");
  return { ok: false, error };
}

/** Best-effort public download counter — only for installs that actually ran. */
function bumpDownload(name: string) {
  if (!SOCIAL_API) return;
  fetch(SOCIAL_API.replace(/\/$/, "") + "/api/plugins/" + encodeURIComponent(name) + "/download", {
    method: "POST",
  }).catch(() => {});
}

export const usePluginStore = create<PluginState>((set, get) => ({
  index: SNAPSHOT,
  installed: {},
  loading: false,
  loaded: false,
  offline: false,

  hydrate: async () => {
    try {
      const raw = await AsyncStorage.getItem(STORAGE_KEY);
      if (raw) set({ installed: JSON.parse(raw) });
    } catch {
      /* ignore */
    }
    get().fetchIndex();
  },

  fetchIndex: async () => {
    set({ loading: true });
    // The client owns the catalogue (the registry may be private): base = the
    // snapshot, overlaid by the live git index if public, then by live social
    // stats merged by name. Any step failing just leaves the prior data.
    let base: PluginEntry[] = SNAPSHOT.slice();
    let live = false;
    for (const url of INDEX_URLS) {
      try {
        const res = await fetch(url, { cache: "no-store" } as any);
        if (!res.ok) continue;
        const data = await res.json();
        const list = Array.isArray(data?.plugins) ? data.plugins.map(normalize) : [];
        if (list.length) {
          base = list;
          live = true;
          break;
        }
      } catch {
        /* mirror unreachable → try the next, else keep the snapshot */
      }
    }
    if (SOCIAL_API) {
      try {
        const res = await fetch(SOCIAL_API.replace(/\/$/, "") + "/api/plugins", { cache: "no-store" } as any);
        const data = await res.json();
        const m: Record<string, any> = {};
        (Array.isArray(data?.plugins) ? data.plugins : []).forEach((s: any) => (m[s.name] = s));
        base = base.map((p) => ({ ...p, ...(m[p.name] || {}) }));
      } catch {
        /* keep base without live stats */
      }
    }
    set({ index: base, loading: false, loaded: true, offline: !live });
  },

  search: (query, sort) => {
    const q = (query || "").trim().toLowerCase();
    let list = get().index.filter(
      (p) =>
        !q ||
        `${p.name} ${p.description} ${p.author} ${p.tags.join(" ")}`
          .toLowerCase()
          .includes(q),
    );
    const featured = (p: PluginEntry) => (p.tags.includes("featured") ? 1 : 0);
    if (sort === "featured")
      list = [...list].sort((a, b) => featured(b) - featured(a) || b.downloads - a.downloads);
    else if (sort === "rating")
      list = [...list].sort((a, b) => b.rating - a.rating || b.ratings_count - a.ratings_count);
    else if (sort === "downloads") list = [...list].sort((a, b) => b.downloads - a.downloads);
    else list = [...list].sort((a, b) => a.name.localeCompare(b.name));
    return list;
  },

  isInstalled: (name) => !!get().installed[name],

  install: async (entry, mac = null) => {
    // Sideload the real package to the paired Brain and reflect *its* verdict —
    // no more optimistically showing "installed" for a plugin the hub silently
    // rejected. With no hub, it's queued locally until one pairs (flushPending).
    if (mac?.url) {
      const r = await sideload(entry, mac);
      if (!r.ok) return r; // nothing persisted — the UI stays not-installed
    }
    const rec: InstalledPlugin = {
      name: entry.name,
      version: entry.version,
      grantedCapabilities: [...entry.requires],
      installedAt: Date.now(),
      status: mac?.url ? "installed" : "pending",
    };
    const installed = { ...get().installed, [entry.name]: rec };
    set({ installed });
    await persist(installed);
    if (mac?.url) bumpDownload(entry.name); // count real installs, not queued intents
    return { ok: true };
  },

  flushPending: async (mac) => {
    // A Brain just paired: complete every install that was queued while
    // offline — the promise "it installs the next time one is paired", kept.
    if (!mac?.url) return;
    const installed = { ...get().installed };
    let changed = false;
    for (const rec of Object.values(installed)) {
      if (rec.status !== "pending") continue;
      const entry =
        get().index.find((p) => p.name === rec.name) ??
        ({ name: rec.name, version: rec.version, requires: rec.grantedCapabilities } as PluginEntry);
      const r = await sideload(entry, mac);
      if (r.ok) {
        installed[rec.name] = { ...rec, status: "installed", installedAt: Date.now() };
        bumpDownload(rec.name);
        changed = true;
      }
      // failures stay pending — visible in the UI, retried on the next pair
    }
    if (changed) {
      set({ installed });
      await persist(installed);
    }
  },

  remove: async (name, mac = null) => {
    const installed = { ...get().installed };
    delete installed[name];
    set({ installed });
    await persist(installed);
    await postToMac(mac, "/dreamlayer/plugins/remove", { name });
  },

  rate: async (name, stars) => {
    if (!SOCIAL_API) return;
    try {
      await fetch(SOCIAL_API.replace(/\/$/, "") + "/api/plugins/" + encodeURIComponent(name) + "/rate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stars, user: await userId() }),
      });
      get().fetchIndex();
    } catch {
      /* best effort */
    }
  },
}));
