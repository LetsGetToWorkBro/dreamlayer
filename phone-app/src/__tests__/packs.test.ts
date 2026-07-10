/** Earcon/Haptic pack picker store (B8): choosing a pack persists it and
 * installs its haptic overrides. */
jest.mock("../services/haptics", () => ({ setHapticOverrides: jest.fn() }));

import AsyncStorage from "@react-native-async-storage/async-storage";

import { setHapticOverrides } from "../services/haptics";
import { PACKS, usePackStore } from "../state/usePackStore";

beforeEach(() => {
  usePackStore.setState({ selectedId: "glass" });
  (setHapticOverrides as jest.Mock).mockClear();
});

describe("usePackStore", () => {
  it("defaults to Glass with no overrides", () => {
    expect(usePackStore.getState().active().id).toBe("glass");
    expect(PACKS[0]!.haptics).toBeUndefined();
  });

  it("selecting Analog installs its haptic overrides and persists", () => {
    usePackStore.getState().select("analog");
    const s = usePackStore.getState();
    expect(s.selectedId).toBe("analog");
    expect(s.active().name).toBe("Analog");
    expect(setHapticOverrides).toHaveBeenCalledWith(s.active().haptics);
  });

  it("selecting Glass clears overrides", () => {
    usePackStore.getState().select("analog");
    usePackStore.getState().select("glass");
    expect(setHapticOverrides).toHaveBeenLastCalledWith(null);
  });

  it("an unknown id falls back to the default pack", () => {
    usePackStore.getState().select("nope");
    expect(usePackStore.getState().selectedId).toBe("glass");
  });

  it("hydrate restores a persisted choice", async () => {
    await AsyncStorage.setItem("dreamlayer.pack.v1", "analog");
    await usePackStore.getState().hydrate();
    expect(usePackStore.getState().selectedId).toBe("analog");
  });

  it("every bundled pack keeps answer_ahead silent (no override)", () => {
    for (const p of PACKS) {
      expect(p.haptics?.answer_ahead).toBeUndefined();
    }
  });
});
