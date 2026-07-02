import React from "react";
import { View, Text, Switch, StyleSheet } from "react-native";
import { colors } from "../theme/colors";
import { typography } from "../theme/typography";
import { Tappable } from "./Tappable";

/** A card grouping one connector (glasses, Mac mini, cloud, incognito). */
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
    <View style={[s.card, on ? { borderColor: accent } : null]}>
      <View style={s.cardHead}>
        <View style={[s.dot, { backgroundColor: on ? accent : colors.statusPaused }]} />
        <Text style={[typography.title, { color: colors.textPrimary, flex: 1 }]}>{title}</Text>
        {status ? (
          <Text style={[typography.caption, { color: on ? accent : colors.textSecondary }]}>{status}</Text>
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
        trackColor={{ true: accent, false: colors.borderSubtle }}
        thumbColor={colors.textPrimary}
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

/** A pill button used for "Connect" / "Pair" affordances. */
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
      style={[
        s.pill,
        ghost
          ? { borderWidth: 1, borderColor: colors.borderSubtle, backgroundColor: "transparent" }
          : { backgroundColor: accent },
      ]}
    >
      <Text style={[typography.body, { fontWeight: "600", color: ghost ? colors.textSecondary : colors.background }]}>
        {label}
      </Text>
    </Tappable>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: 18,
    marginBottom: 14,
  },
  cardHead: { flexDirection: "row", alignItems: "center", marginBottom: 10 },
  dot: { width: 9, height: 9, borderRadius: 5, marginRight: 10 },
  row: { flexDirection: "row", alignItems: "center", paddingVertical: 8 },
  bullet: { flexDirection: "row", alignItems: "flex-start", marginTop: 6 },
  pill: { borderRadius: 999, paddingVertical: 12, paddingHorizontal: 22, alignItems: "center", marginTop: 12 },
});
