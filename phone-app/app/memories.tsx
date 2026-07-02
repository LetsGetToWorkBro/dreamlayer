import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { useMemoryStore, Memory } from "../src/state/useMemoryStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";

const KIND_COLOR: Record<string, string> = {
  Promise: colors.accentAttention,
  Person: colors.accentMemory,
  Object: colors.accentSuccess,
  Place: "#8FB8FF",
  Note: colors.textSecondary,
};

const DAY = 86_400_000;
function bucketOf(ts: number): string {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const t0 = startOfToday.getTime();
  if (ts >= t0) return "Today";
  if (ts >= t0 - DAY) return "Yesterday";
  return "Earlier";
}

function group(memories: Memory[]): { label: string; items: Memory[] }[] {
  const order = ["Today", "Yesterday", "Earlier"];
  const by: Record<string, Memory[]> = {};
  for (const m of memories) (by[bucketOf(m.ts)] ??= []).push(m);
  return order.filter((l) => by[l]?.length).map((label) => ({ label, items: by[label] }));
}

export default function Memories() {
  const memories = useMemoryStore((s) => s.memories);
  const groups = group([...memories].sort((a, b) => b.ts - a.ts));

  return (
    <Screen>
      <ScreenHeader
        title="Memories"
        eyebrow="Your recall"
        subtitle={memories.length ? `${memories.length} kept` : undefined}
      />

      {groups.length === 0 ? (
        <EmptyState title="No memories yet" hint="Put on your Halo and live — the moments that matter get kept here, never raw recordings." />
      ) : (
        groups.map((g, gi) => (
          <View key={g.label}>
            <Section label={g.label} first={gi === 0} accent={colors.textSecondary} />
            {g.items.map((m, i) => {
              const tint = KIND_COLOR[m.kind] ?? colors.textSecondary;
              return (
                <Card key={m.id} delay={gi * 60 + i * 45}>
                  <View style={s.row}>
                    <View style={[s.tag, { backgroundColor: tint }]} />
                    <View style={{ flex: 1 }}>
                      <View style={s.metaRow}>
                        <Text style={[typography.eyebrow, { color: tint }]}>{m.kind}</Text>
                        <Text style={[typography.caption, { color: colors.textSecondary }]}>{m.createdAt}</Text>
                      </View>
                      <Text style={[typography.body, { color: colors.textPrimary, marginTop: space.xs }]}>{m.summary}</Text>
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
  metaRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
});
