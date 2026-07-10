/**
 * bridge.ts — HaloBridge: the phone's glasses link, transport-injected.
 *
 * All the logic — MTU chunking on send, streaming reassembly + JSON routing on
 * receive, and a reconnect state machine with backoff — lives here as pure TS
 * over a `BleTransport` interface, so it unit-tests with a fake transport and
 * Expo Go keeps working. The native `react-native-ble-plx` adapter
 * (transport.blePlx.ts) is a thin, inert-until-built shell.
 *
 * The reconnect hysteresis matches useConnectionStore: one blip is not an
 * outage; a success recovers immediately.
 */
import { chunkFrame, framePayload, Reassembler } from "./framing";

export type ConnState = "disconnected" | "scanning" | "connected" | "reconnecting";

/** The seam a real radio fills. Every method is async; onNotify/onDisconnect
 * register callbacks. `write` sends one already-chunked payload. */
export interface BleTransport {
  scan(timeoutMs: number): Promise<string | null>; // returns a device id or null
  connect(deviceId: string): Promise<void>;
  write(chunk: Uint8Array): Promise<void>;
  onNotify(cb: (chunk: Uint8Array) => void): void;
  onDisconnect(cb: () => void): void;
  disconnect(): Promise<void>;
}

export type BridgeEvents = {
  onCard?: (card: Record<string, unknown>) => void;
  onFigmentAck?: (ack: Record<string, unknown>) => void;
  onTelemetry?: (tel: Record<string, unknown>) => void;
  onState?: (state: ConnState) => void;
  onMessage?: (obj: Record<string, unknown>) => void; // anything else
};

export const RECONNECT_BACKOFF_MS = [500, 1000, 2000, 4000, 8000];
export const OFFLINE_AFTER = 2; // consecutive failures before we stop retrying

export class HaloBridge {
  private transport: BleTransport;
  private events: BridgeEvents;
  private reasm = new Reassembler();
  private deviceId: string | null = null;
  private _state: ConnState = "disconnected";
  private _stopped = false;
  private failures = 0;
  private mtu: number;

  constructor(transport: BleTransport, events: BridgeEvents = {}, mtu = 128) {
    this.transport = transport;
    this.events = events;
    this.mtu = mtu;
    this.transport.onNotify((chunk) => this._onChunk(chunk));
    this.transport.onDisconnect(() => this._onDisconnect());
  }

  get state(): ConnState {
    return this._state;
  }

  private _setState(s: ConnState) {
    if (this._state !== s) {
      this._state = s;
      this.events.onState?.(s);
    }
  }

  /** Scan + connect. Returns the connected device id, or null. */
  async connect(scanTimeoutMs = 8000): Promise<string | null> {
    this._stopped = false;
    this._setState("scanning");
    try {
      const id = await this.transport.scan(scanTimeoutMs);
      if (!id) {
        this._setState("disconnected");
        return null;
      }
      await this.transport.connect(id);
      this.deviceId = id;
      this.failures = 0;
      this.reasm.reset();
      this._setState("connected");
      return id;
    } catch {
      this._setState("disconnected");
      return null;
    }
  }

  /** Frame + chunk + send an object. Throws only if the transport does. */
  async send(obj: unknown): Promise<void> {
    const chunks = chunkFrame(framePayload(obj), this.mtu);
    for (const c of chunks) await this.transport.write(c);
  }

  async disconnect(): Promise<void> {
    this._stopped = true;
    try {
      await this.transport.disconnect();
    } finally {
      this._setState("disconnected");
    }
  }

  // -- inbound ---------------------------------------------------------------

  private _onChunk(chunk: Uint8Array): void {
    for (const obj of this.reasm.feed(chunk)) {
      this._route(obj as Record<string, unknown>);
    }
  }

  private _route(obj: Record<string, unknown>): void {
    const t = obj.t;
    if (t === "card") this.events.onCard?.(obj);
    else if (t === "figment_ack") this.events.onFigmentAck?.(obj);
    else if (t === "TEL") this.events.onTelemetry?.(obj);
    else this.events.onMessage?.(obj);
  }

  // -- reconnect state machine ----------------------------------------------

  private _onDisconnect(): void {
    if (this._stopped) {
      this._setState("disconnected");
      return;
    }
    this._setState("reconnecting");
    this._retry(0);
  }

  private async _retry(attempt: number): Promise<void> {
    if (this._stopped) return;
    const delay = RECONNECT_BACKOFF_MS[Math.min(attempt, RECONNECT_BACKOFF_MS.length - 1)];
    await new Promise((r) => setTimeout(r, delay));
    if (this._stopped || this.deviceId === null) return;
    try {
      await this.transport.connect(this.deviceId);
      this.failures = 0;
      this.reasm.reset();
      this._setState("connected");
    } catch {
      this.failures += 1;
      // keep trying with growing backoff; a real user walking back into range
      // recovers. Callers watching `state` see "reconnecting" throughout.
      this._retry(attempt + 1);
    }
  }
}
