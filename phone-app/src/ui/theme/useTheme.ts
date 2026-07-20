/**
 * useTheme — the one door to the ACTIVE token sets.
 *
 * The engineering problem this solves: most files bake token values into a
 * module-level StyleSheet.create, which runs once and never re-renders on a
 * theme change. The cure, app-wide:
 *
 *   • `useTheme()` returns the live { colors, platinum } for the current mode
 *     (store choice + OS scheme). It subscribes the calling component to the
 *     theme store AND useColorScheme(), so every consumer re-renders the
 *     moment either changes — no root remount, no stale chrome.
 *
 *   • `makeThemedStyles(factory)` turns a static sheet into a themed one with
 *     a one-line diff: the factory receives the theme and (by destructuring
 *     `({ colors, platinum })`) shadows the old imports, so sheet BODIES stay
 *     byte-identical. Sheets are built once per theme and cached — two themes,
 *     two StyleSheet.create calls, ever.
 *
 * Layout metrics (spacing, radius, typography) never change between themes,
 * so only color-bearing values route through here.
 */
import { useColorScheme } from "react-native";
import { useThemeStore, resolveThemeName } from "../../state/useThemeStore";
import { themes, type Theme, type ThemeName } from "./themes";

export type { Theme, ThemeName } from "./themes";

/** The active theme — subscribes to the mode store and the OS scheme. */
export function useTheme(): Theme {
  const mode = useThemeStore((s) => s.mode);
  const scheme = useColorScheme();
  return themes[resolveThemeName(mode, scheme === "dark" ? "dark" : "light")];
}

/**
 * Build a per-theme-memoized styles hook from a factory:
 *
 *   const useS = makeThemedStyles(({ colors, platinum }) =>
 *     StyleSheet.create({ ... }));           // body unchanged from the static days
 *   ...
 *   const s = useS();                        // inside the component
 */
export function makeThemedStyles<T>(factory: (t: Theme) => T): () => T {
  const cache = new Map<ThemeName, T>();
  return function useThemedStyles(): T {
    const t = useTheme();
    let sheet = cache.get(t.name);
    if (sheet === undefined) {
      sheet = factory(t);
      cache.set(t.name, sheet);
    }
    return sheet;
  };
}
