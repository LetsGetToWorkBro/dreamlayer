/**
 * useThemeStore — which Platinum world the phone wears.
 *
 * Three modes: "platinum" (the light Mac OS 8.1 desktop), "midnight" (the
 * dark one), and "auto" — follow the OS appearance. Default is "auto", the
 * respectful choice: the app looks like the phone until you say otherwise.
 *
 * The choice persists across launches (AsyncStorage, same pattern as
 * useBrainStore). Resolution from mode → concrete theme name lives here as a
 * pure function so the logic layer can test it without a React runtime; the
 * React side (src/ui/theme/useTheme.ts) feeds it useColorScheme().
 */
import { create } from "zustand";
import AsyncStorage from "@react-native-async-storage/async-storage";
import type { ThemeName } from "../ui/theme/themes";

export type ThemeMode = ThemeName | "auto";

/** platinum → midnight → auto → platinum — the Appearance row's cycle order. */
export const THEME_MODES: readonly ThemeMode[] = ["platinum", "midnight", "auto"];

/** mode + the OS scheme → the concrete theme to draw. Pure; no React. */
export function resolveThemeName(
  mode: ThemeMode,
  systemScheme?: "light" | "dark" | null,
): ThemeName {
  if (mode === "auto") return systemScheme === "dark" ? "midnight" : "platinum";
  return mode;
}

type ThemeState = {
  mode: ThemeMode;
  hydrated: boolean;
  setMode: (mode: ThemeMode) => void;
  /** step to the next mode in THEME_MODES order (the tap-to-cycle control) */
  cycleMode: () => void;
  /** the concrete theme for a given OS scheme (auto follows it) */
  resolved: (systemScheme?: "light" | "dark" | null) => ThemeName;
  hydrate: () => Promise<void>;
};

const KEY = "dreamlayer.theme.v1";

function isMode(v: unknown): v is ThemeMode {
  return v === "platinum" || v === "midnight" || v === "auto";
}

function persist(mode: ThemeMode) {
  AsyncStorage.setItem(KEY, JSON.stringify({ mode })).catch(() => {});
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  mode: "auto",
  hydrated: false,

  setMode: (mode) => {
    if (!isMode(mode)) return;
    set({ mode });
    persist(mode);
  },

  cycleMode: () => {
    const i = THEME_MODES.indexOf(get().mode);
    const next = THEME_MODES[(i + 1) % THEME_MODES.length] ?? "auto";
    get().setMode(next);
  },

  resolved: (systemScheme) => resolveThemeName(get().mode, systemScheme),

  hydrate: async () => {
    try {
      const raw = await AsyncStorage.getItem(KEY);
      if (raw) {
        const snap: unknown = JSON.parse(raw);
        const mode = (snap as { mode?: unknown } | null)?.mode;
        set({ mode: isMode(mode) ? mode : "auto", hydrated: true });
        return;
      }
    } catch {
      /* fall through to defaults */
    }
    set({ hydrated: true });
  },
}));
