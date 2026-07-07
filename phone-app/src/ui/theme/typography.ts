import { StyleSheet } from "react-native";
import { fonts } from "./fonts";

// Space Grotesk throughout (custom fonts ignore fontWeight in RN, so the weight
// lives in the family). Weights kept too, as a graceful fallback before the
// font loads.
export const typography = StyleSheet.create({
  display:    { fontFamily: fonts.bold,    fontSize: 36, fontWeight: "700", letterSpacing: -0.5, lineHeight: 42 },
  headline:   { fontFamily: fonts.bold,    fontSize: 26, fontWeight: "700", letterSpacing: -0.3, lineHeight: 32 },
  title:      { fontFamily: fonts.medium,  fontSize: 20, fontWeight: "600", lineHeight: 26 },
  body:       { fontFamily: fonts.regular, fontSize: 16, fontWeight: "400", lineHeight: 24 },
  caption:    { fontFamily: fonts.regular, fontSize: 13, fontWeight: "400", lineHeight: 18, opacity: 0.8 },
  eyebrow:    { fontFamily: fonts.medium,  fontSize: 11, fontWeight: "600", letterSpacing: 1.5, textTransform: "uppercase" },
  mono:       { fontFamily: fonts.mono,    fontSize: 13, lineHeight: 18 },
});
