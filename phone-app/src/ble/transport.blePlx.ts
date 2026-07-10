/**
 * transport.blePlx.ts — the react-native-ble-plx adapter for HaloBridge.
 *
 * INERT UNTIL A DEV BUILD. react-native-ble-plx is a native module: it does not
 * exist in Expo Go, so this file `require`s it lazily and returns null when it's
 * absent — every existing dev flow (Expo Go, jest, web) is untouched. To make it
 * live:
 *
 *   1. npx expo install react-native-ble-plx
 *   2. add the config plugin + Bluetooth permission strings to app.json:
 *        "plugins": [["react-native-ble-plx", { "isBackgroundEnabled": true }]]
 *   3. build a dev client:  eas build --profile development --platform ios
 *      (Expo Go cannot load native modules; you need a dev/standalone build)
 *   4. fill in the real UUIDs below from the bench-Halo session (they are the
 *      one thing that can't be known without the device on a desk).
 *
 * The bridge logic (framing, reassembly, reconnect) is transport-agnostic and
 * fully tested; this adapter only has to move bytes.
 */
import type { BleTransport } from "./bridge";

// TODO(bench-Halo): the real service + characteristic UUIDs come from the first
// on-glass session. Placeholders here are deliberately obvious.
export const HALO_SERVICE_UUID = "0000fe00-0000-1000-8000-00805f9b34fb";
export const HALO_TX_CHAR_UUID = "0000fe01-0000-1000-8000-00805f9b34fb"; // phone → glasses
export const HALO_RX_CHAR_UUID = "0000fe02-0000-1000-8000-00805f9b34fb"; // glasses → phone

function loadBlePlx(): any {
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    return require("react-native-ble-plx");
  } catch {
    return null;
  }
}

/** Returns a live BleTransport when react-native-ble-plx is installed (a dev
 * build), else null so callers keep the demo/HTTP behaviour. */
export function makeBlePlxTransport(): BleTransport | null {
  const mod = loadBlePlx();
  if (!mod?.BleManager) return null;

  const { BleManager } = mod;
  const manager = new BleManager();
  let notifyCb: ((chunk: Uint8Array) => void) | null = null;
  let disconnectCb: (() => void) | null = null;
  let device: any = null;

  const b64ToBytes = (b64: string): Uint8Array => {
    // RN provides global.atob on modern engines; fall back to Buffer if present.
    if (typeof atob === "function") {
      const bin = atob(b64);
      const out = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out;
    }
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    return Uint8Array.from(require("buffer").Buffer.from(b64, "base64"));
  };
  const bytesToB64 = (bytes: Uint8Array): string => {
    let bin = "";
    for (const b of bytes) bin += String.fromCharCode(b);
    if (typeof btoa === "function") return btoa(bin);
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    return require("buffer").Buffer.from(bytes).toString("base64");
  };

  return {
    async scan(timeoutMs: number): Promise<string | null> {
      return new Promise((resolve) => {
        const timer = setTimeout(() => {
          manager.stopDeviceScan();
          resolve(null);
        }, timeoutMs);
        manager.startDeviceScan([HALO_SERVICE_UUID], null, (err: any, dev: any) => {
          if (err || !dev) return;
          clearTimeout(timer);
          manager.stopDeviceScan();
          resolve(dev.id);
        });
      });
    },
    async connect(deviceId: string): Promise<void> {
      device = await manager.connectToDevice(deviceId);
      await device.discoverAllServicesAndCharacteristics();
      device.onDisconnected(() => disconnectCb?.());
      device.monitorCharacteristicForService(
        HALO_SERVICE_UUID,
        HALO_RX_CHAR_UUID,
        (err: any, ch: any) => {
          if (err || !ch?.value) return;
          notifyCb?.(b64ToBytes(ch.value));
        }
      );
    },
    async write(chunk: Uint8Array): Promise<void> {
      if (!device) throw new Error("not connected");
      await device.writeCharacteristicWithoutResponseForService(
        HALO_SERVICE_UUID,
        HALO_TX_CHAR_UUID,
        bytesToB64(chunk)
      );
    },
    onNotify(cb) {
      notifyCb = cb;
    },
    onDisconnect(cb) {
      disconnectCb = cb;
    },
    async disconnect(): Promise<void> {
      if (device) await manager.cancelDeviceConnection(device.id);
      device = null;
    },
  };
}
