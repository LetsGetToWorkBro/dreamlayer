/** Ember on the phone — the thin client honors the practice's contracts:
 *  - refresh() pulls cue+curve from the Brain; ANSWERS never arrive or persist
 *  - tend() posts the morning choice; the 3-keeps cap holds in demo too
 *  - burn() requires literal consent === true and posts it explicitly
 */
import { useBrainStore } from "../state/useBrainStore";
import { useEmberStore } from "../state/useEmberStore";
import { demoEmber } from "../demo/fixtures";

type Call = { url: string; body: unknown };
let calls: Call[];

function mockBrain(reply: Record<string, unknown>) {
  calls = [];
  (global as any).fetch = jest.fn((url: string, opts: RequestInit = {}) => {
    calls.push({ url, body: JSON.parse(String(opts.body || "{}")) });
    return Promise.resolve({ json: () => Promise.resolve(reply) } as Response);
  });
}

const RESET = {
  loaded: false, reachable: false, status: {}, candidates: [],
  engrams: [], offers: [], keptToday: 0,
};

beforeEach(() => {
  useEmberStore.setState({ ...RESET });
  useBrainStore.setState({
    macMini: { connected: true, url: "http://10.0.0.9:7777", token: "t", relayUrl: "" },
    demoMode: false,
  } as any);
});

describe("refresh", () => {
  it("pulls the practice from GET /dreamlayer/ember", async () => {
    mockBrain({ ok: true, exists: true, status: { tended: 1 },
                candidates: [], engrams: demoEmber.engrams, offers: [] });
    await useEmberStore.getState().refresh();
    const s = useEmberStore.getState();
    expect(calls[0]!.url).toContain("/dreamlayer/ember");
    expect(s.reachable).toBe(true);
    expect(s.engrams.length).toBe(3);
  });

  it("never holds an answer field — the phone can't leak what it never has", async () => {
    mockBrain({ ok: true, exists: true, status: {}, candidates: demoEmber.candidates,
                engrams: demoEmber.engrams, offers: demoEmber.offers });
    await useEmberStore.getState().refresh();
    const s = useEmberStore.getState();
    for (const e of [...s.engrams, ...s.offers]) {
      expect((e as any).answer).toBeUndefined();
    }
  });

  it("an unreachable Brain reads as unreachable, not as empty truth", async () => {
    (global as any).fetch = jest.fn(() => Promise.reject(new Error("down")));
    await useEmberStore.getState().refresh();
    expect(useEmberStore.getState().reachable).toBe(false);
  });
});

describe("tend", () => {
  it("posts the morning choice", async () => {
    mockBrain({ ok: true, exists: true, status: {}, candidates: [], engrams: [], offers: [] });
    await useEmberStore.getState().tend(7, true);
    expect(calls[0]!.url).toContain("/dreamlayer/ember/tend");
    expect(calls[0]!.body).toEqual({ candidate_id: 7, keep: true });
  });

  it("demo ritual caps keeps at 3 — a ritual, not an inbox", async () => {
    useBrainStore.setState({ demoMode: true } as any);
    useEmberStore.setState({
      ...RESET, loaded: true, reachable: true,
      candidates: [1, 2, 3, 4].map((id) => ({
        id, kind: "memory", summary: `moment ${id}`, cue: `cue ${id}`, salience: 1,
      })),
    });
    const st = useEmberStore.getState();
    expect(await st.tend(1, true)).toBe(true);
    expect(await st.tend(2, true)).toBe(true);
    expect(await st.tend(3, true)).toBe(true);
    expect(await useEmberStore.getState().tend(4, true)).toBe(false);
    expect(useEmberStore.getState().engrams.length).toBe(3);
  });
});

describe("burn", () => {
  it("refuses anything but literal consent === true, and posts it", async () => {
    mockBrain({ ok: true });
    expect(await useEmberStore.getState().burn(13, false)).toBe(false);
    expect(await useEmberStore.getState().burn(13, "yes" as any)).toBe(false);
    expect(calls.length).toBe(0);

    await useEmberStore.getState().burn(13, true);
    expect(calls[0]!.url).toContain("/dreamlayer/ember/burn");
    expect(calls[0]!.body).toEqual({ engram_id: 13, consent: true });
  });
});
