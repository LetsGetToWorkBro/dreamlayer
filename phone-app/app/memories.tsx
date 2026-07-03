import React from "react";
import { View, Text, TextInput, StyleSheet } from "react-native";
import { useMemoryStore, Memory } from "../src/state/useMemoryStore";
import { useBrainStore } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { Tappable } from "../src/ui/components/Tappable";
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
  return order.filter((l) => by[l]?.length).map((label) => ({ label, items: by[label] ?? [] }));
}

export default function Memories() {
  const memories = useMemoryStore((s) => s.memories);
  const macConnected = useBrainStore((s) => s.macMini.connected);
  const ask = useBrainStore((s) => s.ask);

  const [q, setQ] = React.useState("");
  const [recall, setRecall] = React.useState<{ text: string; sources: string[]; tier: string } | null>(null);
  const [asking, setAsking] = React.useState(false);

  const query = q.trim().toLowerCase();
  const filtered = query
    ? memories.filter(
        (m) => m.summary.toLowerCase().includes(query) || m.kind.toLowerCase().includes(query),
      )
    : memories;
  const groups = group([...filtered].sort((a, b) => b.ts - a.ts));

  const doRecall = async () => {
    if (!q.trim() || !macConnected) return;
    setAsking(true);
    const r = await ask(q.trim());
    setRecall(r ? { text: r.text, sources: r.sources ?? [], tier: r.tier } : null);
    setAsking(false);
  };

  return (
    <Screen>
      <ScreenHeader
        title="Memories"
        eyebrow="Your recall"
        subtitle={memories.length ? `${memories.length} kept` : undefined}
      />

      <View style={s.searchRow}>
        <TextInput
          value={q}
          onChangeText={(t) => {
            setQ(t);
            if (!t.trim()) setRecall(null);
          }}
          placeholder={macConnected ? "Search memories · ask your Brain…" : "Search your memories…"}
          placeholderTextColor={colors.textSecondary}
          style={s.searchInput}
          returnKeyType="search"
          onSubmitEditing={doRecall}
          autoCorrect={false}
        />
        {macConnected ? (
          <Tappable onPress={doRecall} style={s.searchBtn}>
            <Text style={[typography.body, { color: colors.background, fontWeight: "700" }]}>
              {asking ? "…" : "↳"}
            </Text>
          </Tappable>
        ) : null}
      </View>

      {recall ? (
        <Card>
          <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: space.xs }]}>
            From your Brain{recall.tier ? ` · ${recall.tier}` : ""}
          </Text>
          <Text style={[typography.body, { color: colors.textPrimary }]}>{recall.text}</Text>
          {recall.sources.length ? (
            <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm }]}>
              {recall.sources.slice(0, 4).join(" · ")}
            </Text>
          ) : null}
        </Card>
      ) : null}

      {groups.length === 0 ? (
        query ? (
          <EmptyState
            title={`Nothing kept matches “${q.trim()}”`}
            hint={macConnected ? "Tap ↳ to ask your Brain to search your files and mail." : "Connect your Mac mini to search your files and mail too."}
          />
        ) : (
          <EmptyState title="No memories yet" hint="Put on your Halo and live — the moments that matter get kept here, never raw recordings." />
        )
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
  searchRow: { flexDirection: "row", gap: space.sm, marginBottom: space.md },
  searchInput: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.pill,
    color: colors.textPrimary,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    fontSize: 15,
  },
  searchBtn: {
    backgroundColor: colors.accentMemory,
    borderRadius: radius.pill,
    width: 48,
    alignItems: "center",
    justifyContent: "center",
  },
});
