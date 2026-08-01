/**
 * usePrivacyStore — the shields, on the device that can actually raise them.
 *
 * Private zones, quiet hours, retention, and the two biometric recalls (faces
 * and voices) were reachable only from the Mac's own web panel. For most of
 * them that is merely inconvenient. For PRIVATE ZONES it makes the feature
 * close to unusable, because a zone is created at the CURRENT POSITION and the
 * Mac does not move: "mark this room as private" from the panel means carrying
 * the Brain into the room. The phone is the only device in the product that
 * knows where the wearer is, so it is the only one that can honestly offer it.
 *
 * What this client will not do
 * ----------------------------
 * * NEVER SHOW A COORDINATE. `/dreamlayer/zones` returns lat/lon so the Brain
 *   can compute membership; `/dreamlayer/where` deliberately returns only the
 *   zone NAME and whether the shield is up. This store follows the stricter of
 *   the two — a screen listing the exact coordinates of the places you consider
 *   private is a worse artefact than the thing it protects you from.
 * * NEVER SYNTHESISE CONSENT. The face and voice consent text is fetched from
 *   the Brain and rendered verbatim, because the acceptance is recorded against
 *   a VERSION of those exact words. A client that paraphrased them would be
 *   recording agreement to something the wearer never read.
 * * NEVER CALL A MISSING MODEL "OFF". `model: false` means no recogniser is
 *   installed; a switch drawn as merely off would send the wearer looking for
 *   the setting they had already found.
 */
import { create } from "zustand";
import { useBrainStore } from "./useBrainStore";
import { markHere } from "../services/location";

type MacTarget = { url: string; token: string; relayUrl?: string };

function target(): MacTarget | null {
  const m = useBrainStore.getState().macMini;
  return m.connected && m.url ? { url: m.url, token: m.token, relayUrl: m.relayUrl } : null;
}

async function req(m: MacTarget, path: string, opts: RequestInit = {}): Promise<any> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (m.token) headers["X-DreamLayer-Token"] = m.token;
  const o: RequestInit = { ...opts, headers };
  try {
    return await (await fetch(m.url + path, o)).json();
  } catch (e) {
    if (m.relayUrl) return await (await fetch(m.relayUrl + path, o)).json();
    throw e;
  }
}

/** A zone as this app is willing to hold it: the name, how big, and whether you
 *  are standing in it. The coordinate is dropped on arrival — see the header. */
export type Zone = { name: string; radiusM: number; inside: boolean };

/** A biometric recall, faces or voices. One shape for both because the two
 *  hosts already report the same facts, and a second shape would be a second
 *  place for the consent rules to drift. */
export type Biometric = {
  /** the wearer's switch */
  enabled: boolean;
  /** a recogniser is genuinely installed — not the same as "on" */
  model: boolean;
  /** consent has been recorded against `consentVersion` */
  consented: boolean;
  consentVersion: string;
  /** the exact words the acceptance is recorded against */
  consentText: string;
  /** enrol on sight, without being asked each time */
  autoEnrol: boolean;
  enrolled: number;
  /** stored identities belonging to people who never gave a name */
  unnamed: number;
  /** faces only: whether ambient recognition is permitted in this jurisdiction */
  ambient: boolean;
  /** the host could not be built at all (missing extra, no store) */
  available: boolean;
};

export const NO_BIOMETRIC: Biometric = {
  enabled: false, model: false, consented: false, consentVersion: "",
  consentText: "", autoEnrol: false, enrolled: 0, unnamed: 0,
  ambient: false, available: false,
};

function biometric(raw: any): Biometric {
  if (!raw || raw.available === false) return { ...NO_BIOMETRIC };
  return {
    enabled: !!raw.enabled,
    model: !!raw.model,
    consented: !!raw.consented,
    consentVersion: String(raw.consent_version || ""),
    consentText: String(raw.consent_text || ""),
    autoEnrol: !!raw.auto_enrol,
    enrolled: Number(raw.enrolled || 0),
    unnamed: Number(raw.unnamed || 0),
    // Faces report `ambient`; voices have no such term, and defaulting it to
    // false there would draw a restriction that does not exist. Absent means
    // "not a question for this one", which reads as permitted.
    ambient: raw.ambient === undefined ? true : !!raw.ambient,
    available: true,
  };
}

export type PrivacyState = {
  loaded: boolean;
  reachable: boolean;
  lastError: string;

  zones: Zone[];
  maxZones: number;
  /** the Brain has a position report fresh enough to place a zone with */
  hasFix: boolean;
  /** the zone the wearer is inside right now, or "" */
  insideZone: string;
  /** the effective shield: incognito, quiet hours, OR a private zone */
  veiled: boolean;

  quietHours: string;
  retentionDays: number;

  faces: Biometric;
  voices: Biometric;

  refresh: () => Promise<void>;
  /** Take a fresh fix from THIS phone and make it a zone. */
  addZoneHere: (name: string, radiusM?: number) => Promise<{ ok: boolean; error: string }>;
  removeZone: (name: string) => Promise<boolean>;
  setQuietHours: (window: string) => Promise<boolean>;
  setRetentionDays: (days: number) => Promise<boolean>;
  setBiometric: (
    which: "faces" | "voices",
    field: "enabled" | "autoEnrol",
    on: boolean,
  ) => Promise<boolean>;
  /** Record or withdraw consent, against the version the Brain reported. */
  setConsent: (which: "faces" | "voices", accept: boolean) => Promise<boolean>;
};

const CONFIG_KEY = {
  faces: { enabled: "face_recognition", autoEnrol: "face_auto_enrol" },
  voices: { enabled: "voice_recognition", autoEnrol: "voice_auto_enrol" },
} as const;

export const usePrivacyStore = create<PrivacyState>((set, get) => ({
  loaded: false,
  reachable: false,
  lastError: "",
  zones: [],
  maxZones: 0,
  hasFix: false,
  insideZone: "",
  veiled: false,
  quietHours: "",
  retentionDays: 0,
  faces: { ...NO_BIOMETRIC },
  voices: { ...NO_BIOMETRIC },

  refresh: async () => {
    const m = target();
    if (!m) {
      set({ loaded: true, reachable: false });
      return;
    }
    try {
      const [cfg, zones, where, face, voice] = await Promise.all([
        req(m, "/dreamlayer/config"),
        req(m, "/dreamlayer/zones").catch(() => null),
        req(m, "/dreamlayer/where").catch(() => null),
        req(m, "/dreamlayer/face").catch(() => null),
        req(m, "/dreamlayer/voice").catch(() => null),
      ]);
      const c = (cfg && cfg.config) || {};
      set({
        loaded: true,
        reachable: true,
        lastError: "",
        zones: ((zones && zones.zones) || []).map((z: any) => ({
          // the coordinate is read and dropped here, deliberately
          name: String(z.name || "this area"),
          radiusM: Number(z.radius_m || 0),
          inside: !!z.inside,
        })),
        maxZones: Number((zones && zones.max) || 0),
        hasFix: !!(zones && zones.has_fix),
        insideZone: String((where && where.zone) || ""),
        veiled: !!(where && where.veiled),
        quietHours: typeof c.quiet_hours === "string" ? c.quiet_hours : "",
        retentionDays: typeof c.retention_days === "number" ? c.retention_days : 0,
        faces: biometric(face),
        voices: biometric(voice),
      });
    } catch {
      set({ loaded: true, reachable: false });
    }
  },

  addZoneHere: async (name, radiusM = 150) => {
    const m = target();
    if (!m) return { ok: false, error: "not-connected" };
    if (!name.trim()) return { ok: false, error: "give it a name" };
    // Post a fresh fix FIRST. `startReporting` sends nothing while the phone is
    // stationary — and standing still in the room you want silenced is exactly
    // the moment this is used — so without this the Brain would place the zone
    // around wherever the last movement happened to be.
    const got = await markHere();
    if (!got && !get().hasFix) {
      return { ok: false, error: "I don’t know where you are yet — allow location and try again" };
    }
    try {
      const r = await req(m, "/dreamlayer/zones", {
        method: "POST",
        body: JSON.stringify({ action: "add", name: name.trim(), radius_m: radiusM }),
      });
      await get().refresh();
      return { ok: !!(r && r.ok), error: String((r && r.error) || "") };
    } catch {
      return { ok: false, error: "unreachable" };
    }
  },

  removeZone: async (name) => {
    const m = target();
    if (!m) return false;
    try {
      const r = await req(m, "/dreamlayer/zones", {
        method: "POST",
        body: JSON.stringify({ action: "remove", name }),
      });
      await get().refresh();
      return !!(r && r.ok);
    } catch {
      return false;
    }
  },

  setQuietHours: async (window) => {
    const m = target();
    if (!m) {
      set({ lastError: "not-connected" });
      return false;
    }
    try {
      const r = await req(m, "/dreamlayer/config", {
        method: "POST",
        body: JSON.stringify({ quiet_hours: window }),
      });
      if (r && r.error) {
        await get().refresh();
        set({ lastError: String(r.error) });
        return false;
      }
      await get().refresh();
      return get().quietHours === window;
    } catch {
      set({ lastError: "unreachable" });
      return false;
    }
  },

  setRetentionDays: async (days) => {
    const m = target();
    if (!m) {
      set({ lastError: "not-connected" });
      return false;
    }
    try {
      const r = await req(m, "/dreamlayer/config", {
        method: "POST",
        body: JSON.stringify({ retention_days: days }),
      });
      if (r && r.error) {
        await get().refresh();
        set({ lastError: String(r.error) });
        return false;
      }
      await get().refresh();
      return get().retentionDays === days;
    } catch {
      set({ lastError: "unreachable" });
      return false;
    }
  },

  setBiometric: async (which, field, on) => {
    const m = target();
    if (!m) {
      set({ lastError: "not-connected" });
      return false;
    }
    // Consent gates the SWITCH, not just the capture: turning face recall on
    // without a recorded acceptance would enrol under terms nobody agreed to.
    // The Brain enforces this too; refusing here means the switch never moves
    // in the first place, which is the honest UI for the same rule.
    if (on && !get()[which].consented) {
      set({ lastError: "consent-required" });
      return false;
    }
    try {
      const r = await req(m, "/dreamlayer/config", {
        method: "POST",
        body: JSON.stringify({ [CONFIG_KEY[which][field]]: on }),
      });
      if (r && r.error) {
        await get().refresh();
        set({ lastError: String(r.error) });
        return false;
      }
      await get().refresh();
      return get()[which][field] === on;
    } catch {
      set({ lastError: "unreachable" });
      return false;
    }
  },

  setConsent: async (which, accept) => {
    const m = target();
    if (!m) return false;
    const path = which === "faces" ? "/dreamlayer/face/consent" : "/dreamlayer/voice/consent";
    try {
      const r = await req(m, path, {
        method: "POST",
        body: JSON.stringify(
          // The version travels back with the acceptance so the record names
          // the words that were on screen. Accepting a version this client
          // invented would make the receipt meaningless.
          accept ? { accept: true, version: get()[which].consentVersion } : { accept: false },
        ),
      });
      await get().refresh();
      return !!(r && r.ok !== false);
    } catch {
      return false;
    }
  },
}));
