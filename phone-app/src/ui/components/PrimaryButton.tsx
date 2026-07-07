import { Text, View, ViewStyle, StyleSheet } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { colors } from "../theme/colors";
import { typography } from "../theme/typography";
import { radius, space } from "../theme/spacing";
import { Tappable } from "./Tappable";

type Props = { label: string; onPress: () => void; accent?: string; style?: ViewStyle };

/**
 * PrimaryButton — a luminous pill. A two-stop gradient in the accent gives the
 * fill depth, a colored glow lifts it off the glass, and a hairline top sheen
 * reads as light catching the edge. `accent="attention"` swaps teal for coral.
 */
export function PrimaryButton({ label, onPress, accent, style }: Props) {
  const attention = accent === "attention";
  const tint = attention ? colors.accentAttention : colors.accentMemory;
  const stops: [string, string] = attention
    ? ["#FF8A7E", "#F0574A"]
    : ["#43E7D6", "#1FB9AB"];
  return (
    <Tappable
      onPress={onPress}
      scaleTo={0.97}
      style={[s.shadow, { shadowColor: tint }, style]}
    >
      <LinearGradient
        colors={stops}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={s.fill}
      >
        <View style={s.sheen} pointerEvents="none" />
        <Text style={[typography.title, s.label]}>{label}</Text>
      </LinearGradient>
    </Tappable>
  );
}

const s = StyleSheet.create({
  shadow: {
    borderRadius: radius.pill,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.4,
    shadowRadius: 18,
    elevation: 8,
  },
  fill: {
    borderRadius: radius.pill,
    paddingVertical: space.lg,
    paddingHorizontal: space.huge,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  sheen: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    height: "50%",
    backgroundColor: "rgba(255,255,255,0.22)",
  },
  label: { color: colors.background, letterSpacing: 0.2 },
});
