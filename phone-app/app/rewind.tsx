import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { useBrainStore, RewindBlock } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";

const KIND_COLOR: Record<string, string> = {
  message: colors.accentMemory,
  event: "#3D63C7",
  people: colors.accentSuccess,
  ask: colors.accentAttention,
  "cloud-egress": colors.accentAttention,
};

function kindLabel(kind: string): string {
  if (kind === "cloud-egress") return "cloud";
  if (kind === "ask") return "asked";
  return kind;
}

export default function Rewind() {
  const macConnected = useBrainStore((s) => s.macMini.connected || s.demoMode);
  const getRewind = useBrainStore((s) => s.getRewind);
  const [blocks, setBlocks] = React.useState<RewindBlock[] | null>(null);

  const load = React.useCallback(async () => {
    setBlocks(await getRewind());
  }, [getRewind]);

  React.useEffect(() => {
    if (macConnected) load();
    else setBlocks([]);
  }, [macConnected, load]);

  const total = (blocks ?? []).reduce((n, b) => n + b.count, 0);

  return (
    <Screen>
      <ScreenHeader
        title="Rewind"
        eyebrow="Your day"
        subtitle={total ? `${total} moments across the day` : undefined}
      />

      {!macConnected ? (
        <EmptyState
          title="Connect your Mac mini"
          hint="Rewind stitches your day — messages, events, and what the Brain did — into one timeline. It lives on your Mac mini."
        />
      ) : blocks === null ? (
        <EmptyState title="Rewinding…" hint="Gathering the day." />
      ) : blocks.length === 0 ? (
        <EmptyState title="Nothing yet today" hint="As the day fills in — messages, events, questions — it lands here hour by hour." />
      ) : (
        blocks.map((b, bi) => (
          <View key={b.hour}>
            <Section label={b.label} first={bi === 0} accent={colors.textSecondary} />
            {b.items.map((it, i) => {
              const tint = KIND_COLOR[it.kind] ?? colors.textSecondary;
              return (
                <Card key={`${b.hour}-${i}`} delay={bi * 50 + i * 35}>
                  <View style={s.row}>
                    <View style={[s.tag, { backgroundColor: tint }]} />
                    <View style={{ flex: 1 }}>
                      <Text style={[typography.eyebrow, { color: tint }]}>{kindLabel(it.kind)}</Text>
                      <Text style={[typography.body, { color: colors.textPrimary, marginTop: space.xs }]}>{it.text}</Text>
                    </View>
                  </View>
                </Card>
              );
            })}
          </View>
        ))
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "stretch", gap: space.md },
  tag: { width: 3, borderRadius: radius.sm, alignSelf: "stretch" },
});
