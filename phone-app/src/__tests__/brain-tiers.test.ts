/** Brain tiers store (3.1): fetches the ladder, degrades to phone-only. */
import { useBrainTiersStore } from "../state/useBrainTiersStore";
import { useBrainStore } from "../state/useBrainStore";

const RESET = {
  model: "on-device", cloud_provider: "", cloud: false, incognito: false,
  active_tier: "device", tiers: useBrainTiersStore.getState().tiers,
  loaded: false, connected: false,
};

beforeEach(() => {
  useBrainTiersStore.setState(RESET);
  useBrainStore.setState({ macMini: { connected: false, url: "", token: "" } } as never);
});

describe("useBrainTiersStore", () => {
  it("is phone-only with no Mac paired", async () => {
    await useBrainTiersStore.getState().load();
    const s = useBrainTiersStore.getState();
    expect(s.connected).toBe(false);
    expect(s.tiers).toHaveLength(1);
    expect(s.tiers[0]!.id).toBe("device");
    expect(s.tiers[0]!.enabled).toBe(true);   // the phone is always the brain
  });

  it("loads the tier ladder from a paired Brain", async () => {
    useBrainStore.setState({ macMini: { connected: true, url: "http://mac.local", token: "t" } } as never);
    const payload = {
      model: "claude-sonnet-5", cloud_provider: "anthropic", cloud: true,
      incognito: false, active_tier: "device",
      tiers: [
        { id: "device", name: "On-device", note: "", enabled: true, latency_ms: 12, answered: 3, failed: 0, reliability: 1, seen: true },
        { id: "mac_mini", name: "Mac mini", note: "", enabled: true, latency_ms: 90, answered: 5, failed: 1, reliability: 0.83, seen: true },
        { id: "cloud", name: "Cloud", note: "", enabled: true, latency_ms: null, answered: 0, failed: 0, reliability: null, seen: false },
      ],
    };
    const fetchImpl = jest.fn().mockResolvedValue({ json: async () => payload }) as unknown as typeof fetch;
    await useBrainTiersStore.getState().load(fetchImpl);
    const s = useBrainTiersStore.getState();
    expect(s.connected).toBe(true);
    expect(s.model).toBe("claude-sonnet-5");
    expect(s.tiers.map((t) => t.id)).toEqual(["device", "mac_mini", "cloud"]);
    expect(s.tiers[1]!.latency_ms).toBe(90);
    expect(s.active_tier).toBe("device");
  });

  it("degrades to phone-only on a fetch error", async () => {
    useBrainStore.setState({ macMini: { connected: true, url: "http://mac.local", token: "t" } } as never);
    const fetchImpl = jest.fn().mockRejectedValue(new Error("down")) as unknown as typeof fetch;
    await useBrainTiersStore.getState().load(fetchImpl);
    expect(useBrainTiersStore.getState().tiers).toHaveLength(1);
    expect(useBrainTiersStore.getState().loaded).toBe(true);
  });
});
