/**
 * useReceiptStore — the phone's view of the Brain's signed privacy receipt
 * (GET /dreamlayer/receipt). It fetches the hash-chained, Ed25519-signed
 * activity ledger from the paired Mac Brain and verifies it ON THE PHONE
 * (src/crypto/receiptVerify.ts) — the server's own verdict is never trusted.
 *
 * Trust-on-first-use key pinning: the first time we see a Brain's public key we
 * remember it (AsyncStorage, keyed by the Brain URL). On every later fetch we
 * compare — if the key changed, that's either a reinstall or someone
 * impersonating the Brain, and the screen says so loudly. Without the pin, an
 * attacker who held the pairing token could serve a receipt signed by their OWN
 * key and it would "verify"; the pin is what makes the signature mean identity.
 *
 * Uses the X-DreamLayer-Token header (the header the Brain actually reads),
 * matching usePluginStore — NOT Authorization: Bearer.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";

import { useBrainStore } from "./useBrainStore";
import {
  verifyReceipt,
  ReceiptRecord,
  VerifyResult,
  HeadAnchor,
} from "../crypto/receiptVerify";

const PIN_PREFIX = "dl.receiptpin.";

type ReceiptState = {
  records: ReceiptRecord[];
  pubkey: string;
  result: VerifyResult | null;
  keyChanged: boolean; // pubkey differs from the pinned one — suspicious
  firstSeen: boolean; // we just pinned this key for the first time
  loaded: boolean;
  loading: boolean;
  connected: boolean;
  error: string | null;
  load: (fetchImpl?: typeof fetch) => Promise<void>;
  /** Deliberately re-pin this Brain's current key (e.g. after a real reinstall),
   *  replacing the old pin, then re-verify. The only escape from a keyChanged
   *  state — intentionally a user action, never automatic. */
  repin: (fetchImpl?: typeof fetch) => Promise<void>;
};

export const useReceiptStore = create<ReceiptState>((set, get) => ({
  records: [],
  pubkey: "",
  result: null,
  keyChanged: false,
  firstSeen: false,
  loaded: false,
  loading: false,
  connected: false,
  error: null,

  load: async (fetchImpl: typeof fetch = fetch) => {
    const mac = useBrainStore.getState().macMini;
    if (!mac || !mac.url) {
      set({ connected: false, loaded: true, records: [], result: null, error: null });
      return;
    }
    set({ loading: true, error: null, connected: true });
    try {
      const base = mac.url.replace(/\/$/, "");
      const res = await fetchImpl(`${base}/dreamlayer/receipt`, {
        headers: mac.token ? { "X-DreamLayer-Token": mac.token } : {},
      });
      const data = await res.json();
      const records: ReceiptRecord[] = Array.isArray(data.records) ? data.records : [];
      const pubkey: string = typeof data.pubkey === "string" ? data.pubkey : "";
      const head: HeadAnchor | null = data.head && typeof data.head === "object" ? data.head : null;

      // Trust-on-first-use pin, keyed by this Brain's URL. Once a key is pinned
      // we ALWAYS verify against the pin — never the key the server just sent —
      // so a substitution (a MITM's key) or a downgrade (server now sends "") both
      // diverge from the pin AND fail verification (records signed by a different
      // or no key don't verify against the pinned key) → ok=false, not a mere flag.
      const pinKey = PIN_PREFIX + base;
      const pinned = await AsyncStorage.getItem(pinKey);
      let keyChanged = false;
      let firstSeen = false;
      let verifyKey = pubkey;
      if (pinned) {
        verifyKey = pinned;
        if (pubkey !== pinned) keyChanged = true; // substitution OR strip-to-unsigned
      } else if (pubkey) {
        await AsyncStorage.setItem(pinKey, pubkey); // first contact — pin it
        firstSeen = true;
      }

      const result = verifyReceipt(records, verifyKey, head);
      set({ records, pubkey, result, keyChanged, firstSeen, loaded: true, loading: false });
    } catch (e: unknown) {
      set({
        error: e instanceof Error ? e.message : String(e),
        loading: false,
        loaded: true,
      });
    }
  },

  repin: async (fetchImpl: typeof fetch = fetch) => {
    const mac = useBrainStore.getState().macMini;
    const served = get().pubkey;
    if (!mac || !mac.url || !served) return;
    const base = mac.url.replace(/\/$/, "");
    await AsyncStorage.setItem(PIN_PREFIX + base, served);
    await get().load(fetchImpl);
  },
}));
