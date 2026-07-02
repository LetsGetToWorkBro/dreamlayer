import React from "react";
import { Animated, View, Text, StyleSheet } from "react-native";
import { colors } from "../theme/colors";
import { typography } from "../theme/typography";
import { space } from "../theme/spacing";
import { useEntrance } from "../anim";

/**
 * ScreenHeader — the large title block. Optional eyebrow above and a right-hand
 * slot (a status pill, an action). Rises in on mount so every screen opens the
 * same calm way.
 */
export function ScreenHeader({
  title,
  eyebrow,
  subtitle,
  right,
}: {
  title: string;
  eyebrow?: string;
  subtitle?: string;
  right?: React.ReactNode;
}) {
  const anim = useEntrance(0);
  return (
    <Animated.View style={[s.wrap, anim]}>
      <View style={{ flex: 1 }}>
        {eyebrow ? <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: space.xs }]}>{eyebrow}</Text> : null}
        <Text style={[typography.display, { color: colors.textPrimary }]}>{title}</Text>
        {subtitle ? <Text style={[typography.body, { color: colors.textSecondary, marginTop: space.xs }]}>{subtitle}</Text> : null}
      </View>
      {right ? <View style={s.right}>{right}</View> : null}
    </Animated.View>
  );
}

const s = StyleSheet.create({
  wrap: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", marginBottom: space.lg },
  right: { paddingTop: space.sm, paddingLeft: space.md },
});
