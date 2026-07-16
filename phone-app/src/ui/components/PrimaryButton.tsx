import { Text, View, ViewStyle, StyleSheet } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { platinum } from "../theme/colors";
import { typography } from "../theme/typography";
import { radius, space } from "../theme/spacing";
import { Tappable } from "./Tappable";

type Props = { label: string; onPress: () => void; accent?: string; style?: ViewStyle };

/**
 * PrimaryButton — the Mac OS 8.1 default push button. A beveled rectangle with a
 * bold black ring (the "this is the default action" cue), a top-lit gradient
 * face, and a Chicago label. The default action wears the brand teal;
 * `accent="attention"` swaps it for coral. Tappable still gives the press its
 * scale + haptic tick.
 */
export function PrimaryButton({ label, onPress, accent, style }: Props) {
  const attention = accent === "attention";
  const stops: [string, string] = attention
    ? ["#E8846F", "#B3402E"]
    : ["#49E8BC", "#12A588"];
  const labelColor = attention ? "#2A0B06" : "#00251C";
  return (
    <Tappable onPress={onPress} scaleTo={0.97} style={[s.ring, style]}>
      <LinearGradient colors={stops} start={{ x: 0, y: 0 }} end={{ x: 0, y: 1 }} style={s.fill}>
        <View style={s.bevel} pointerEvents="none" />
        <Text style={[typography.title, s.label, { color: labelColor }]}>{label}</Text>
      </LinearGradient>
    </Tappable>
  );
}

const s = StyleSheet.create({
  // the bold black default-button ring + a hard drop shadow
  ring: {
    borderRadius: radius.sm,
    borderWidth: 2,
    borderColor: platinum.frame,
    overflow: "hidden",
    shadowColor: "#000000",
    shadowOffset: { width: 1, height: 2 },
    shadowOpacity: 0.3,
    shadowRadius: 0,
    elevation: 4,
  },
  fill: {
    paddingVertical: space.md,
    paddingHorizontal: space.xxl,
    alignItems: "center",
    justifyContent: "center",
  },
  // top-left highlight edge (the raised bevel), drawn as a 1px inner border
  bevel: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    borderTopWidth: 1,
    borderLeftWidth: 1,
    borderTopColor: "rgba(255,255,255,0.55)",
    borderLeftColor: "rgba(255,255,255,0.4)",
  },
  label: { fontSize: 16, lineHeight: 20, letterSpacing: 0.2 },
});
