/**
 * receiptVerify.test.ts — the phone's independent receipt verification.
 *
 * Builds genuinely-signed ledgers with @noble (the same primitive the Brain's
 * Ed25519 uses), then proves verifyReceipt() accepts a clean ledger and catches
 * every tamper: an edited entry, a deleted entry, and a key substitution
 * (the MITM case the trust-on-first-use pin defends against).
 */
import * as ed from "@noble/ed25519";
import { sha512 } from "@noble/hashes/sha512";
import { sha256 } from "@noble/hashes/sha256";

ed.etc.sha512Sync = (...m) => sha512(ed.etc.concatBytes(...m));

import { verifyReceipt, canonicalCore, canonicalHead, ReceiptRecord, HeadAnchor } from "../crypto/receiptVerify";

const enc = new TextEncoder();
const toHex = (b: Uint8Array) =>
  Array.from(b).map((x) => x.toString(16).padStart(2, "0")).join("");

function buildLedger(priv: Uint8Array, texts: string[]): { recs: ReceiptRecord[]; pub: string; head: HeadAnchor } {
  const pub = toHex(ed.getPublicKey(priv));
  let prev = "";
  const recs: ReceiptRecord[] = [];
  texts.forEach((text, i) => {
    const rec: ReceiptRecord = { seq: i, ts: 1700000000 + i * 0.5, kind: "test", text, prev };
    const bytes = enc.encode(canonicalCore(rec));
    rec.sig = toHex(ed.sign(bytes, priv));
    recs.push(rec);
    prev = toHex(sha256(bytes)); // running head
  });
  const core = { last_seq: recs[recs.length - 1]!.seq, head: prev, count: recs.length };
  const head: HeadAnchor = { ...core, sig: toHex(ed.sign(enc.encode(canonicalHead(core)), priv)) };
  return { recs, pub, head };
}

const PRIV = new Uint8Array(32).fill(7);

describe("receipt verification", () => {
  test("a genuine signed ledger verifies", () => {
    const { recs, pub, head } = buildLedger(PRIV, ["looked at a book", "synced calendar", "purged frames"]);
    const r = verifyReceipt(recs, pub, head);
    expect(r.ok).toBe(true);
    expect(r.signed).toBe(true);
    expect(r.signatureValid).toBe(true);
    expect(r.chainIntact).toBe(true);
    expect(r.sequenceComplete).toBe(true);
    expect(r.tailComplete).toBe(true);
    expect(r.firstBroken).toBeNull();
  });

  test("editing a past entry breaks the signature and the chain at that entry", () => {
    const { recs, pub, head } = buildLedger(PRIV, ["a", "b", "c"]);
    recs[1] = { ...recs[1]!, text: "b (tampered)" };
    const r = verifyReceipt(recs, pub, head);
    expect(r.ok).toBe(false);
    expect(r.signatureValid).toBe(false);
    expect(r.chainIntact).toBe(false);
    expect(r.firstBroken).toBe(1);
  });

  test("deleting an entry leaves a sequence gap", () => {
    const { recs, pub, head } = buildLedger(PRIV, ["a", "b", "c"]);
    const r = verifyReceipt([recs[0]!, recs[2]!], pub, head);
    expect(r.ok).toBe(false);
    expect(r.sequenceComplete).toBe(false);
  });

  test("a different key never verifies the signatures (key-substitution / MITM)", () => {
    const { recs, head } = buildLedger(PRIV, ["a", "b"]);
    const attacker = toHex(ed.getPublicKey(new Uint8Array(32).fill(9)));
    const r = verifyReceipt(recs, attacker, head);
    expect(r.signatureValid).toBe(false);
    expect(r.ok).toBe(false);
  });

  test("a signed ledger with NO head anchor cannot be confirmed complete", () => {
    const { recs, pub } = buildLedger(PRIV, ["a", "b"]);
    const r = verifyReceipt(recs, pub); // head stripped by an attacker / absent
    expect(r.ok).toBe(false);
    expect(r.tailComplete).toBe(false);
    expect(r.chainIntact).toBe(true); // not tampered — completeness just isn't proven
  });

  test("an empty ledger is vacuously verified", () => {
    const r = verifyReceipt([], toHex(ed.getPublicKey(PRIV)));
    expect(r.ok).toBe(true);
    expect(r.count).toBe(0);
  });

  test("an unsigned ledger reports signed=false but still checks the chain", () => {
    const { recs } = buildLedger(PRIV, ["a", "b"]);
    const unsigned = recs.map((r) => ({ seq: r.seq, ts: r.ts, kind: r.kind, text: r.text, prev: r.prev }));
    const r = verifyReceipt(unsigned, "");
    expect(r.signed).toBe(false);
    expect(r.signatureValid).toBe(false);
    expect(r.chainIntact).toBe(true);
    expect(r.ok).toBe(true); // chain + sequence hold; there is nothing to attest
  });

  test("a signed head anchor verifies and reports the attested count", () => {
    const { recs, pub, head } = buildLedger(PRIV, ["a", "b", "c"]);
    const r = verifyReceipt(recs, pub, head);
    expect(r.ok).toBe(true);
    expect(r.attestedCount).toBe(3);
    expect(r.tailShort).toBe(false);
    expect(r.unattestedAppend).toBe(false);
  });

  test("a truncated tail is flagged (signed length ahead of the shown window)", () => {
    const { recs, pub, head } = buildLedger(PRIV, ["a", "b", "c", "d"]);
    // attacker chops the last two records but can't re-sign the length anchor
    const chopped = recs.slice(0, 2);
    const r = verifyReceipt(chopped, pub, head);
    expect(r.tailShort).toBe(true);
    expect(r.attestedCount).toBe(4);
    expect(r.chainIntact).toBe(true); // the surviving prefix is itself valid — that's the attack
    expect(r.ok).toBe(false); // but tail-completeness is unproven, so NOT verified
  });

  test("records beyond the signed length are an unattested-append tamper", () => {
    const { recs, pub, head } = buildLedger(PRIV, ["a", "b"]);
    const { recs: more } = buildLedger(PRIV, ["a", "b", "c"]);
    // three properly-chained records, but the head only attests two
    const r = verifyReceipt(more, pub, head);
    expect(r.unattestedAppend).toBe(true);
    expect(r.ok).toBe(false);
  });

  test("a forged head anchor is rejected", () => {
    const { recs, pub, head } = buildLedger(PRIV, ["a", "b"]);
    const forged: HeadAnchor = { ...head, sig: "00".repeat(64) };
    const r = verifyReceipt(recs, pub, forged);
    expect(r.ok).toBe(false);
    expect(r.chainIntact).toBe(false);
  });

  test("canonicalCore matches the Python contract vector (whole-float + emoji)", () => {
    const core: ReceiptRecord = {
      seq: 2, ts: 1700000000.0, kind: "plugin",
      text: 'emoji 🎉 and quote " and backslash \\', prev: "deadbeef",
    };
    expect(canonicalCore(core)).toBe(
      '{"kind":"plugin","prev":"deadbeef","seq":2,"text":"emoji \\ud83c\\udf89 and quote \\" and backslash \\\\","ts":1700000000.0}',
    );
  });
});
