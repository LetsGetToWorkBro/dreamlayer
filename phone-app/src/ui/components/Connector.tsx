import React from "react";
import { View, Text, Switch, StyleSheet } from "react-native";
import { colors, platinum } from "../theme/colors";
import { typography } from "../theme/typography";
import { Tappable } from "./Tappable";

/** A group box for one connector (glasses, Mac mini, cloud, incognito) — a
 * raised platinum panel with an LED, a Chicago heading, and a status readout. */
export function ConnectorCard({
  title,
  status,
  accent = colors.accentMemory,
  on,
  children,
}: {
  title: string;
  status?: string;
  accent?: string;
  on?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <View style={[s.card, on ? { borderColor: accent, borderWidth: 1.5 } : null]}>
      <View style={s.cardHead}>
        <View style={[s.dot, { backgroundColor: on ? accent : colors.statusPaused }]} />
        <Text style={[typography.title, { color: colors.textPrimary, flex: 1 }]}>{title}</Text>
        {status ? (
          <Text style={[typography.caption, { color: on ? accent : colors.textSecondary, opacity: 1 }]}>{status}</Text>
        ) : null}
      </View>
      {children}
    </View>
  );
}

/** A labelled switch with an explanatory subtitle. */
export function SwitchRow({
  label,
  sub,
  value,
  onValueChange,
  disabled,
  accent = colors.accentMemory,
}: {
  label: string;
  sub?: string;
  value: boolean;
  onValueChange: (v: boolean) => void;
  disabled?: boolean;
  accent?: string;
}) {
  return (
    <View style={[s.row, disabled ? { opacity: 0.5 } : null]}>
      <View style={{ flex: 1, paddingRight: 12 }}>
        <Text style={[typography.body, { color: colors.textPrimary }]}>{label}</Text>
        {sub ? <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>{sub}</Text> : null}
      </View>
      <Switch
        value={value}
        onValueChange={onValueChange}
        disabled={disabled}
        trackColor={{ true: accent, false: platinum.sh }}
        thumbColor={platinum.well}
        ios_backgroundColor={platinum.sh}
      />
    </View>
  );
}

/** A single benefit bullet. */
export function Bullet({ children, muted }: { children: React.ReactNode; muted?: boolean }) {
  return (
    <View style={s.bullet}>
      <Text style={{ color: muted ? colors.textSecondary : colors.accentMemory, marginRight: 8 }}>
        {muted ? "–" : "✓"}
      </Text>
      <Text style={[typography.caption, { color: colors.textSecondary, flex: 1 }]}>{children}</Text>
    </View>
  );
}

/** A beveled push button for "Connect" / "Pair" affordances. Solid teal for a
 * primary action; `ghost` for a plain platinum push button. */
export function PillButton({
  label,
  onPress,
  accent = colors.accentMemory,
  ghost,
}: {
  label: string;
  onPress: () => void;
  accent?: string;
  ghost?: boolean;
}) {
  return (
    <Tappable
      onPress={onPress}
      scaleTo={0.97}
      style={[s.pill, ghost ? { backgroundColor: platinum.face } : { backgroundColor: accent }]}
    >
      <View style={s.pillBevel} pointerEvents="none" />
      <Text
        style={[
          typography.title,
          s.pillLabel,
          { color: ghost ? platinum.ink : platinum.well },
        ]}
      >
        {label}
      </Text>
    </Tappable>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: platinum.face,
    borderRadius: 10,
    borderTopColor: platinum.hi,
    borderLeftColor: platinum.hi,
    borderBottomColor: platinum.sh,
    borderRightColor: platinum.sh,
    borderWidth: 1.5,
    padding: 18,
    marginBottom: 14,
  },
  cardHead: { flexDirection: "row", alignItems: "center", marginBottom: 10, gap: 0 },
  dot: { width: 9, height: 9, borderRadius: 5, marginRight: 10, borderWidth: 0.5, borderColor: "rgba(0,0,0,0.35)" },
  row: { flexDirection: "row", alignItems: "center", paddingVertical: 8 },
  bullet: { flexDirection: "row", alignItems: "flex-start", marginTop: 6 },
  pill: {
    borderRadius: 8,
    borderWidth: 1.5,
    borderColor: platinum.frame,
    paddingVertical: 11,
    paddingHorizontal: 22,
    alignItems: "center",
    marginTop: 12,
    overflow: "hidden",
  },
  pillBevel: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    borderTopWidth: 1,
    borderLeftWidth: 1,
    borderTopColor: "rgba(255,255,255,0.5)",
    borderLeftColor: "rgba(255,255,255,0.36)",
  },
  pillLabel: { fontSize: 15, lineHeight: 20 },
});
