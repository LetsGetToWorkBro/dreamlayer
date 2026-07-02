import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { colors } from "../theme/colors";
import { typography } from "../theme/typography";

/** A small live/paused indicator for the Now header. */
export function StatusPill({ paused }: { paused: boolean }) {
  const tint = paused ? colors.statusPaused : colors.accentSuccess;
  return (
    <View style={[s.pill, { borderColor: tint }]}>
      <View style={[s.dot, { backgroundColor: tint }]} />
      <Text style={[typography.caption, { color: tint }]}>{paused ? "Paused" : "Live"}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 999,
    paddingVertical: 6,
    paddingHorizontal: 12,
    gap: 7,
  },
  dot: { width: 7, height: 7, borderRadius: 4 },
});
