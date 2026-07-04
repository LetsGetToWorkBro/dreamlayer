/**
 * usePeopleStore — the phone's view of your social memory.
 *
 * Everyone you've met (Social Lens): how you know them, when you last saw them,
 * your notes, and any open debts. The hub (glasses) owns the truth and mirrors
 * it to the paired Brain — the same hub→Brain bridge the Oracle profile uses —
 * and this store reads it, and posts edits (add/remove a note, set the
 * relationship, settle debts) back to the Brain.
 *
 * Everything is on your own device; nothing leaves it.
 */
import { create } from "zustand";
import { useBrainStore } from "./useBrainStore";

export type Person = {
  contact_id: string;
  name: string;
  relation: string;
  company: string;
  role: string;
  last_met: string;
  last_seen: string;
  notes: string[];
  debts: string[];
  topics: string[];
};

type MacTarget = { url: string; token: string; relayUrl?: string };

function target(): MacTarget | null {
  const m = useBrainStore.getState().macMini;
  return m.connected && m.url ? { url: m.url, token: m.token, relayUrl: m.relayUrl } : null;
}

async function req(m: MacTarget, path: string, opts: RequestInit = {}): Promise<any> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(opts.headers as object) };
  if (m.token) headers["X-DreamLayer-Token"] = m.token;
  const o: RequestInit = { ...opts, headers };
  try {
    return await (await fetch(m.url + path, o)).json();
  } catch (e) {
    if (m.relayUrl) return await (await fetch(m.relayUrl + path, o)).json();
    throw e;
  }
}

function normalize(p: any): Person {
  return {
    contact_id: String(p?.contact_id ?? ""),
    name: String(p?.name ?? ""),
    relation: String(p?.relation ?? ""),
    company: String(p?.company ?? ""),
    role: String(p?.role ?? ""),
    last_met: String(p?.last_met ?? ""),
    last_seen: String(p?.last_seen ?? ""),
    notes: Array.isArray(p?.notes) ? p.notes.map(String) : [],
    debts: Array.isArray(p?.debts) ? p.debts.map(String) : [],
    topics: Array.isArray(p?.topics) ? p.topics.map(String) : [],
  };
}

type PeopleState = {
  people: Person[];
  loading: boolean;
  paired: boolean;
  loaded: boolean;
  fetchPeople: () => Promise<void>;
  addNote: (id: string, note: string) => Promise<void>;
  removeNote: (id: string, note: string) => Promise<void>;
  setRelation: (id: string, relation: string) => Promise<void>;
  settle: (id: string) => Promise<void>;
};

async function edit(set: any, get: any, id: string, action: string, value?: string) {
  const m = target();
  if (!m) return;
  try {
    const r = await req(m, "/dreamlayer/social/people/edit", {
      method: "POST",
      body: JSON.stringify({ contact_id: id, action, value }),
    });
    if (r?.ok && r.person) {
      const person = normalize(r.person);
      set({ people: get().people.map((p: Person) => (p.contact_id === id ? person : p)) });
    }
  } catch {
    /* best effort; a refresh re-syncs */
  }
}

export const usePeopleStore = create<PeopleState>((set, get) => ({
  people: [],
  loading: false,
  paired: false,
  loaded: false,

  fetchPeople: async () => {
    const m = target();
    if (!m) {
      set({ paired: false, loaded: true });
      return;
    }
    set({ loading: true, paired: true });
    try {
      const r = await req(m, "/dreamlayer/social/people");
      const people = Array.isArray(r?.people) ? r.people.map(normalize) : [];
      set({ people, loading: false, loaded: true });
    } catch {
      set({ loading: false, loaded: true });
    }
  },

  addNote: (id, note) => edit(set, get, id, "note", note),
  removeNote: (id, note) => edit(set, get, id, "remove_note", note),
  setRelation: (id, relation) => edit(set, get, id, "relation", relation),
  settle: (id) => edit(set, get, id, "settle"),
}));
