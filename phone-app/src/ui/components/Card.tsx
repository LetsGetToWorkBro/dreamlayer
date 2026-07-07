import React from "react";
import { Animated, View, Text, StyleSheet, StyleProp, ViewStyle, Platform } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { colors } from "../theme/colors";
import { typography } from "../theme/typography";
import { radius, space } from "../theme/spacing";
import { useEntrance } from "../anim";
import { Tappable } from "./Tappable";

/**
 * Card — the standard glass surface. A translucent panel over the cinematic
 * backdrop with a faint top sheen and a soft lift, so cards read as luminous
 * glass (matching the Mac panel). `active` takes the accent edge + glow;
 * `onPress` makes it a tactile Tappable; `delay` staggers a column into view.
 */
export function Card({
  children,
  active,
  accent = colors.accentMemory,
  onPress,
  style,
  delay = 0,
  animate = true,
}: {
  children: React.ReactNode;
  active?: boolean;
  accent?: string;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
  delay?: number;
  animate?: boolean;
}) {
  const anim = useEntrance(delay);
  const body = (
    <View style={[s.card, active ? { borderColor: accent, shadowColor: accent, shadowOpacity: 0.28 } : null, style]}>
      <LinearGradient
        colors={["rgba(255,255,255,0.06)", "rgba(255,255,255,0)"]}
        start={{ x: 0.1, y: 0 }}
        end={{ x: 0.5, y: 0.9 }}
        style={s.sheen}
        pointerEvents="none"
      />
      {children}
    </View>
  );
  const wrapped = onPress ? <Tappable onPress={onPress}>{body}</Tappable> : body;
  if (!animate) return wrapped;
  return <Animated.View style={anim}>{wrapped}</Animated.View>;
}

/** A small uppercase section label with consistent spacing above it. */
export function Section({ label, accent = colors.accentMemory, first }: { label: string; accent?: string; first?: boolean }) {
  return (
    <Text style={[typography.eyebrow, { color: accent, marginTop: first ? 0 : space.xl, marginBottom: space.md }]}>
      {label}
    </Text>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: "rgba(20, 31, 35, 0.64)",
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: "rgba(140, 190, 190, 0.14)",
    padding: space.lg,
    marginBottom: space.md,
    overflow: "hidden",
    // soft lift
    shadowColor: "#000000",
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.35,
    shadowRadius: 22,
    ...(Platform.OS === "android" ? { elevation: 6 } : null),
  },
  sheen: { position: "absolute", top: 0, left: 0, right: 0, height: "60%" },
});
