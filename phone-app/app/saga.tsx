import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { useBrainStore, SagaSnapshot, SagaAchievement } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";

const CATEGORY: { key: SagaAchievement["category"]; label: string; tint: string }[] = [
  { key: "milestone", label: "Milestones", tint: colors.accentMemory },
  { key: "quest", label: "Quests", tint: colors.accentAttention },
  { key: "explore", label: "Explore the ecosystem", tint: colors.accentSuccess },
];

export default function Saga() {
  const macConnected = useBrainStore((s) => s.macMini.connected);
  const getSaga = useBrainStore((s) => s.getSaga);
  const [saga, setSaga] = React.useState<SagaSnapshot | null>(null);
  const [loaded, setLoaded] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      const s = macConnected ? await getSaga() : null;
      if (alive) {
        setSaga(s);
        setLoaded(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, [macConnected, getSaga]);

  const pct = saga && saga.level_ceil > saga.level_floor
    ? Math.max(0, Math.min(1, (saga.xp - saga.level_floor) / (saga.level_ceil - saga.level_floor)))
    : 1;

  return (
    <Screen>
      <ScreenHeader
        title="Saga"
        eyebrow="Your journey"
        subtitle={saga ? `${saga.unlocked_count} of ${saga.total_count} unlocked` : undefined}
      />

      {!macConnected ? (
        <EmptyState title="Connect your Mac mini" hint="Saga — your ranks, level, and badges — lives on your Brain." />
      ) : !loaded ? (
        <EmptyState title="Loading your Saga…" hint="Gathering your journey." />
      ) : !saga ? (
        <EmptyState title="Couldn’t reach your Brain" hint="Is the Mac mini awake and reachable?" />
      ) : (
        <>
          {/* rank + level + XP bar */}
          <Card>
            <View style={s.rankRow}>
              <View>
                <Text style={[typography.eyebrow, { color: colors.accentMemory }]}>{`Rank ${saga.level}`}</Text>
                <Text style={[typography.display, { color: colors.textPrimary }]}>{saga.rank}</Text>
              </View>
              <View style={{ alignItems: "flex-end" }}>
                <Text style={[typography.caption, { color: colors.textSecondary }]}>
                  Level {saga.level} / {saga.max_level}
                </Text>
              </View>
            </View>
            <View style={s.barTrack}>
              <View style={[s.barFill, { width: `${pct * 100}%` }]} />
            </View>
            <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.xs }]}>
              {saga.level >= saga.max_level
                ? "The summit — Architect of Memory."
                : saga.next_rank
                ? `${saga.xp_to_next} XP to level ${saga.level + 1} · next rank: ${saga.next_rank.title} at ${saga.next_rank.level}`
                : `${saga.xp_to_next} XP to level ${saga.level + 1}`}
            </Text>
          </Card>

          {/* badges by category */}
          {CATEGORY.map(({ key, label, tint }, ci) => {
            const items = saga.achievements.filter((a) => a.category === key);
            if (!items.length) return null;
            const got = items.filter((a) => a.unlocked).length;
            return (
              <View key={key}>
                <Section label={`${label} · ${got}/${items.length}`} first={ci === 0} accent={tint} />
                {items.map((a, i) => (
                  <Card key={a.id} delay={ci * 40 + i * 30}>
                    <View style={s.row}>
                      <View style={[s.badge, { borderColor: a.unlocked ? tint : colors.borderSubtle }]}>
                        <Text style={{ fontSize: 18, opacity: a.unlocked ? 1 : 0.4 }}>
                          {a.unlocked ? "★" : "☆"}
                        </Text>
                      </View>
                      <View style={{ flex: 1 }}>
                        <View style={s.nameRow}>
                          <Text style={[typography.body, { color: a.unlocked ? colors.textPrimary : colors.textSecondary, fontWeight: "600" }]}>
                            {a.name}
                          </Text>
                          {a.unlocked ? (
                            <Text style={[typography.caption, { color: tint }]}>unlocked</Text>
                          ) : a.target > 1 ? (
                            <Text style={[typography.caption, { color: colors.textSecondary }]}>{a.progress}/{a.target}</Text>
                          ) : null}
                        </View>
                        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>{a.what}</Text>
                        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2, fontStyle: "italic", opacity: 0.8 }]}>
                          {a.how}
                        </Text>
                        {!a.unlocked && a.target > 1 ? (
                          <View style={s.miniTrack}>
                            <View style={[s.miniFill, { width: `${Math.min(1, a.progress / a.target) * 100}%`, backgroundColor: tint }]} />
                          </View>
                        ) : null}
                      </View>
                    </View>
                  </Card>
                ))}
              </View>
            );
          })}
        </>
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  rankRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end", marginBottom: space.md },
  barTrack: { height: 8, borderRadius: radius.pill, backgroundColor: colors.borderSubtle, overflow: "hidden" },
  barFill: { height: "100%", borderRadius: radius.pill, backgroundColor: colors.accentMemory },
  row: { flexDirection: "row", gap: space.md, alignItems: "flex-start" },
  badge: { width: 40, height: 40, borderRadius: 20, borderWidth: 1.5, alignItems: "center", justifyContent: "center" },
  nameRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  miniTrack: { height: 4, borderRadius: radius.pill, backgroundColor: colors.borderSubtle, overflow: "hidden", marginTop: 6 },
  miniFill: { height: "100%", borderRadius: radius.pill },
});
