/** HaloBridge over a fake transport: send framing, inbound routing, and the
 * reconnect state machine surviving drop storms. */
import { HaloBridge, type BleTransport } from "../ble/bridge";
import { framePayload } from "../ble/framing";

class FakeTransport implements BleTransport {
  written: Uint8Array[] = [];
  private notify: ((c: Uint8Array) => void) | null = null;
  private onDisc: (() => void) | null = null;
  scanResult: string | null = "halo-1";
  connectShouldFail = false;
  connectCalls = 0;

  async scan(): Promise<string | null> {
    return this.scanResult;
  }
  async connect(): Promise<void> {
    this.connectCalls += 1;
    if (this.connectShouldFail) throw new Error("no glasses");
  }
  async write(chunk: Uint8Array): Promise<void> {
    this.written.push(chunk);
  }
  onNotify(cb: (c: Uint8Array) => void): void {
    this.notify = cb;
  }
  onDisconnect(cb: () => void): void {
    this.onDisc = cb;
  }
  async disconnect(): Promise<void> {}

  // test helpers
  deliver(bytes: Uint8Array): void {
    this.notify?.(bytes);
  }
  dropLink(): void {
    this.onDisc?.();
  }
}

describe("HaloBridge", () => {
  it("connects via the transport and reports state", async () => {
    const t = new FakeTransport();
    const states: string[] = [];
    const b = new HaloBridge(t, { onState: (s) => states.push(s) });
    const id = await b.connect();
    expect(id).toBe("halo-1");
    expect(b.state).toBe("connected");
    expect(states).toEqual(["scanning", "connected"]);
  });

  it("returns null when nothing is found", async () => {
    const t = new FakeTransport();
    t.scanResult = null;
    const b = new HaloBridge(t);
    expect(await b.connect()).toBeNull();
    expect(b.state).toBe("disconnected");
  });

  it("frames + chunks on send", async () => {
    const t = new FakeTransport();
    const b = new HaloBridge(t, {}, 16);
    await b.connect();
    await b.send({ t: "card", payload: { text: "hello world ".repeat(4) } });
    const joined = new Uint8Array(t.written.reduce((n, c) => n + c.length, 0));
    let off = 0;
    for (const c of t.written) {
      expect(c.length).toBeLessThanOrEqual(16);
      joined.set(c, off);
      off += c.length;
    }
    expect(Array.from(joined)).toEqual(Array.from(framePayload({ t: "card", payload: { text: "hello world ".repeat(4) } })));
  });

  it("routes inbound cards / acks / telemetry by type", async () => {
    const t = new FakeTransport();
    const cards: unknown[] = [];
    const acks: unknown[] = [];
    const tels: unknown[] = [];
    const b = new HaloBridge(t, {
      onCard: (c) => cards.push(c),
      onFigmentAck: (a) => acks.push(a),
      onTelemetry: (x) => tels.push(x),
    });
    await b.connect();
    t.deliver(framePayload({ t: "card", card_type: "ReadyCard" }));
    t.deliver(framePayload({ t: "figment_ack", id: "f1", ok: true }));
    t.deliver(framePayload({ t: "TEL", event: "CARD_SHOWN" }));
    expect(cards).toHaveLength(1);
    expect(acks).toHaveLength(1);
    expect(tels).toHaveLength(1);
  });

  it("enters reconnecting on a link drop and recovers", async () => {
    jest.useFakeTimers();
    const t = new FakeTransport();
    const states: string[] = [];
    const b = new HaloBridge(t, { onState: (s) => states.push(s) });
    await b.connect();
    t.dropLink();
    expect(b.state).toBe("reconnecting");
    await jest.runOnlyPendingTimersAsync();     // first backoff → reconnect succeeds
    expect(b.state).toBe("connected");
    jest.useRealTimers();
  });

  it("keeps retrying through a drop storm without wedging", async () => {
    jest.useFakeTimers();
    const t = new FakeTransport();
    const b = new HaloBridge(t);
    await b.connect();
    t.connectShouldFail = true;
    t.dropLink();
    for (let i = 0; i < 4; i++) await jest.runOnlyPendingTimersAsync();
    expect(b.state).toBe("reconnecting");       // still trying, not dead
    t.connectShouldFail = false;
    await jest.runOnlyPendingTimersAsync();
    expect(b.state).toBe("connected");          // recovers when the radio returns
    jest.useRealTimers();
  });

  it("stops retrying after an explicit disconnect", async () => {
    const t = new FakeTransport();
    const b = new HaloBridge(t);
    await b.connect();
    await b.disconnect();
    t.dropLink();
    expect(b.state).toBe("disconnected");       // not reconnecting
  });
});
