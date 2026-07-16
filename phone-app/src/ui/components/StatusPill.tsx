import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { colors, platinum } from "../theme/colors";
import { typography } from "../theme/typography";
import { useConnectionStore } from "../../state/useConnectionStore";

/** A small live/paused indicator — a Platinum status well with a colored LED. */
export function StatusPill({ paused }: { paused: boolean }) {
  const tint = paused ? colors.statusPaused : colors.accentSuccess;
  return (
    <View style={s.pill}>
      <View style={[s.dot, { backgroundColor: tint }]} />
      <Text style={[typography.caption, s.label, { color: tint }]}>{paused ? "Paused" : "Live"}</Text>
    </View>
  );
}

/** The Brain's three honest reachability truths — home / away via relay /
 * unreachable — rendered from the single connection state machine, never a
 * per-call guess. Renders nothing while no Brain is paired. */
export function BrainPill() {
  const state = useConnectionStore((s) => s.state);
  const labelFn = useConnectionStore((s) => s.label);
  if (state === "unpaired") return null;
  const tint = state === "lan" ? colors.accentSuccess : colors.statusPaused;
  return (
    <View style={s.pill}>
      <View style={[s.dot, { backgroundColor: tint }]} />
      <Text style={[typography.caption, s.label, { color: tint }]}>{labelFn()}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    // an inset (pressed-in) well, the Platinum way to show a readout
    backgroundColor: platinum.paper,
    borderRadius: 4,
    borderTopWidth: 1,
    borderLeftWidth: 1,
    borderBottomWidth: 1,
    borderRightWidth: 1,
    borderTopColor: platinum.sh,
    borderLeftColor: platinum.sh,
    borderBottomColor: platinum.hi,
    borderRightColor: platinum.hi,
    paddingVertical: 4,
    paddingHorizontal: 9,
    gap: 6,
  },
  dot: { width: 7, height: 7, borderRadius: 4, borderWidth: 0.5, borderColor: "rgba(0,0,0,0.35)" },
  label: { opacity: 1 },
});
