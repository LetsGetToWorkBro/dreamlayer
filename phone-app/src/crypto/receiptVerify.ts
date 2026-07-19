/**
 * receiptVerify — independent, on-device verification of the Brain's signed
 * privacy receipt (GET /dreamlayer/receipt). No network, no trust in the
 * server's own verdict: we re-derive everything here.
 *
 * Three checks, mirroring the panel:
 *   1. signature — each record's Ed25519 signature over the 5-field core
 *      {seq,ts,kind,text,prev}, verified against the Brain's public key.
 *   2. chain — each record's `prev` equals sha256(canonical(previous core)),
 *      so altering or removing any past entry breaks every entry after it.
 *   3. sequence — the seq numbers run unbroken (a deleted entry leaves a gap).
 *
 * `canonicalCore` reproduces Python's json.dumps(sort_keys=True,
 * separators=(",",":"), ensure_ascii=True) BYTE-FOR-BYTE — the exact same
 * contract the panel reproduces and test_receipt_verify_vectors.py pins. A
 * mismatch here would fail a legitimate receipt, so it is proven cross-language
 * (node ↔ Python) and must not be "fixed" casually.
 */
import * as ed from "@noble/ed25519";
import { sha256 } from "@noble/hashes/sha256";
import { sha512 } from "@noble/hashes/sha512";

// noble-ed25519 v2 needs a synchronous SHA-512; React Native/Hermes has no
// WebCrypto, so wire the pure-JS one from @noble/hashes.
ed.etc.sha512Sync = (...m) => sha512(ed.etc.concatBytes(...m));

export type ReceiptRecord = {
  seq: number;
  ts: number;
  kind: string;
  text: string;
  prev: string;
  sig?: string;
};

// The signed length anchor {last_seq, head, count} + its own signature. Defeats
// tail-truncation: a valid prefix of a valid chain is itself a valid chain, so a
// key-less attacker who chops recent records leaves the anchor attesting a
// length they can't re-sign.
export type HeadAnchor = {
  last_seq: number;
  head: string;
  count: number;
  sig?: string;
};

export type VerifyResult = {
  ok: boolean; // every applicable check passed
  signed: boolean; // the ledger carries a public key at all
  signatureValid: boolean;
  chainIntact: boolean;
  sequenceComplete: boolean;
  firstBroken: number | null; // index of the first failing record
  count: number;
  attestedCount: number | null; // total records the signed head attests (null if no valid head)
  headVerified: boolean; // a signed head anchor was present and its signature checked out
  tailShort: boolean; // signed length is ahead of the last shown entry — the tail may be truncated
  unattestedAppend: boolean; // records claim entries the signed head never attested (hard tamper)
  tailComplete: boolean; // a valid head ties the shown tail to the signed length (or ledger is unsigned)
};

function pyStr(s: string): string {
  s = s == null ? "" : String(s);
  let o = '"';
  for (const ch of s) {
    const cp = ch.codePointAt(0) as number;
    if (ch === '"') o += '\\"';
    else if (ch === "\\") o += "\\\\";
    else if (cp === 8) o += "\\b";
    else if (cp === 9) o += "\\t";
    else if (cp === 10) o += "\\n";
    else if (cp === 12) o += "\\f";
    else if (cp === 13) o += "\\r";
    else if (cp < 0x20) o += "\\u" + cp.toString(16).padStart(4, "0");
    else if (cp < 0x80) o += ch;
    else if (cp > 0xffff) {
      const c = cp - 0x10000;
      o +=
        "\\u" + (0xd800 + (c >> 10)).toString(16).padStart(4, "0") +
        "\\u" + (0xdc00 + (c & 0x3ff)).toString(16).padStart(4, "0");
    } else o += "\\u" + cp.toString(16).padStart(4, "0");
  }
  return o + '"';
}

// ts is a float from time.time(); Python renders an integer-valued float as "N.0"
function pyFloat(v: number): string {
  v = Number(v);
  return Number.isInteger(v) ? v.toFixed(1) : String(v);
}

export function canonicalCore(r: ReceiptRecord): string {
  return (
    '{"kind":' + pyStr(r.kind) +
    ',"prev":' + pyStr(r.prev || "") +
    ',"seq":' + String(r.seq) +
    ',"text":' + pyStr(r.text) +
    ',"ts":' + pyFloat(r.ts) + "}"
  );
}

// canonical form of the head-anchor core {last_seq, head, count} — sorted keys,
// ints and one hex string, matching Python's json.dumps for _write_head's core.
export function canonicalHead(h: HeadAnchor): string {
  return '{"count":' + String(h.count) + ',"head":' + pyStr(h.head) + ',"last_seq":' + String(h.last_seq) + "}";
}

const enc = new TextEncoder();
const toHex = (b: Uint8Array) =>
  Array.prototype.map.call(b, (x: number) => x.toString(16).padStart(2, "0")).join("");

function edVerify(sigHex: string, bytes: Uint8Array, pubHex: string): boolean {
  try {
    return ed.verify(sigHex, bytes, pubHex);
  } catch {
    return false;
  }
}

/**
 * Verify a receipt's records against a public key, and (when present) its signed
 * head anchor. `pubkey` "" means the ledger is unsigned. Runs entirely on-device.
 *
 * The chain is anchored at records[0].prev — NOT at "" — because the endpoint
 * returns only the last N records, so the window may legitimately start
 * mid-chain. Each in-window link is still verified; the first record's link into
 * the (out-of-window) past is instead attested by the signed head anchor.
 */
export function verifyReceipt(
  records: ReceiptRecord[],
  pubkey: string,
  head?: HeadAnchor | null,
): VerifyResult {
  const signed = !!pubkey;
  if (records.length === 0) {
    // an empty ledger has nothing to attest — trivially, vacuously verified
    return {
      ok: true, signed, signatureValid: signed, chainIntact: true, sequenceComplete: true,
      firstBroken: null, count: 0, attestedCount: null, headVerified: false,
      tailShort: false, unattestedAppend: false, tailComplete: true,
    };
  }
  let chainIntact = true;
  let sequenceComplete = true;
  let signatureValid = signed;
  let firstBroken: number | null = null;
  const breakAt = (i: number) => {
    if (firstBroken === null) firstBroken = i;
  };
  let prev = records[0]?.prev ?? ""; // anchor into the possibly out-of-window past
  const base = records[0]?.seq ?? 0;
  for (const [i, rec] of records.entries()) {
    const bytes = enc.encode(canonicalCore(rec));
    if (i > 0 && (rec.prev || "") !== prev) {
      chainIntact = false;
      breakAt(i);
    }
    if (rec.seq !== base + i) sequenceComplete = false;
    if (signed && !edVerify(rec.sig || "", bytes, pubkey)) {
      signatureValid = false;
      breakAt(i);
    }
    prev = toHex(sha256(bytes)); // running head after this record
  }

  // Independent tail-length attestation via the signed head anchor.
  let attestedCount: number | null = null;
  let headVerified = false;
  let tailShort = false;
  let unattestedAppend = false;
  if (signed && head && head.sig) {
    if (!edVerify(head.sig, enc.encode(canonicalHead(head)), pubkey)) {
      chainIntact = false; // a forged / edited length anchor
      breakAt(records.length - 1);
    } else {
      headVerified = true;
      attestedCount = head.count;
      const lastSeq = records[records.length - 1]!.seq;
      if (head.last_seq === lastSeq) {
        // window ends exactly at the signed head — the running hash must match it
        if (head.head !== prev) {
          chainIntact = false;
          breakAt(records.length - 1);
        }
      } else if (head.last_seq < lastSeq) {
        unattestedAppend = true; // entries past the signed length — never a race, always tamper
      } else {
        tailShort = true; // signed length ahead of the shown tail — possible truncation
      }
    }
  }

  // A SIGNED ledger is only "complete" when a valid head anchor ties the shown
  // window's tail to the signed length. A missing head, an unverifiable head, or
  // a short tail all mean completeness is UNproven → not ok (fail-safe, so an
  // attacker who chops the tail — or strips the anchor — can't read as verified).
  const tailComplete = !signed || (headVerified && !tailShort);
  const ok =
    chainIntact && sequenceComplete && (signed ? signatureValid : true) &&
    !unattestedAppend && tailComplete;
  return {
    ok,
    signed,
    signatureValid,
    chainIntact,
    sequenceComplete,
    firstBroken,
    count: records.length,
    attestedCount,
    headVerified,
    tailShort,
    unattestedAppend,
    tailComplete,
  };
}
