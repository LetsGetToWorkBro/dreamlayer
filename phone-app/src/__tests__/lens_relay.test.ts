/** The lens relay closes the glass → Brain → glass loop on the phone side:
 *  - the bridge routes a device `figment_event` to onFigmentEmit
 *  - emitLens/feedLens POST to the Brain's /rc/emit and /rc/feed
 *  - the relay service forwards emits (with the spoken question for "ask")
 *    and streams host text into the running lens's {slot}
 */
import { HaloBridge, type BleTransport } from "../ble/bridge";
import { framePayload } from "../ble/framing";
import { useBrainStore } from "../state/useBrainStore";
import { relayEmit, feed, setQuestionProvider } from "../services/lensRelay";

class FakeTransport implements BleTransport {
  private notify: ((c: Uint8Array) => void) | null = null;
  async scan(): Promise<string | null> { return "halo-1"; }
  async connect(): Promise<void> {}
  async write(): Promise<void> {}
  onNotify(cb: (c: Uint8Array) => void): void { this.notify = cb; }
  onDisconnect(): void {}
  async disconnect(): Promise<void> {}
  deliver(bytes: Uint8Array): void { this.notify?.(bytes); }
}

const brain = () => useBrainStore.getState();

type Call = { url: string; body: unknown };
let calls: Call[];

function mockBrain(reply: Record<string, unknown>) {
  calls = [];
  (global as any).fetch = jest.fn((url: string, opts: RequestInit) => {
    calls.push({ url, body: JSON.parse(String(opts.body || "{}")) });
    return Promise.resolve({ json: () => Promise.resolve(reply) } as Response);
  });
}

beforeEach(() => {
  useBrainStore.setState({
    macMini: { connected: true, url: "http://10.0.0.9:7777", token: "t", relayUrl: "" },
    demoMode: false,
  });
  setQuestionProvider(() => "");
});

describe("bridge routes a lens emit", () => {
  it("delivers figment_event as an onFigmentEmit", () => {
    const t = new FakeTransport();
    const emits: Array<{ tag: string }> = [];
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const _b = new HaloBridge(t, { onFigmentEmit: (e) => emits.push(e) });
    t.deliver(framePayload({ t: "figment_event", id: "abc", tag: "ask" }));
    expect(emits).toEqual([{ id: "abc", tag: "ask" }]);
  });

  it("ignores a malformed emit with no tag", () => {
    const t = new FakeTransport();
    const emits: unknown[] = [];
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const _b = new HaloBridge(t, { onFigmentEmit: (e) => emits.push(e) });
    t.deliver(framePayload({ t: "figment_event", id: "abc" }));
    expect(emits).toEqual([]);
  });
});

describe("feedLens streams host text into the slot", () => {
  it("POSTs the text to /dreamlayer/rc/feed", async () => {
    mockBrain({ ok: true, text: "Hola" });
    const ok = await brain().feedLens("Hola", "translate");
    expect(ok).toBe(true);
    expect(calls[0]!.url).toContain("/dreamlayer/rc/feed");
    expect(calls[0]!.body).toMatchObject({ text: "Hola", source: "translate" });
  });

  it("no-ops with no Brain paired", async () => {
    useBrainStore.setState({ macMini: { connected: false, url: "", token: "" } });
    (global as any).fetch = jest.fn();
    expect(await brain().feedLens("Hola")).toBe(false);
    expect((global as any).fetch).not.toHaveBeenCalled();
  });
});

describe("emitLens closes the ask loop", () => {
  it("POSTs the tag + question and returns the Brain's answer", async () => {
    mockBrain({ ok: true, tag: "ask", answer: "Lease due Fri", tier: "device" });
    const r = await brain().emitLens("ask", "when is my lease due?");
    expect(calls[0]!.url).toContain("/dreamlayer/rc/emit");
    expect(calls[0]!.body).toMatchObject({ tag: "ask", text: "when is my lease due?" });
    expect(r).toMatchObject({ text: "Lease due Fri", tier: "device" });
  });

  it("returns null when the Brain is unreachable", async () => {
    (global as any).fetch = jest.fn(() => Promise.reject(new Error("offline")));
    expect(await brain().emitLens("ask", "hi")).toBeNull();
  });
});

describe("relay service forwards to the Brain", () => {
  it("relayEmit('ask') carries the provided question", async () => {
    mockBrain({ ok: true, tag: "ask", answer: "42", tier: "cloud" });
    setQuestionProvider(() => "meaning of life?");
    const r = await relayEmit({ tag: "ask", id: "z" });
    expect(calls[0]!.body).toMatchObject({ tag: "ask", text: "meaning of life?" });
    expect(r?.text).toBe("42");
  });

  it("relayEmit passes non-ask tags through with no question", async () => {
    mockBrain({ ok: true, tag: "look", text: "Monstera" });
    await relayEmit({ tag: "look" });
    expect(calls[0]!.body).toMatchObject({ tag: "look", text: "" });
  });

  it("feed() streams a line into the lens", async () => {
    mockBrain({ ok: true, text: "You sat here with Dad" });
    expect(await feed("You sat here with Dad", "memory")).toBe(true);
    expect(calls[0]!.url).toContain("/dreamlayer/rc/feed");
  });

  it("relayEmit ignores an empty tag", async () => {
    (global as any).fetch = jest.fn();
    expect(await relayEmit({ tag: "" })).toBeNull();
    expect((global as any).fetch).not.toHaveBeenCalled();
  });

  it("the Veil silences captured content at the relay chokepoint", async () => {
    // Audit 2026-07-14: the phone must ENFORCE the veil, not trust upstream ASR.
    // With capture paused (Veil/incognito), a spoken 'ask' and host feed text
    // never reach the Brain.
    (global as any).fetch = jest.fn();
    useBrainStore.setState({ capturePaused: true });
    setQuestionProvider(() => "a private question");
    expect(await relayEmit({ tag: "ask", id: "z" })).toBeNull();
    expect(await feed("translated overheard speech", "whisper")).toBe(false);
    expect((global as any).fetch).not.toHaveBeenCalled();
    // an inert non-capture lens tag still passes (carries no captured payload)
    mockBrain({ ok: true, tag: "look", text: "Monstera" });
    useBrainStore.setState({ capturePaused: true });
    await relayEmit({ tag: "look" });
    expect(calls.length).toBe(1);
  });
});
