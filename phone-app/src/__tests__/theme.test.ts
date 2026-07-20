/**
 * The theme store — Midnight Platinum's switchboard.
 *
 *  - three modes (platinum / midnight / auto), default "auto"
 *  - auto resolves through the OS scheme: dark → midnight, anything else →
 *    platinum (the phone looks like the phone until you say otherwise)
 *  - the choice persists (AsyncStorage) and hydrates back; garbage in
 *    storage falls back to auto instead of wedging the app
 *  - the two theme worlds carry the SAME token contract — every colors.* and
 *    platinum.* key exists in both — and midnight keeps the Platinum
 *    construction: the hard black frame never softens.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  useThemeStore,
  resolveThemeName,
  THEME_MODES,
  type ThemeMode,
} from "../state/useThemeStore";
import { themes, platinumTheme, midnightTheme } from "../ui/theme/themes";
import { colors, platinum } from "../ui/theme/colors";

const KEY = "dreamlayer.theme.v1";
const mock = AsyncStorage as unknown as { __reset(): void };

beforeEach(() => {
  mock.__reset();
  useThemeStore.setState({ mode: "auto", hydrated: false });
});

describe("mode switching", () => {
  it("defaults to auto", () => {
    expect(useThemeStore.getState().mode).toBe("auto");
  });

  it("setMode switches and persists the choice", async () => {
    useThemeStore.getState().setMode("midnight");
    expect(useThemeStore.getState().mode).toBe("midnight");
    await Promise.resolve(); // let the fire-and-forget setItem land
    expect(await AsyncStorage.getItem(KEY)).toBe(JSON.stringify({ mode: "midnight" }));
  });

  it("cycleMode walks platinum → midnight → auto → platinum", () => {
    useThemeStore.getState().setMode("platinum");
    const seen: ThemeMode[] = [];
    for (let i = 0; i < 3; i++) {
      useThemeStore.getState().cycleMode();
      seen.push(useThemeStore.getState().mode);
    }
    expect(seen).toEqual(["midnight", "auto", "platinum"]);
    expect(THEME_MODES).toEqual(["platinum", "midnight", "auto"]);
  });

  it("rejects a nonsense mode instead of storing it", () => {
    useThemeStore.getState().setMode("disco" as ThemeMode);
    expect(useThemeStore.getState().mode).toBe("auto");
  });
});

describe("auto resolution", () => {
  it("auto follows the OS scheme; explicit modes ignore it", () => {
    expect(resolveThemeName("auto", "dark")).toBe("midnight");
    expect(resolveThemeName("auto", "light")).toBe("platinum");
    expect(resolveThemeName("auto", null)).toBe("platinum");
    expect(resolveThemeName("auto", undefined)).toBe("platinum");
    expect(resolveThemeName("platinum", "dark")).toBe("platinum");
    expect(resolveThemeName("midnight", "light")).toBe("midnight");
  });

  it("the store's resolved() mirrors the pure function", () => {
    useThemeStore.getState().setMode("auto");
    expect(useThemeStore.getState().resolved("dark")).toBe("midnight");
    expect(useThemeStore.getState().resolved("light")).toBe("platinum");
    useThemeStore.getState().setMode("midnight");
    expect(useThemeStore.getState().resolved("light")).toBe("midnight");
  });
});

describe("persistence", () => {
  it("hydrate restores a stored mode", async () => {
    await AsyncStorage.setItem(KEY, JSON.stringify({ mode: "midnight" }));
    await useThemeStore.getState().hydrate();
    expect(useThemeStore.getState().mode).toBe("midnight");
    expect(useThemeStore.getState().hydrated).toBe(true);
  });

  it("garbage in storage falls back to auto", async () => {
    await AsyncStorage.setItem(KEY, "{not json");
    await useThemeStore.getState().hydrate();
    expect(useThemeStore.getState().mode).toBe("auto");
    expect(useThemeStore.getState().hydrated).toBe(true);

    mock.__reset();
    await AsyncStorage.setItem(KEY, JSON.stringify({ mode: "disco" }));
    useThemeStore.setState({ mode: "auto", hydrated: false });
    await useThemeStore.getState().hydrate();
    expect(useThemeStore.getState().mode).toBe("auto");
    expect(useThemeStore.getState().hydrated).toBe(true);
  });
});

describe("the two Platinum worlds", () => {
  it("platinum is byte-for-byte the shipped light palette", () => {
    expect(platinumTheme.colors).toBe(colors);
    expect(platinumTheme.platinum).toBe(platinum);
    expect(platinumTheme.dark).toBe(false);
  });

  it("midnight carries the SAME token contract — no key drifts", () => {
    expect(Object.keys(midnightTheme.colors).sort()).toEqual(Object.keys(colors).sort());
    expect(Object.keys(midnightTheme.platinum).sort()).toEqual(Object.keys(platinum).sort());
    expect(midnightTheme.platinum.stripe).toHaveLength(3);
  });

  it("midnight keeps the Platinum construction — the hard black frame", () => {
    expect(midnightTheme.platinum.frame).toBe("#000000");
    expect(midnightTheme.dark).toBe(true);
    expect(themes.midnight).toBe(midnightTheme);
    expect(themes.platinum).toBe(platinumTheme);
  });
});
