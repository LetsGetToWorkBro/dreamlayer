/** Look store action: a phone photo → the World-lens panel via /brain/look. */
import { useBrainStore } from "../state/useBrainStore";

const CONNECTED = { connected: true, url: "http://mac.local", token: "t" };

beforeEach(() => {
  useBrainStore.setState({
    macMini: { connected: false, url: "", token: "" },
    demoMode: false, capturePaused: false,   // Veil open by default; a test opts in
  } as never);
  (global as unknown as { fetch?: unknown }).fetch = undefined;
});

function mockFetch(payload: unknown) {
  const fn = jest.fn().mockResolvedValue({ json: async () => payload, status: 200 });
  (global as unknown as { fetch: unknown }).fetch = fn;
  return fn;
}

describe("useBrainStore.look", () => {
  it("asks you to pair when no Brain is connected", async () => {
    const res = await useBrainStore.getState().look("b64");
    expect(res.ok).toBe(false);
    expect(res.reason).toMatch(/pair/i);
  });

  it("parses an object panel with provider rows", async () => {
    useBrainStore.setState({ macMini: CONNECTED } as never);
    const fetchFn = mockFetch({
      ok: true, lens: "object",
      panel: {
        primary: "price tag", detail: "EUR",
        rows: [{ label: "$21.60", detail: "€20.00", kind: "stat", source: "currency" }],
        sources: ["currency"], confidence: 0.9,
      },
    });
    const res = await useBrainStore.getState().look("b64");
    expect(fetchFn).toHaveBeenCalled();
    const url = (fetchFn.mock.calls[0]![0] as string);
    expect(url).toContain("/dreamlayer/brain/look");
    expect(res.ok).toBe(true);
    expect(res.title).toBe("price tag");
    expect(res.rows).toHaveLength(1);
    expect(res.rows[0]!.label).toBe("$21.60");
    expect(res.sources).toEqual(["currency"]);
    expect(res.confidence).toBeCloseTo(0.9);
  });

  it("surfaces an honest reason when the Brain couldn't see", async () => {
    useBrainStore.setState({ macMini: CONNECTED } as never);
    mockFetch({ ok: false, reason: "couldn't make it out" });
    const res = await useBrainStore.getState().look("b64");
    expect(res.ok).toBe(false);
    expect(res.reason).toMatch(/make it out/i);
    expect(res.rows).toEqual([]);
  });

  it("carries the veil flag through", async () => {
    useBrainStore.setState({ macMini: CONNECTED } as never);
    mockFetch({ ok: false, veiled: true, reason: "Incognito — Juno isn't looking." });
    const res = await useBrainStore.getState().look("b64");
    expect(res.ok).toBe(false);
    expect(res.veiled).toBe(true);
  });

  it("refuses to send the photo when the Veil is closed", async () => {
    // capture paused / incognito / glasses Veil raised → the phone must NOT ship
    // the photo (enforce, don't trust the Brain's separate posture).
    useBrainStore.setState({ macMini: CONNECTED, capturePaused: true } as never);
    const fetchFn = mockFetch({ ok: true, panel: { rows: [] } });
    const res = await useBrainStore.getState().look("b64");
    expect(fetchFn).not.toHaveBeenCalled();   // REVERT-FAILING: nothing past the Veil
    expect(res.ok).toBe(false);
    expect(res.veiled).toBe(true);
  });

  it("filters malformed (non-object) rows instead of crashing", async () => {
    useBrainStore.setState({ macMini: CONNECTED } as never);
    mockFetch({ ok: true, panel: { rows: [null, { label: "real" }, 42], sources: [] } });
    const res = await useBrainStore.getState().look("b64");
    expect(res.ok).toBe(true);
    expect(res.rows).toEqual([{ label: "real" }]);   // null + 42 dropped, no crash
  });

  it("returns a demo panel in demo mode without a Brain", async () => {
    useBrainStore.setState({ demoMode: true } as never);
    const res = await useBrainStore.getState().look("b64");
    expect(res.ok).toBe(true);
    expect(res.rows.length).toBeGreaterThan(0);
  });
});
