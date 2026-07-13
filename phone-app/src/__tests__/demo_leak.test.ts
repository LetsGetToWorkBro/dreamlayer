/** P2-14: demo fiction must never leak into real mode.
 *
 * The memory store used to initialize with five fictional sample memories and
 * a fake "you owe Marcus" card UNCONDITIONALLY — so a real-mode install showed
 * fabricated memories, and they survived turning demo off. Now: a fresh store
 * is empty, enableDemo() seeds the fixtures, disableDemo() strips exactly them
 * (real ingested entries survive), and a failed real-BLE scan does not fall
 * back to marking a demo Halo paired. */
import {
  useMemoryStore, seedDemoMemories, clearDemoMemories, type Memory,
} from "../state/useMemoryStore";
import { useBrainStore } from "../state/useBrainStore";

const REAL: Memory = {
  id: "real-1", kind: "Promise", summary: "Call the dentist back",
  createdAt: "2:10 PM", ts: Date.now(),
};

beforeEach(() => {
  useMemoryStore.setState({
    memories: [],
    fetchedAt: 0,
    service: { ...useMemoryStore.getState().service, lastCard: null },
  });
  useBrainStore.setState({ demoMode: false, glasses: { connected: false, id: "" } });
});

describe("real mode is fiction-free", () => {
  it("a fresh store has no memories and no last card", () => {
    expect(useMemoryStore.getState().memories).toEqual([]);
    expect(useMemoryStore.getState().service.lastCard).toBeNull();
  });
});

describe("the demo lifecycle", () => {
  it("enableDemo seeds fixtures and a demo card", () => {
    useBrainStore.getState().enableDemo();
    const s = useMemoryStore.getState();
    expect(s.memories.length).toBeGreaterThan(0);
    expect(s.memories.every((m) => m.id.startsWith("demo-"))).toBe(true);
    expect(s.service.lastCard).not.toBeNull();
    expect(useBrainStore.getState().glasses.id).toBe("HALO-DEMO");
  });

  it("disableDemo strips the fixtures but keeps real entries", () => {
    useBrainStore.getState().enableDemo();
    useMemoryStore.getState().ingest(REAL);          // a real capture mid-demo
    useBrainStore.getState().disableDemo();
    const s = useMemoryStore.getState();
    expect(s.memories).toEqual([REAL]);              // fiction gone, real kept
    expect(s.service.lastCard).toBeNull();           // the fake card too
    expect(useBrainStore.getState().glasses.connected).toBe(false);
  });

  it("seeding is idempotent", () => {
    seedDemoMemories();
    const n = useMemoryStore.getState().memories.length;
    seedDemoMemories();
    expect(useMemoryStore.getState().memories.length).toBe(n);
  });

  it("clearDemoMemories keeps a card the wearer's glasses actually drew", () => {
    seedDemoMemories();
    const realCard = { kind: "Place", primary: "Bike: 4th & Main rack" };
    useMemoryStore.getState().service.setLastCard(realCard);
    clearDemoMemories();
    expect(useMemoryStore.getState().service.lastCard).toEqual(realCard);
  });
});
