import React from "react";
import { Animated, View, Text, StyleSheet } from "react-native";
import { colors } from "../theme/colors";
import { typography } from "../theme/typography";
import { space } from "../theme/spacing";
import { useEntrance } from "../anim";

/**
 * EmptyState — a calm, on-brand nothing: a soft halo ring, a line, and an
 * optional hint. No screen should ever render as a blank void.
 */
export function EmptyState({ glyph = "◌", title, hint }: { glyph?: string; title: string; hint?: string }) {
  const anim = useEntrance(80);
  return (
    <Animated.View style={[s.wrap, anim]}>
      <View style={s.ring}>
        <Text style={s.glyph}>{glyph}</Text>
      </View>
      <Text style={[typography.body, { color: colors.textPrimary, marginTop: space.xl, textAlign: "center" }]}>{title}</Text>
      {hint ? (
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm, textAlign: "center", maxWidth: 280 }]}>
          {hint}
        </Text>
      ) : null}
    </Animated.View>
  );
}

const s = StyleSheet.create({
  wrap: { alignItems: "center", justifyContent: "center", paddingVertical: space.huge },
  ring: {
    width: 96,
    height: 96,
    borderRadius: 48,
    borderWidth: 1.5,
    borderColor: colors.borderSubtle,
    alignItems: "center",
    justifyContent: "center",
  },
  glyph: { fontSize: 34, color: colors.statusPaused },
});
