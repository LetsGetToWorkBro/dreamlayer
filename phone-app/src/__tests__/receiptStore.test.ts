/**
 * receiptStore.test.ts — trust-on-first-use key pinning in useReceiptStore.
 *
 * Proves the store verifies against the PINNED key (not the served one), so a
 * key substitution or a signature-strip downgrade after pinning both fail
 * verification — and that an explicit repin() is the only way to accept a new
 * key (a genuine reinstall).
 */
import * as ed from "@noble/ed25519";
import { sha512 } from "@noble/hashes/sha512";
import { sha256 } from "@noble/hashes/sha256";

ed.etc.sha512Sync = (...m) => sha512(ed.etc.concatBytes(...m));

import AsyncStorage from "@react-native-async-storage/async-storage";
import { useReceiptStore } from "../state/useReceiptStore";
import { useBrainStore } from "../state/useBrainStore";
import { canonicalCore, canonicalHead } from "../crypto/receiptVerify";

// hermetic: clear any pinned keys between tests so ordering can never couple them
beforeEach(() => (AsyncStorage as unknown as { __reset?: () => void }).__reset?.());

const enc = new TextEncoder();
const toHex = (b: Uint8Array) => Array.from(b).map((x) => x.toString(16).padStart(2, "0")).join("");

function payload(seed: number, texts: string[]) {
  const priv = new Uint8Array(32).fill(seed);
  const pub = toHex(ed.getPublicKey(priv));
  let prev = "";
  const records = texts.map((text, i) => {
    const rec: Record<string, unknown> = { seq: i, ts: 1700000000 + i, kind: "t", text, prev };
    const b = enc.encode(canonicalCore(rec as never));
    rec.sig = toHex(ed.sign(b, priv));
    prev = toHex(sha256(b));
    return rec;
  });
  const core = { last_seq: records.length - 1, head: prev, count: records.length };
  const head = { ...core, sig: toHex(ed.sign(enc.encode(canonicalHead(core)), priv)) };
  return { pubkey: pub, records, head, algorithm: "ed25519-sha256-chain" };
}
const fetchOf = (p: unknown) => (() => Promise.resolve({ json: () => Promise.resolve(p) })) as unknown as typeof fetch;
const pair = (url: string) => useBrainStore.setState({ macMini: { connected: true, url, token: "t" } });

test("first contact pins the key and verifies clean", async () => {
  pair("http://b1.local");
  await useReceiptStore.getState().load(fetchOf(payload(3, ["a", "b"])));
  const s = useReceiptStore.getState();
  expect(s.firstSeen).toBe(true);
  expect(s.keyChanged).toBe(false);
  expect(s.result?.ok).toBe(true);
});

test("a substituted key is caught and fails verification against the pin", async () => {
  pair("http://b2.local");
  await useReceiptStore.getState().load(fetchOf(payload(3, ["a", "b"]))); // pins seed 3
  await useReceiptStore.getState().load(fetchOf(payload(9, ["a", "b", "c"]))); // attacker's key
  const s = useReceiptStore.getState();
  expect(s.keyChanged).toBe(true);
  expect(s.result?.ok).toBe(false);
});

test("a downgrade (key stripped + records swapped) is flagged AND fails verification", async () => {
  pair("http://b3.local");
  await useReceiptStore.getState().load(fetchOf(payload(3, ["a", "b"]))); // pin seed 3
  // attacker strips the pubkey and serves a ledger NOT signed by the pinned key
  const evil = payload(9, ["x", "y"]);
  await useReceiptStore.getState().load(fetchOf({ pubkey: "", records: evil.records, head: null }));
  const s = useReceiptStore.getState();
  expect(s.keyChanged).toBe(true); // pubkey went from the pinned key to "" → flagged
  expect(s.result?.ok).toBe(false); // and the swapped records don't verify under the pin
});

test("re-serving the SAME authentic records with the pubkey field stripped still verifies", async () => {
  // A cosmetic strip (records still genuinely signed by the pinned key) is not a
  // forgery — it verifies against the pin — but the key change is still surfaced.
  pair("http://b3b.local");
  const good = payload(3, ["a", "b"]);
  await useReceiptStore.getState().load(fetchOf(good));
  await useReceiptStore.getState().load(fetchOf({ ...good, pubkey: "" }));
  const s = useReceiptStore.getState();
  expect(s.keyChanged).toBe(true); // surfaced to the user
  expect(s.result?.ok).toBe(true); // but the content is authentic under the pinned key
});

test("repin trusts the new key after a genuine reinstall", async () => {
  pair("http://b4.local");
  await useReceiptStore.getState().load(fetchOf(payload(3, ["a"])));
  const rotated = payload(7, ["a", "b"]);
  await useReceiptStore.getState().load(fetchOf(rotated));
  expect(useReceiptStore.getState().keyChanged).toBe(true);
  await useReceiptStore.getState().repin(fetchOf(rotated));
  const s = useReceiptStore.getState();
  expect(s.keyChanged).toBe(false);
  expect(s.result?.ok).toBe(true);
});
