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
  // minimal UTF-8 decode (the payload is JSON; usually ASCII). Reads default
  // to 0 for the type-checker; loop bounds guarantee the bytes are present.
  const at = (i: number) => bytes[i] ?? 0;
  let out = "";
  for (let i = 0; i < bytes.length; ) {
    const b = at(i++);
    if (b < 0x80) out += String.fromCharCode(b);
    else if (b < 0xe0) out += String.fromCharCode(((b & 0x1f) << 6) | (at(i++) & 0x3f));
    else if (b < 0xf0)
      out += String.fromCharCode(((b & 0x0f) << 12) | ((at(i++) & 0x3f) << 6) | (at(i++) & 0x3f));
    else {
      const cp =
        ((b & 0x07) << 18) | ((at(i++) & 0x3f) << 12) | ((at(i++) & 0x3f) << 6) | (at(i++) & 0x3f);
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
  const ch = (n: number) => std[n & 63] ?? "";
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const n = ((bytes[i] ?? 0) << 16) | ((bytes[i + 1] ?? 0) << 8) | (bytes[i + 2] ?? 0);
    out += ch(n >> 18) + ch(n >> 12);
    out += i + 1 < bytes.length ? ch(n >> 6) : "=";
    out += i + 2 < bytes.length ? ch(n) : "=";
  }
  return out.replace(/\+/g, "-").replace(/\//g, "_");
}

function b64urlDecode(s: string): number[] {
  const std = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const clean = s.replace(/-/g, "+").replace(/_/g, "/").replace(/=+$/, "");
  const idx = (i: number) => (clean[i] ? std.indexOf(clean[i] as string) : 0);
  const out: number[] = [];
  for (let i = 0; i < clean.length; i += 4) {
    const n = (idx(i) << 18) | (idx(i + 1) << 12) | (idx(i + 2) << 6) | idx(i + 3);
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

// ---------------------------------------------------------------------------
// Cleartext scoping — the app half of the Android network security policy.
//
// The phone speaks plain HTTP to the Brain, but only ever on the owner's own
// network. Android's network_security_config.xml cannot express "cleartext to
// RFC 1918 ranges only" (its <domain> rules are literal hostnames, no CIDR),
// so the real range check lives here and is enforced wherever a Brain/relay
// URL enters or leaves the app: pairFromCode(), hydrate(), and brainFetch()
// in useBrainStore. Keep in sync with plugins/withAndroidLanCleartext.js.
// ---------------------------------------------------------------------------

/** The hostname/IP part of a URL, without scheme, userinfo, port, brackets,
 * or path. Hand-rolled (no URL global on every Hermes runtime). */
function hostOf(url: string): string {
  const m = /^[a-z][a-z0-9+.-]*:\/\/([^/?#]+)/i.exec(url.trim());
  if (!m || !m[1]) return "";
  let host = m[1];
  const at = host.lastIndexOf("@"); // strip userinfo — never let it spoof the host
  if (at >= 0) host = host.slice(at + 1);
  if (host.startsWith("[")) {
    const end = host.indexOf("]");
    return end > 0 ? host.slice(1, end).toLowerCase() : "";
  }
  const colon = host.indexOf(":");
  return (colon >= 0 ? host.slice(0, colon) : host).toLowerCase();
}

/** True when a host can only be someone's own network: loopback, RFC 1918,
 * link-local, CGNAT (100.64/10 — Tailscale addresses), IPv6 ULA/link-local,
 * mDNS-style names (.local / .home.arpa), or a dotless single-label name
 * (resolvable only through local search domains, never public DNS). */
export function isPrivateLanHost(host: string): boolean {
  const h = host.toLowerCase().replace(/^\[|\]$/g, "");
  if (!h) return false;
  if (h === "localhost" || h.endsWith(".localhost")) return true;
  if (h.endsWith(".local") || h.endsWith(".home.arpa")) return true;

  const v4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h);
  if (v4) {
    const [a, b, c, d] = [Number(v4[1]), Number(v4[2]), Number(v4[3]), Number(v4[4])];
    if ([a, b, c, d].some((n) => n > 255)) return false;
    if (a === 10 || a === 127) return true;                    // 10/8, loopback
    if (a === 172 && b >= 16 && b <= 31) return true;          // 172.16/12
    if (a === 192 && b === 168) return true;                   // 192.168/16
    if (a === 169 && b === 254) return true;                   // link-local
    if (a === 100 && b >= 64 && b <= 127) return true;         // CGNAT / Tailscale
    return false;
  }
  if (h.includes(":")) {
    // IPv6: loopback, ULA fc00::/7, link-local fe80::/10 — nothing else
    if (h === "::1") return true;
    if (h.startsWith("fc") || h.startsWith("fd")) return true;
    return /^fe[89ab]/.test(h);
  }
  // a bare single-label hostname (http://mac:7777) never resolves via public
  // DNS — it's a LAN name by construction
  return !h.includes(".");
}

/** Policy gate for a Brain/relay URL: HTTPS goes anywhere; plain HTTP only to
 * a private/LAN host. Anything unparseable is refused. */
export function cleartextAllowed(url: string): boolean {
  const u = url.trim();
  if (/^https:\/\//i.test(u)) return true;
  if (!/^http:\/\//i.test(u)) return false;
  return isPrivateLanHost(hostOf(u));
}

// referenced so the alphabet constant isn't flagged unused by strict builds
void B64;
