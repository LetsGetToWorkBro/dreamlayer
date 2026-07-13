/**
 * useGlassesStore — the phone's live view of the BLE link to the glasses.
 *
 * Wraps HaloBridge (pure-TS, transport-injected) so the UI has one honest
 * connection state: unpaired → scanning → connected → reconnecting. In Expo Go /
 * tests there is no native transport, so `connect()` stays a no-op and the demo
 * behaviour in useHaloStore is unchanged; a dev build supplies the ble-plx
 * transport and this drives the real radio.
 */
import { create } from "zustand";
import { HaloBridge, type BleTransport, type ConnState } from "../ble/bridge";
import { useVitalsStore } from "./useVitalsStore";
import { relayEmit } from "../services/lensRelay";

type GlassesState = {
  state: ConnState;
  deviceId: string | null;
  bridge: HaloBridge | null;

  label: () => string;
  /** Attach a real transport (a dev build calls this once at startup). */
  attachTransport: (transport: BleTransport | null) => void;
  connect: (scanTimeoutMs?: number) => Promise<string | null>;
  disconnect: () => Promise<void>;
  /** Send an object to the glasses (framed + chunked by the bridge). */
  send: (obj: unknown) => Promise<void>;
};

export const useGlassesStore = create<GlassesState>((set, get) => ({
  state: "disconnected",
  deviceId: null,
  bridge: null,

  label: () => {
    // lazy require: keep this store importable in plain node tests where the
    // expo-localization native module behind src/i18n isn't available
    let tr: (k: string) => string;
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      tr = require("../i18n").t;
    } catch {
      tr = (k) => k;
    }
    switch (get().state) {
      case "scanning":
        return tr("glasses.scanning");
      case "connected":
        return tr("glasses.connected");
      case "reconnecting":
        return tr("glasses.reconnecting");
      default:
        return tr("glasses.notPaired");
    }
  },

  attachTransport: (transport) => {
    if (!transport) {
      set({ bridge: null });
      return;
    }
    const bridge = new HaloBridge(transport, {
      onState: (s) => set({ state: s }),
      // give device telemetry an audience — the Device Vitals screen (B11)
      onTelemetry: (tel) => useVitalsStore.getState().ingest(tel),
      // a running lens emitted a tag → relay it to the Brain (glass→Brain→glass)
      onFigmentEmit: (emit) => { void relayEmit(emit); },
      // card/ack routing is wired by the app layer as needed
    });
    set({ bridge });
  },

  connect: async (scanTimeoutMs = 8000) => {
    const bridge = get().bridge;
    if (!bridge) return null; // no native transport (Expo Go / tests)
    const id = await bridge.connect(scanTimeoutMs);
    set({ deviceId: id });
    return id;
  },

  disconnect: async () => {
    const bridge = get().bridge;
    if (bridge) await bridge.disconnect();
    set({ deviceId: null });
  },

  send: async (obj) => {
    const bridge = get().bridge;
    if (bridge) await bridge.send(obj);
  },
}));
