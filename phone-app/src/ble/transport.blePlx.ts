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

  // Hermes ships global.atob/btoa; the inline codec below covers any engine
  // without them. (No require("buffer") here — Metro resolves require literals
  // statically, so a Node-polyfill fallback breaks the iOS/Android bundle even
  // when the branch never runs.)
  const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const b64ToBytes = (b64: string): Uint8Array => {
    const bin = typeof atob === "function" ? atob(b64) : decodeB64(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  };
  const decodeB64 = (b64: string): string => {
    let bin = "";
    const clean = b64.replace(/=+$/, "");
    for (let i = 0; i < clean.length; i += 4) {
      const n =
        (B64.indexOf(clean.charAt(i)) << 18) |
        (B64.indexOf(clean.charAt(i + 1)) << 12) |
        ((B64.indexOf(clean.charAt(i + 2)) & 63) << 6) |
        (B64.indexOf(clean.charAt(i + 3)) & 63);
      bin += String.fromCharCode((n >> 16) & 255);
      if (i + 2 < clean.length) bin += String.fromCharCode((n >> 8) & 255);
      if (i + 3 < clean.length) bin += String.fromCharCode(n & 255);
    }
    return bin;
  };
  const bytesToB64 = (bytes: Uint8Array): string => {
    let bin = "";
    for (const b of bytes) bin += String.fromCharCode(b);
    if (typeof btoa === "function") return btoa(bin);
    let out = "";
    for (let i = 0; i < bin.length; i += 3) {
      const n = (bin.charCodeAt(i) << 16) | ((bin.charCodeAt(i + 1) || 0) << 8) | (bin.charCodeAt(i + 2) || 0);
      out += B64.charAt((n >> 18) & 63) + B64.charAt((n >> 12) & 63)
        + (i + 1 < bin.length ? B64.charAt((n >> 6) & 63) : "=")
        + (i + 2 < bin.length ? B64.charAt(n & 63) : "=");
    }
    return out;
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
