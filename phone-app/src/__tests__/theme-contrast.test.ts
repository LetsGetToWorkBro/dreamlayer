/**
 * theme-contrast.test.ts — the theme tokens have to be READABLE (#565).
 *
 * Midnight's secondary ink was `#9FA6AA` on the `#3E4044` window face: 4.21:1,
 * under the 4.5:1 WCAG AA floor for normal text. Nothing measured it, so it
 * shipped — the most visible instance being a shaded `WindowShade` title bar,
 * where the title draws `platinum.ink2` on `platinum.face` with the pinstripe
 * suppressed behind it.
 *
 * A contrast ratio is a pure function of two tokens, so it is checkable without
 * rendering anything, on every pairing the app actually uses, in both themes.
 * That is what this file does — it is a property of the palette, not a snapshot,
 * so it cannot rot the way a recorded screenshot would.
 *
 * The maths is WCAG 2.x relative luminance (sRGB, the 0.03928 knee), written out
 * rather than pulled from a dependency so the test has no opinion to be wrong
 * about beyond the spec itself.
 */
import { themes, type ThemeName } from "../ui/theme/themes";

const AA_NORMAL = 4.5; // WCAG AA, normal-size text
// (no AA_LARGE floor is enforced — see the note about `ink3` in pairings())

function channel(hex: string, at: number): number {
  const v = parseInt(hex.replace("#", "").slice(at, at + 2), 16) / 255;
  return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}

function luminance(hex: string): number {
  return (
    0.2126 * channel(hex, 0) + 0.7152 * channel(hex, 2) + 0.0722 * channel(hex, 4)
  );
}

function contrast(a: string, b: string): number {
  const [la, lb] = [luminance(a), luminance(b)];
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** Ink/background pairings the app genuinely draws, named as the UI names them. */
function pairings(t: (typeof themes)[ThemeName]) {
  const c = t.colors;
  const p = t.platinum;
  return [
    // semantic tokens
    ["textPrimary on surface", c.textPrimary, c.surface, AA_NORMAL],
    ["textPrimary on background", c.textPrimary, c.background, AA_NORMAL],
    ["textPrimary on surfaceElevated", c.textPrimary, c.surfaceElevated, AA_NORMAL],
    ["textSecondary on surface", c.textSecondary, c.surface, AA_NORMAL],
    ["textSecondary on background", c.textSecondary, c.background, AA_NORMAL],
    ["textSecondary on surfaceElevated", c.textSecondary, c.surfaceElevated, AA_NORMAL],
    // raw platinum materials — this is the pairing #565 was actually about:
    // a shut WindowShade draws `ink2` on `face` (Card.tsx) with no pinstripe.
    ["ink on face", p.ink, p.face, AA_NORMAL],
    ["ink on well", p.ink, p.well, AA_NORMAL],
    ["ink on paper", p.ink, p.paper, AA_NORMAL],
    ["ink2 on face", p.ink2, p.face, AA_NORMAL],
    ["ink2 on well", p.ink2, p.well, AA_NORMAL],
    ["ink2 on paper", p.ink2, p.paper, AA_NORMAL],
    // `ink3` is deliberately ABSENT. It is the menu-disabled ink and nothing in
    // `src/` or `app/` currently renders it — asserting a floor on a token no
    // screen draws would be asserting about nothing, and holding it to one would
    // have meant darkening a colour to satisfy a rule invented here rather than
    // one the design owes anybody. (Disabled text is exempt from the AA contrast
    // requirement in any case — WCAG 1.4.3.) The ordering check below still
    // pins it as the dimmest of the three, which is what the token means.
  ] as const;
}

describe.each(Object.keys(themes) as ThemeName[])("%s theme contrast", (name) => {
  const theme = themes[name];

  it.each(pairings(theme).map((p) => [p[0], p[1], p[2], p[3]]))(
    "%s clears its WCAG AA floor",
    (label, fg, bg, floor) => {
      const ratio = contrast(fg as string, bg as string);
      expect({ label, fg, bg, ratio: Number(ratio.toFixed(2)) }).toMatchObject({
        ratio: expect.any(Number),
      });
      // the assertion proper, with the numbers in the message so a failure says
      // WHAT to change rather than only that something is wrong
      if (ratio < (floor as number)) {
        throw new Error(
          `${name}: ${label} — ${fg} on ${bg} is ${ratio.toFixed(2)}:1, ` +
            `below the ${floor}:1 floor`,
        );
      }
    },
  );

  it("secondary ink is dimmer than primary ink, not merely legible", () => {
    // The cheap way to pass the test above is to lift secondary ink until it
    // matches primary, which would fix the number and destroy the hierarchy.
    const onFace = (c: string) => contrast(c, theme.platinum.face);
    expect(onFace(theme.platinum.ink2)).toBeLessThan(onFace(theme.platinum.ink));
    expect(onFace(theme.platinum.ink3)).toBeLessThan(onFace(theme.platinum.ink2));
  });
});

describe("the contrast maths itself", () => {
  // A bug in the helper would make every assertion above vacuous, so pin it
  // against values from the WCAG spec's own worked examples.
  it("computes the known extremes", () => {
    expect(contrast("#FFFFFF", "#000000")).toBeCloseTo(21, 5);
    expect(contrast("#000000", "#FFFFFF")).toBeCloseTo(21, 5);
    expect(contrast("#FFFFFF", "#FFFFFF")).toBeCloseTo(1, 5);
  });

  it("reproduces the ratio reported in #565", () => {
    // The exact pair from the issue, kept as a fixture so the regression is
    // named and not merely covered by the sweep above.
    expect(contrast("#9FA6AA", "#3E4044")).toBeCloseTo(4.21, 2);
    expect(contrast("#9FA6AA", "#3E4044")).toBeLessThan(AA_NORMAL);
  });

  it("is symmetric", () => {
    expect(contrast("#9FA6AA", "#3E4044")).toBeCloseTo(contrast("#3E4044", "#9FA6AA"), 10);
  });
});
