import { Platform, StyleSheet } from "react-native";
import { fonts } from "./fonts";

/**
 * The Platinum type scale. Chicago carries the system voice — titles, hero
 * answers, card headings — the way it does on the Mac OS 8.1 desktop; Space
 * Grotesk carries the reading line so long copy and tiny meta stay legible.
 *
 * Chicago is a tall, fixed-weight bitmap face: it wants no negative tracking and
 * a touch more line-height than a modern sans. The Space Grotesk weights stay so
 * anything that renders before the fonts load degrades gracefully.
 */

// Android pads every line box above the ascender and below the descender
// ("font padding"), which sinks Chicago low in its line and drifts the whole
// vertical rhythm away from iOS. Trim it so both platforms measure text the
// same way. iOS has no such prop — a no-op there.
const trim = Platform.select({ android: { includeFontPadding: false as const }, default: null });

export const typography = StyleSheet.create({
  display:    { fontFamily: fonts.chicago, fontSize: 32, fontWeight: "400", letterSpacing: 0.2, lineHeight: 40, ...trim },
  headline:   { fontFamily: fonts.chicago, fontSize: 23, fontWeight: "400", letterSpacing: 0.2, lineHeight: 30, ...trim },
  title:      { fontFamily: fonts.chicago, fontSize: 17, fontWeight: "400", letterSpacing: 0.2, lineHeight: 24, ...trim },
  body:       { fontFamily: fonts.regular, fontSize: 16, fontWeight: "400", lineHeight: 24, ...trim },
  caption:    { fontFamily: fonts.regular, fontSize: 13, fontWeight: "400", lineHeight: 18, opacity: 0.9, ...trim },
  eyebrow:    { fontFamily: fonts.medium,  fontSize: 11, fontWeight: "600", letterSpacing: 1.5, textTransform: "uppercase", ...trim },
  mono:       { fontFamily: fonts.mono,    fontSize: 13, lineHeight: 18, ...trim },
});
