/**
 * pairing.ts — decode the one code that brings the trio together.
 *
 * Mirrors host-python/src/dreamlayer/pairing.py: a `dreamlayer:` deep-link
 * whose payload is URL-safe base64 of a tiny JSON bundle carrying the Brain
 * URL, the pairing token, and the glasses' BLE id. The Mac mini panel shows
 * it as a QR; the phone scans (or pastes) it and is instantly wired.
 *
 * We hand-roll base64 so this works on any RN/Hermes runtime without relying
 * on atob/btoa being present.
 */
export const SCHEME = "dreamlayer";

export type PairingBundle = {
  brainUrl: string;
  token: string;
  glassesId: string;
  label: string;
  relayUrl: string; // reach the Brain off your LAN (optional)
};

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

function bytesToUtf8(bytes: number[]): string {
  // minimal UTF-8 decode (the payload is JSON; usually ASCII)
  let out = "";
  for (let i = 0; i < bytes.length; ) {
    const b = bytes[i++];
    if (b < 0x80) out += String.fromCharCode(b);
    else if (b < 0xe0) out += String.fromCharCode(((b & 0x1f) << 6) | (bytes[i++] & 0x3f));
    else if (b < 0xf0)
      out += String.fromCharCode(((b & 0x0f) << 12) | ((bytes[i++] & 0x3f) << 6) | (bytes[i++] & 0x3f));
    else {
      const cp =
        ((b & 0x07) << 18) | ((bytes[i++] & 0x3f) << 12) | ((bytes[i++] & 0x3f) << 6) | (bytes[i++] & 0x3f);
      const c = cp - 0x10000;
      out += String.fromCharCode(0xd800 + (c >> 10), 0xdc00 + (c & 0x3ff));
    }
  }
  return out;
}

function utf8ToBytes(s: string): number[] {
  const out: number[] = [];
  for (const ch of s) {
    let c = ch.codePointAt(0)!;
    if (c < 0x80) out.push(c);
    else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f));
    else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
    else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 0x3f), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
  }
  return out;
}

function b64urlEncode(bytes: number[]): string {
  const std = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const n = (bytes[i] << 16) | ((bytes[i + 1] ?? 0) << 8) | (bytes[i + 2] ?? 0);
    out += std[(n >> 18) & 63] + std[(n >> 12) & 63];
    out += i + 1 < bytes.length ? std[(n >> 6) & 63] : "=";
    out += i + 2 < bytes.length ? std[n & 63] : "=";
  }
  return out.replace(/\+/g, "-").replace(/\//g, "_");
}

function b64urlDecode(s: string): number[] {
  const std = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const clean = s.replace(/-/g, "+").replace(/_/g, "/").replace(/=+$/, "");
  const out: number[] = [];
  for (let i = 0; i < clean.length; i += 4) {
    const n =
      (std.indexOf(clean[i]) << 18) |
      (std.indexOf(clean[i + 1]) << 12) |
      ((clean[i + 2] ? std.indexOf(clean[i + 2]) : 0) << 6) |
      (clean[i + 3] ? std.indexOf(clean[i + 3]) : 0);
    out.push((n >> 16) & 0xff);
    if (clean[i + 2]) out.push((n >> 8) & 0xff);
    if (clean[i + 3]) out.push(n & 0xff);
  }
  return out;
}

export function encodePairing(b: PairingBundle): string {
  const payload: Record<string, string> = {};
  if (b.brainUrl) payload.brain_url = b.brainUrl;
  if (b.token) payload.token = b.token;
  if (b.glassesId) payload.glasses_id = b.glassesId;
  if (b.label && b.label !== "DreamLayer") payload.label = b.label;
  if (b.relayUrl) payload.relay_url = b.relayUrl;
  return SCHEME + ":" + b64urlEncode(utf8ToBytes(JSON.stringify(payload)));
}

export function decodePairing(code: string): PairingBundle {
  let s = code.trim();
  if (s.startsWith(SCHEME + ":")) s = s.slice(SCHEME.length + 1);
  const data = JSON.parse(bytesToUtf8(b64urlDecode(s))) as Record<string, string>;
  return {
    brainUrl: data.brain_url ?? "",
    token: data.token ?? "",
    glassesId: data.glasses_id ?? "",
    label: data.label ?? "DreamLayer",
    relayUrl: data.relay_url ?? "",
  };
}

// referenced so the alphabet constant isn't flagged unused by strict builds
void B64;
