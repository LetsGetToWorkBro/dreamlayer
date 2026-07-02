import React from "react";
import { Animated, View, Text, StyleSheet, StyleProp, ViewStyle } from "react-native";
import { colors } from "../theme/colors";
import { typography } from "../theme/typography";
import { radius, space } from "../theme/spacing";
import { useEntrance } from "../anim";
import { Tappable } from "./Tappable";

/**
 * Card — the standard surface. One radius, one border, one padding. When
 * `active` it takes the accent edge; when `onPress` is given it becomes a
 * tactile Tappable. `delay` staggers a column of cards into view.
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
  const body = <View style={[s.card, active ? { borderColor: accent } : null, style]}>{children}</View>;
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
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: space.lg,
    marginBottom: space.md,
  },
});
