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

const INDEX_URL =
  "https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/registry/index.json";

const STORAGE_KEY = "dreamlayer.plugins.installed.v1";

export type PluginEntry = {
  name: string;
  version: string;
  author: string;
  description: string;
  homepage?: string;
  requires: string[];
  tags: string[];
  downloads: number;
  rating: number;
  ratings_count: number;
  comments_count: number;
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
    author: "dreamlayer",
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
  },
];

function normalize(p: any): PluginEntry {
  return {
    name: String(p?.name ?? ""),
    version: String(p?.version ?? ""),
    author: String(p?.author ?? "community"),
    description: String(p?.description ?? ""),
    homepage: p?.homepage ? String(p.homepage) : undefined,
    requires: Array.isArray(p?.requires) ? p.requires.map(String) : [],
    tags: Array.isArray(p?.tags) ? p.tags.map(String) : [],
    downloads: Number(p?.downloads ?? 0) || 0,
    rating: Number(p?.rating ?? 0) || 0,
    ratings_count: Number(p?.ratings_count ?? 0) || 0,
    comments_count: Number(p?.comments_count ?? 0) || 0,
  };
}

type MacTarget = { url: string; token: string } | null;

export type SortKey = "featured" | "rating" | "downloads" | "all";

type PluginState = {
  index: PluginEntry[];
  installed: Record<string, InstalledPlugin>;
  loading: boolean;
  loaded: boolean;
  hydrate: () => Promise<void>;
  fetchIndex: () => Promise<void>;
  search: (query: string, sort: SortKey) => PluginEntry[];
  isInstalled: (name: string) => boolean;
  install: (entry: PluginEntry, mac?: MacTarget) => Promise<void>;
  remove: (name: string, mac?: MacTarget) => Promise<void>;
};

async function persist(installed: Record<string, InstalledPlugin>) {
  try {
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(installed));
  } catch {
    /* local cache only; ignore */
  }
}

async function postToMac(mac: MacTarget, path: string, body: any) {
  if (!mac?.url) return;
  try {
    await fetch(mac.url.replace(/\/$/, "") + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-DreamLayer-Token": mac.token },
      body: JSON.stringify(body),
    });
  } catch {
    /* best effort; local is source of truth */
  }
}

export const usePluginStore = create<PluginState>((set, get) => ({
  index: SNAPSHOT,
  installed: {},
  loading: false,
  loaded: false,

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
    try {
      const res = await fetch(INDEX_URL, { cache: "no-store" } as any);
      const data = await res.json();
      const list = Array.isArray(data?.plugins) ? data.plugins.map(normalize) : [];
      if (list.length) set({ index: list });
    } catch {
      /* keep the snapshot */
    }
    set({ loading: false, loaded: true });
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
    await postToMac(mac, "/dreamlayer/plugins/install", {
      name: entry.name,
      version: entry.version,
      grant: entry.requires,
    });
  },

  remove: async (name, mac = null) => {
    const installed = { ...get().installed };
    delete installed[name];
    set({ installed });
    await persist(installed);
    await postToMac(mac, "/dreamlayer/plugins/remove", { name });
  },
}));
