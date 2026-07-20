import React from "react";
import { View, Text, ScrollView, StyleSheet } from "react-native";

import { useVitalsStore } from "../src/state/useVitalsStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { useTheme, makeThemedStyles } from "../src/ui/theme/useTheme";
import { typography } from "../src/ui/theme/typography";
import { space } from "../src/ui/theme/spacing";

const BARS = "▁▂▃▄▅▆▇█";

/** A text sparkline of the heap watermark series — no chart library. */
function Spark({ series }: { series: number[] }) {
  const { colors } = useTheme();
  if (series.length < 2) return null;
  const lo = Math.min(...series);
  const hi = Math.max(...series);
  const span = hi - lo || 1;
  const out = series
    .slice(-24)
    .map((v) => BARS[Math.round(((v - lo) / span) * (BARS.length - 1))])
    .join("");
  return <Text style={[typography.title, { color: colors.accentMemory, letterSpacing: 1 }]}>{out}</Text>;
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  const st = useSt();
  const { colors } = useTheme();
  return (
    <View style={st.stat}>
      <Text style={[typography.caption, { color: colors.textSecondary }]}>{label}</Text>
      <Text style={[typography.title, { color: accent || colors.textPrimary }]}>{value}</Text>
    </View>
  );
}

export default function Vitals() {
  const st = useSt();
  const { colors } = useTheme();
  const v = useVitalsStore();
  const rate = Math.round(v.dismissRate() * 100);

  return (
    <Screen>
      <ScreenHeader title="Device Vitals" subtitle="What your glasses report back" />
      {v.events === 0 ? (
        <EmptyState
          glyph="♡"
          title="No telemetry yet"
          hint="Pair your glasses — vitals arrive as they run (heap, crashes, dismissals)."
        />
      ) : (
        <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: space.xxxl }}>
          <Section label="Memory" first />
          <Card style={{ marginBottom: space.md }}>
            <View style={st.row}>
              <Stat label="Heap now" value={v.lastHeapKb != null ? `${v.lastHeapKb} KB` : "—"} />
              <Stat label="Peak" value={v.heap.length ? `${Math.max(...v.heap)} KB` : "—"} />
            </View>
            <View style={{ marginTop: space.sm }}>
              <Spark series={v.heap} />
            </View>
          </Card>

          <Section label="Stability" />
          <Card style={{ marginBottom: space.md }}>
            <View style={st.row}>
              <Stat label="Crashes" value={String(v.crashes)}
                accent={v.crashes ? colors.accentError : colors.accentSuccess} />
              <Stat label="Veil" value={v.veiled ? "up" : "down"} />
            </View>
            {v.lastError ? (
              <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm }]} numberOfLines={2}>
                last: {v.lastError}
              </Text>
            ) : null}
          </Card>

          <Section label="Attention" />
          <Card>
            <View style={st.row}>
              <Stat label="Cards shown" value={String(v.shown)} />
              <Stat label="Dismissed" value={String(v.dismissed)} />
              <Stat label="Dismiss rate" value={`${rate}%`}
                accent={rate > 50 ? colors.accentAttention : colors.textPrimary} />
            </View>
            <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm }]}>
              {v.banished} figment{v.banished === 1 ? "" : "s"} banished
            </Text>
          </Card>
        </ScrollView>
      )}
    </Screen>
  );
}

const useSt = makeThemedStyles(({ colors, platinum }) => StyleSheet.create({
  row: { flexDirection: "row", justifyContent: "space-between" },
  stat: { flex: 1 },
}));
