/**
 * themes.ts — the two Platinum worlds.
 *
 * "platinum" is the shipped Mac OS 8.1 light desktop, byte-for-byte the values
 * in colors.ts. "midnight" is the same CONSTRUCTION — hard bevels, black
 * frames, hard shadows, pinstripes — rebuilt from graphite: charcoal window
 * faces, dark inset wells, pale ink. Only colors differ between the two;
 * spacing, radii, and type never move.
 *
 * The token KEYS stay the app-wide contract (`colors.*` semantic tokens,
 * `platinum.*` raw materials); themes swap VALUES underneath them. Screens get
 * the active set through useTheme()/makeThemedStyles() in ./useTheme — nothing
 * should import this file's midnight objects directly.
 *
 * The Halo world (DreamCanvas, HaloMirror, CardPreview) draws with haloPalette
 * and is its own dark universe in BOTH themes — the glasses don't reskin.
 */
import { colors, platinum } from "./colors";

/** The semantic token set, widened to plain strings so themes can swap values. */
export type ColorSet = { [K in keyof typeof colors]: string };
/** The raw Platinum materials, widened the same way (stripe stays a 3-stop tuple). */
export type PlatinumSet = { [K in keyof Omit<typeof platinum, "stripe">]: string } & {
  stripe: readonly [string, string, string];
};

export type ThemeName = "platinum" | "midnight";

export type Theme = {
  name: ThemeName;
  /** true when the chrome itself is dark (midnight) — for one-off tuning */
  dark: boolean;
  colors: ColorSet;
  platinum: PlatinumSet;
};

/* ------------------------------------------------------------- midnight --
 * Midnight Platinum. The desk drops to near-black graphite, window faces to
 * charcoal, wells become dark inset paper, and the ink inverts to a soft
 * off-white. The bevel logic is unchanged — light still falls from the
 * top-left, it's just moonlight now. Accents: the brand teal flips to its own
 * dark-world chip teal (#2FD4C4 — already in the light palette for exactly
 * this job), coral to the Halo coral, success/error to their dark-legible
 * Halo siblings, and the classic selection blue lifts to #7B87FF so it still
 * glows on charcoal. */

const midnightColors: ColorSet = {
  background:       "#202225",  // the midnight desktop behind every window
  surface:          "#3E4044",  // window / control face (the 3D charcoal)
  surfaceElevated:  "#292B2E",  // dark content wells, inputs, list rows
  textPrimary:      "#E6E8E9",  // pale ink — titles, answers
  textSecondary:    "#9FA6AA",  // secondary ink — captions, supporting copy
  accentMemory:     "#2FD4C4",  // the brand teal's dark-chip voice — "on"
  accentAttention:  "#E06B52",  // coral, dark-legible (the Halo coral)
  accentSuccess:    "#56D364",  // confirmations, live (dark-legible)
  accentError:      "#E05252",  // destructive, unsigned (dark-legible)
  borderSubtle:     "#55585D",  // the bevel-highlight line / hairline frame
  statusPaused:     "#8FA8B2",  // muted / disabled (lifted to read on dark)
  shimmer:          "#33363A",  // loading wash on dark
};

const midnightPlatinum: PlatinumSet = {
  desk:     "#202225",   // desktop base (pinstriped over)
  deskLine: "#191B1E",   // the darker line in the desktop pinstripe
  paper:    "#292B2E",   // darkest panel / menu paper (the inset reading well)
  face:     "#3E4044",   // window & control face
  face2:    "#33363A",   // a step down (button gradient bottom)
  faceHi:   "#4A4D52",   // a step up (button gradient top)
  well:     "#292B2E",   // dark content well
  hi:       "#55585D",   // bevel highlight (top-left)
  sh:       "#232529",   // bevel shadow (bottom-right)
  dk:       "#0E0F10",   // deep shadow
  frame:    "#000000",   // the hard 1px window frame — non-negotiable
  ink:      "#E6E8E9",
  ink2:     "#9FA6AA",
  ink3:     "#7C8388",   // dimmest ink (menu disabled)
  tealInk:  "#2FD4C4",   // text-safe teal on dark = the brand's chip teal
  teal:     "#2FD4C4",   // bright teal, unchanged — it was born for dark
  coralInk: "#E06B52",
  menuHi:   "#7B87FF",   // the selection blue, lifted for dark
  select:   "#7B87FF",   // focus/selection blue on controls
  line:     "#4A4D50",   // hairline row separator inside dark panels
  // title-bar pinstripe stops (light → mid → dark), 1px each
  stripe:   ["#4E5157", "#3E4044", "#2C2E31"],
};

export const platinumTheme: Theme = {
  name: "platinum",
  dark: false,
  colors,
  platinum,
};

export const midnightTheme: Theme = {
  name: "midnight",
  dark: true,
  colors: midnightColors,
  platinum: midnightPlatinum,
};

export const themes: Record<ThemeName, Theme> = {
  platinum: platinumTheme,
  midnight: midnightTheme,
};
