/**
 * usePackStore — the Earcon/Haptic Pack picker (INNOVATION_SESSION 1.5 / B8).
 *
 * A pack reskins the platform's *feel* — a haptic table (and, later, earcon
 * families). The host validates a pack at the store gate (plugins/packs.py); this
 * is the phone half: choose a bundled pack, persist it, and install its haptic
 * overrides so `play()` uses them. answer_ahead stays silent by construction (the
 * gate rejects a non-empty answer_ahead), so a pack can never make it buzz.
 */
import { create } from "zustand";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { setHapticOverrides, type Beat, type HapticSignal } from "../services/haptics";

export type HapticPack = {
  id: string;
  name: string;
  description: string;
  /** Signal → pattern overrides. Absent = the built-in DreamLayer feel. */
  haptics?: Partial<Record<HapticSignal, Beat[]>>;
};

// Bundled packs. "Glass" is the default (no overrides); "Analog" is a worked
// example — weightier confirms, all patterns ≤400ms (the gate's rule).
export const PACKS: HapticPack[] = [
  {
    id: "glass",
    name: "Glass",
    description: "The default DreamLayer feel — tape-clean and precise.",
  },
  {
    id: "analog",
    name: "Analog",
    description: "Felt and warmth: weightier confirms, a firmer action.",
    haptics: {
      confirm: [{ impact: "heavy", at: 0 }, { impact: "light", at: 110 }],
      action: [{ impact: "heavy", at: 0 }],
    },
  },
];

const STORAGE_KEY = "dreamlayer.pack.v1";

type PackState = {
  selectedId: string;
  select: (id: string) => void;
  active: () => HapticPack;
  hydrate: () => Promise<void>;
};

export const usePackStore = create<PackState>((set, get) => ({
  selectedId: "glass",

  select: (id) => {
    const pack = PACKS.find((p) => p.id === id) ?? PACKS[0]!;
    set({ selectedId: pack.id });
    setHapticOverrides(pack.haptics ?? null);
    AsyncStorage.setItem(STORAGE_KEY, pack.id).catch(() => {});
  },

  active: () => PACKS.find((p) => p.id === get().selectedId) ?? PACKS[0]!,

  hydrate: async () => {
    try {
      const id = await AsyncStorage.getItem(STORAGE_KEY);
      if (id) get().select(id);
    } catch {
      /* keep the default */
    }
  },
}));
