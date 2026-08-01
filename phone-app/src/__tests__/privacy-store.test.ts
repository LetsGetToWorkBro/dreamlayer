/**
 * The shields, on the device that can actually raise them.
 *
 * Private zones, quiet hours, retention and the two biometric recalls were
 * reachable only from the Mac's own web panel. For private zones that made the
 * feature close to unusable — a zone is created at the CURRENT POSITION and the
 * Mac does not move — so the phone is the only device that can honestly offer
 * it, and these tests are about the four ways a client could get that wrong:
 *
 *   1. placing a zone from a stale fix, or from no fix at all;
 *   2. holding, or showing, the coordinates of the places you call private;
 *   3. turning a biometric on without a recorded consent, or recording consent
 *      against words the wearer never saw;
 *   4. drawing a missing recogniser, or an unreachable Brain, as "off".
 */
import { usePrivacyStore, NO_BIOMETRIC } from "../state/usePrivacyStore";
import { useBrainStore } from "../state/useBrainStore";

jest.mock("../services/location", () => ({
  markHere: jest.fn(async () => true),
}));
// eslint-disable-next-line @typescript-eslint/no-var-requires
const location = require("../services/location");

const st = () => usePrivacyStore.getState();

const CONFIG = { quiet_hours: "22:00-07:00", retention_days: 30 };
const ZONES = {
  zones: [
    { name: "the flat", radius_m: 150, lat: 51.5074, lon: -0.1278, inside: true },
    { name: "the clinic", radius_m: 80, lat: 51.51, lon: -0.13, inside: false },
  ],
  max: 8,
  has_fix: true,
};
const WHERE = { has_fix: true, zone: "the flat", veiled: true, zones: 2 };
const FACE = {
  enabled: true, model: true, ambient: true, consented: true,
  consent_version: "2026-07-01", auto_enrol: false, enrolled: 4, unnamed: 1,
  consent_text: "Face recall stores a mathematical template of a face…",
};
const VOICE = {
  enabled: false, model: true, consented: false, consent_version: "2026-06-02",
  auto_enrol: false, enrolled: 0, unnamed: 0,
  consent_text: "A voiceprint is the biometric itself…",
};

function routed(over: Record<string, unknown> = {}) {
  const table: Record<string, unknown> = {
    "/dreamlayer/config": { config: CONFIG },
    "/dreamlayer/zones": ZONES,
    "/dreamlayer/where": WHERE,
    "/dreamlayer/face": FACE,
    "/dreamlayer/voice": VOICE,
    ...over,
  };
  return jest.fn((url: string, opts?: RequestInit) => {
    if (opts?.method === "POST") return Promise.resolve({ json: async () => ({ ok: true, config: CONFIG }) });
    const key = Object.keys(table).find((k) => String(url).includes(k));
    return Promise.resolve({ json: async () => (key ? table[key] : {}) });
  });
}

beforeEach(() => {
  (location.markHere as jest.Mock).mockClear();
  (location.markHere as jest.Mock).mockResolvedValue(true);
  useBrainStore.setState({
    macMini: { connected: true, url: "http://mac:8765", token: "t", relayUrl: "" },
  } as never);
  usePrivacyStore.setState({
    loaded: false, reachable: false, lastError: "",
    zones: [], maxZones: 0, hasFix: false, insideZone: "", veiled: false,
    quietHours: "", retentionDays: 0,
    faces: { ...NO_BIOMETRIC }, voices: { ...NO_BIOMETRIC },
  });
});

describe("a private zone is where you are standing", () => {
  it("takes a FRESH fix before placing one", async () => {
    /* `startReporting` sends nothing while the phone is stationary — and
       standing still in the room you want silenced is exactly the moment this
       is used. Without a one-shot report the Brain places the zone wherever
       the last movement happened to be. */
    (global as never as { fetch: unknown }).fetch = routed();
    await st().refresh();
    const r = await st().addZoneHere("the studio");
    expect(location.markHere).toHaveBeenCalled();
    expect(r.ok).toBe(true);
  });

  it("refuses rather than placing a zone somewhere it is guessing", async () => {
    (location.markHere as jest.Mock).mockResolvedValue(false);
    (global as never as { fetch: unknown }).fetch = routed({
      "/dreamlayer/zones": { ...ZONES, has_fix: false },
    });
    await st().refresh();
    const r = await st().addZoneHere("the studio");
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/don’t know where you are/i);
  });

  it("will not make a nameless zone", async () => {
    (global as never as { fetch: unknown }).fetch = routed();
    const r = await st().addZoneHere("   ");
    expect(r.ok).toBe(false);
    expect(location.markHere).not.toHaveBeenCalled();
  });

  it("never holds the coordinate of a place you call private", async () => {
    /* `/dreamlayer/zones` returns lat/lon so the Brain can compute membership;
       `/dreamlayer/where` deliberately returns only the NAME. This store keeps
       the stricter of the two — a list of the exact locations you consider
       private is a worse artefact than the thing it protects you from. */
    (global as never as { fetch: unknown }).fetch = routed();
    await st().refresh();
    expect(st().zones).toEqual([
      { name: "the flat", radiusM: 150, inside: true },
      { name: "the clinic", radiusM: 80, inside: false },
    ]);
    expect(JSON.stringify(st().zones)).not.toContain("51.5");
    expect(JSON.stringify(st().zones)).not.toContain("0.12");
  });

  it("carries which zone you are inside, and that the shield is up", async () => {
    (global as never as { fetch: unknown }).fetch = routed();
    await st().refresh();
    expect(st().insideZone).toBe("the flat");
    expect(st().veiled).toBe(true);
    expect(st().maxZones).toBe(8);
  });
});

describe("consent gates the switch, not just the capture", () => {
  it("refuses to turn recognition on without a recorded agreement", async () => {
    (global as never as { fetch: unknown }).fetch = routed();
    await st().refresh();
    expect(st().voices.consented).toBe(false);
    const ok = await st().setBiometric("voices", "enabled", true);
    expect(ok).toBe(false);
    expect(st().lastError).toBe("consent-required");
    expect(st().voices.enabled).toBe(false);
  });

  it("allows it once consent is on record", async () => {
    (global as never as { fetch: unknown }).fetch = routed();
    await st().refresh();
    expect(st().faces.consented).toBe(true);
    const ok = await st().setBiometric("faces", "enabled", true);
    expect(ok).toBe(true);
  });

  it("records the agreement against the VERSION the Brain reported", async () => {
    /* The acceptance names the words that were on screen. Accepting a version
       this client invented would make the receipt meaningless. */
    const f = routed();
    (global as never as { fetch: unknown }).fetch = f;
    await st().refresh();
    await st().setConsent("voices", true);
    const post = f.mock.calls.find(
      (c) => String(c[0]).includes("/voice/consent") && (c[1] as RequestInit)?.method === "POST");
    expect(JSON.parse(String((post![1] as RequestInit).body)))
      .toEqual({ accept: true, version: "2026-06-02" });
  });

  it("withdraws without echoing a version back", async () => {
    const f = routed();
    (global as never as { fetch: unknown }).fetch = f;
    await st().refresh();
    await st().setConsent("faces", false);
    const post = f.mock.calls.find(
      (c) => String(c[0]).includes("/face/consent") && (c[1] as RequestInit)?.method === "POST");
    expect(JSON.parse(String((post![1] as RequestInit).body))).toEqual({ accept: false });
  });

  it("carries the consent text verbatim rather than paraphrasing it", async () => {
    (global as never as { fetch: unknown }).fetch = routed();
    await st().refresh();
    expect(st().faces.consentText).toBe(FACE.consent_text);
    expect(st().voices.consentText).toBe(VOICE.consent_text);
  });
});

describe("missing is not off", () => {
  it("reports an unavailable recogniser as unavailable, not switched off", async () => {
    (global as never as { fetch: unknown }).fetch = routed({
      "/dreamlayer/voice": { available: false, error: "voice recall unavailable" },
    });
    await st().refresh();
    expect(st().voices.available).toBe(false);
    expect(st().faces.available).toBe(true);
  });

  it("does not invent an ambient restriction for voices, which have none", async () => {
    /* Faces report `ambient`; voices have no such term. Defaulting it to false
       there would draw a legal restriction that does not exist. */
    (global as never as { fetch: unknown }).fetch = routed();
    await st().refresh();
    expect(st().voices.ambient).toBe(true);
    expect(st().faces.ambient).toBe(true);
  });

  it("reports unreachable rather than a set of lowered shields", async () => {
    (global as never as { fetch: unknown }).fetch = jest.fn(() => Promise.reject(new Error("down")));
    await st().refresh();
    expect(st().loaded).toBe(true);
    expect(st().reachable).toBe(false);
  });
});

describe("quiet hours and retention write the Brain's own keys", () => {
  it("posts quiet_hours", async () => {
    const f = routed();
    (global as never as { fetch: unknown }).fetch = f;
    await st().setQuietHours("23:00-06:30");
    const post = f.mock.calls.find(
      (c) => String(c[0]).includes("/dreamlayer/config") && (c[1] as RequestInit)?.method === "POST");
    expect(JSON.parse(String((post![1] as RequestInit).body))).toEqual({ quiet_hours: "23:00-06:30" });
  });

  it("posts retention_days", async () => {
    const f = routed();
    (global as never as { fetch: unknown }).fetch = f;
    await st().setRetentionDays(90);
    const post = f.mock.calls.find(
      (c) => String(c[0]).includes("/dreamlayer/config") && (c[1] as RequestInit)?.method === "POST");
    expect(JSON.parse(String((post![1] as RequestInit).body))).toEqual({ retention_days: 90 });
  });

  it("says NOT SAVED rather than moving on a refusal", async () => {
    /* The Brain type-checks config writes: `{"quiet_hours": 5}` used to be
       stored and then break every status read. A refusal must surface. */
    (global as never as { fetch: unknown }).fetch = jest.fn((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST") return Promise.resolve({ json: async () => ({ error: "quiet_hours must be str" }) });
      if (String(url).includes("/config")) return Promise.resolve({ json: async () => ({ config: CONFIG }) });
      if (String(url).includes("/zones")) return Promise.resolve({ json: async () => ZONES });
      if (String(url).includes("/where")) return Promise.resolve({ json: async () => WHERE });
      if (String(url).includes("/face")) return Promise.resolve({ json: async () => FACE });
      return Promise.resolve({ json: async () => VOICE });
    });
    const ok = await st().setQuietHours("nonsense");
    expect(ok).toBe(false);
    expect(st().lastError).toMatch(/must be str/);
    expect(st().quietHours).toBe("22:00-07:00");
  });
});
