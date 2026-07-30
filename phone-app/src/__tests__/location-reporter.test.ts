/**
 * The location reporter — the client the Brain's `POST /dreamlayer/location`
 * never had.
 *
 * Two features are inert without it and BOTH FAIL QUIETLY, which is what makes
 * a test necessary rather than nice: private zones cannot raise the shield
 * without a position, and Waypath refuses to name a direction without a
 * heading. Neither reports an error when the client is missing — they simply
 * behave as they did before, which is exactly the failure mode the reachability
 * audit exists to catch.
 */
import { reportFix, REPORT_DISTANCE_M, REPORT_FLOOR_MS } from "../services/location";
import { useBrainStore } from "../state/useBrainStore";

describe("reportFix", () => {
  afterEach(() => {
    useBrainStore.setState({
      macMini: { connected: false, url: "", token: "", relayUrl: "" },
      demoMode: false,
    } as never);
    jest.restoreAllMocks();
  });

  function connect() {
    useBrainStore.setState({
      macMini: { connected: true, url: "http://192.168.1.9:7171", token: "t", relayUrl: "" },
      demoMode: false,
    } as never);
  }

  it("posts the fix to the Brain", async () => {
    connect();
    const f = jest.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true }),
    });
    (global as never as { fetch: unknown }).fetch = f;
    expect(await reportFix({ lat: 51.5074, lon: -0.1278, accuracy_m: 8 })).toBe(true);
    const [url, opts] = f.mock.calls[0];
    expect(url).toContain("/dreamlayer/location");
    const body = JSON.parse((opts as { body: string }).body);
    expect(body.lat).toBeCloseTo(51.5074);
    expect(body.lon).toBeCloseTo(-0.1278);
  });

  it("sends heading_deg explicitly as null when there is none", async () => {
    // Not omitted: "no heading" has to be on the wire, because the Brain's
    // behaviour differs — it reports a distance instead of inventing a
    // direction from an assumed heading.
    connect();
    const f = jest.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true }),
    });
    (global as never as { fetch: unknown }).fetch = f;
    await reportFix({ lat: 51.5074, lon: -0.1278 });
    const body = JSON.parse((f.mock.calls[0][1] as { body: string }).body);
    expect(body).toHaveProperty("heading_deg");
    expect(body.heading_deg).toBeNull();
  });

  it("passes a real heading through", async () => {
    connect();
    const f = jest.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true }),
    });
    (global as never as { fetch: unknown }).fetch = f;
    await reportFix({ lat: 51.5074, lon: -0.1278, heading_deg: 270 });
    const body = JSON.parse((f.mock.calls[0][1] as { body: string }).body);
    expect(body.heading_deg).toBe(270);
  });

  it("never reports in demo mode", async () => {
    // A demo must not describe a real place, and a zone raised from a fake
    // coordinate would silently gag a real Brain.
    connect();
    useBrainStore.setState({ demoMode: true } as never);
    const f = jest.fn();
    (global as never as { fetch: unknown }).fetch = f;
    expect(await reportFix({ lat: 51.5074, lon: -0.1278 })).toBe(false);
    expect(f).not.toHaveBeenCalled();
  });

  it("does nothing when unpaired", async () => {
    const f = jest.fn();
    (global as never as { fetch: unknown }).fetch = f;
    expect(await reportFix({ lat: 51.5074, lon: -0.1278 })).toBe(false);
    expect(f).not.toHaveBeenCalled();
  });

  it("refuses a non-finite coordinate rather than posting NaN", async () => {
    connect();
    const f = jest.fn();
    (global as never as { fetch: unknown }).fetch = f;
    expect(await reportFix({ lat: NaN, lon: -0.1278 })).toBe(false);
    expect(await reportFix({ lat: 51.5, lon: Infinity })).toBe(false);
    expect(f).not.toHaveBeenCalled();
  });

  it("a dropped report is false, never a throw", async () => {
    // The next fix is 25 m away and the features degrade to "no fix" rather
    // than to wrong answers, so a network blip must not surface.
    connect();
    (global as never as { fetch: unknown }).fetch = jest
      .fn()
      .mockRejectedValue(new Error("offline"));
    await expect(reportFix({ lat: 51.5074, lon: -0.1278 })).resolves.toBe(false);
  });

  it("the floor rate stays well inside the Brain's stale-fix window", () => {
    // The Brain treats a fix older than 600 s as NO fix — deliberately, so a
    // stale one cannot hold a zone's shield up after you drive away. Standing
    // still inside a zone must not expire the shield, so the re-send floor has
    // to leave real headroom under that bound.
    expect(REPORT_FLOOR_MS).toBeLessThan(600_000 / 2);
    expect(REPORT_DISTANCE_M).toBeGreaterThan(0);
  });
});

describe("startReporting", () => {
  it("is a harmless no-op without expo-location", async () => {
    // Expo Go and jest have no expo-location. Callers must need no capability
    // check, and `stop()` on the no-op must be safe.
    const { startReporting } = require("../services/location");
    const r = await startReporting();
    expect(typeof r.stop).toBe("function");
    expect(() => r.stop()).not.toThrow();
  });
});
