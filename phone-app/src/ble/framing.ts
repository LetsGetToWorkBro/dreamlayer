/**
 * framing.ts — the BLE wire protocol, ported byte-for-byte from Python.
 *
 * Every frame is a 4-byte big-endian total-length header (the total INCLUDES
 * the header) followed by a canonical-JSON body (sorted keys, no spaces) — the
 * exact shape `host-python/.../reality_compiler/v2/transport.frame` produces and
 * `halo-lua/ble/protocol.lua` reassembles. Parity is pinned by test vectors
 * generated from the Python side, so the two implementations can never fork
 * silently (the class of bug the audit found and the loopback tests killed on
 * the host side — this is the phone half).
 */

export const MAX_FRAME = 16384; // must match protocol.lua MAX_FRAME / Python _MAX_FRAME_BYTES

/** Deterministic JSON: keys sorted recursively, `,`/`:` separators, no spaces —
 * matches Python `json.dumps(obj, sort_keys=True, separators=(",",":"))`. */
export function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) {
    return "[" + value.map(canonicalJson).join(",") + "]";
  }
  if (typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>).sort();
    return (
      "{" +
      keys
        .map((k) => JSON.stringify(k) + ":" + canonicalJson((value as Record<string, unknown>)[k]))
        .join(",") +
      "}"
    );
  }
  return JSON.stringify(value);
}

// TextEncoder/TextDecoder exist in Hermes/RN, Node, and web — the only runtimes
// this ships on — so we use them directly rather than hand-rolling UTF-8.
function utf8Bytes(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

function utf8Decode(bytes: Uint8Array): string {
  return new TextDecoder().decode(bytes);
}

/** Frame an object: 4-byte header (total incl. header) + canonical JSON body. */
export function framePayload(obj: unknown): Uint8Array {
  const body = utf8Bytes(canonicalJson(obj));
  const total = body.length + 4;
  if (total > MAX_FRAME) throw new Error(`frame of ${total} bytes exceeds MAX_FRAME`);
  const out = new Uint8Array(total);
  out[0] = (total >>> 24) & 0xff;
  out[1] = (total >>> 16) & 0xff;
  out[2] = (total >>> 8) & 0xff;
  out[3] = total & 0xff;
  out.set(body, 4);
  return out;
}

/** Split a framed payload into MTU-sized chunks for transmission. */
export function chunkFrame(framed: Uint8Array, chunkSize = 128): Uint8Array[] {
  const chunks: Uint8Array[] = [];
  for (let i = 0; i < framed.length; i += chunkSize) {
    chunks.push(framed.slice(i, i + chunkSize));
  }
  return chunks;
}

/**
 * Streaming reassembler — the mirror of protocol.lua. Feed arbitrary byte
 * chunks; it yields complete decoded objects. A corrupt length header (< 5 or
 * > MAX_FRAME) drops the buffer and recovers rather than wedging the link
 * forever, exactly like the device side.
 */
export class Reassembler {
  private buf: number[] = [];
  private need: number | null = null;
  public frames = 0;
  public dropped = 0;

  /** Feed a chunk; return every object that completed (usually 0 or 1). */
  feed(chunk: Uint8Array | number[]): unknown[] {
    for (const b of chunk) this.buf.push(b);
    const out: unknown[] = [];
    // loop so several frames concatenated in one chunk all drain
    // eslint-disable-next-line no-constant-condition
    while (true) {
      if (this.need === null) {
        if (this.buf.length < 4) break;
        this.need =
          ((this.buf[0]! << 24) | (this.buf[1]! << 16) | (this.buf[2]! << 8) | this.buf[3]!) >>> 0;
        if (this.need < 5 || this.need > MAX_FRAME) {
          this.buf = [];
          this.need = null;
          this.dropped += 1;
          break;
        }
      }
      if (this.buf.length < this.need) break;
      const body = Uint8Array.from(this.buf.slice(4, this.need));
      this.buf = this.buf.slice(this.need);
      this.need = null;
      this.frames += 1;
      try {
        out.push(JSON.parse(utf8Decode(body)));
      } catch {
        this.dropped += 1;
      }
    }
    return out;
  }

  reset(): void {
    this.buf = [];
    this.need = null;
  }

  pending(): boolean {
    return this.buf.length >= 4;
  }
}
