/**
 * Ember — memories you tend until they live in you (docs/EMBER.md).
 *
 * Two rituals live on this screen and nowhere else:
 *   the morning tending — keep up to 3 of yesterday's offers (or let them go)
 *   the ceremony        — burn a graduated recording, behind a two-step consent
 *
 * Deliberately absent: engram answers (the Brain never ships them — the
 * reveal card on the glasses is the only surface that renders one), scores,
 * streaks, and anything that would turn a practice into a game.
 */
import React from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import { useBrainStore } from "../src/state/useBrainStore";
import { useEmberStore, EmberEngram } from "../src/state/useEmberStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";

// hearth gold — mirrors themes.py EMBER_GLOW / palette.lua ember_glow
const EMBER = "#B4701F";     // deep ember amber, legible on the light desktop
const EMBER_DIM = "#8A5E20";
const GRADUATE_AT_DAYS = 90; // scheduler.CONSOLIDATION_THRESHOLD_DAYS

function CurveBar({ e }: { e: EmberEngram }) {
  const pct = Math.max(0.02, Math.min(1, e.stability_days / GRADUATE_AT_DAYS));
  return (
    <View style={s.barTrack}>
      <View style={[s.barFill, { width: `${pct * 100}%`, backgroundColor: e.graduated ? EMBER : EMBER_DIM }]} />
    </View>
  );
}

function dueLabel(d: number): string {
  if (d <= 0) return "glowing now — it will find you";
  if (d < 1) return "due later today";
  return `next glow in ~${Math.round(d)}d`;
}

export default function Ember() {
  const connected = useBrainStore((st) => st.macMini.connected || st.demoMode);
  const st = useEmberStore();
  const [confirmBurn, setConfirmBurn] = React.useState<number | null>(null);

  React.useEffect(() => {
    st.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected]);

  const tending = st.engrams.filter((e) => !e.graduated);

  return (
    <Screen>
      <ScreenHeader
        title="Ember"
        eyebrow="Tend your memory"
        subtitle="The glasses don't remember this for you — they teach it back into you, then burn the tape."
      />

      {!connected ? (
        <EmptyState title="Connect your Brain" hint="Ember's curves live beside your memory file — pair the Brain to tend them." />
      ) : !st.loaded ? (
        <EmptyState title="Warming the hearth…" hint="Reading your curves." />
      ) : !st.reachable ? (
        <EmptyState title="Couldn't reach your Brain" hint="Is it awake and on your network?" />
      ) : (
        <>
          {/* the morning offers */}
          <Section label={`This morning's offers · keep up to ${Math.max(0, 3 - st.keptToday)}`} first accent={EMBER} />
          {st.candidates.length === 0 ? (
            <Card>
              <Text style={[typography.body, { color: colors.textSecondary }]}>
                Nothing on offer. The night stages a handful of moments after the glasses dream — an empty morning is a perfectly good morning.
              </Text>
            </Card>
          ) : (
            st.candidates.map((c, i) => (
              <Card key={c.id} delay={i * 40}>
                <Text style={[typography.body, { color: colors.textPrimary }]}>{c.summary}</Text>
                <Text style={[typography.caption, { color: EMBER_DIM, marginTop: 4 }]}>
                  the glow will ask: “{c.cue}”
                </Text>
                <View style={s.rowButtons}>
                  <TouchableOpacity
                    style={[s.btn, { borderColor: EMBER }]}
                    onPress={() => st.tend(c.id, true)}
                    accessibilityLabel={`Keep: ${c.cue}`}
                  >
                    <Text style={[typography.body, { color: EMBER }]}>Keep</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[s.btn, { borderColor: colors.borderSubtle }]}
                    onPress={() => st.tend(c.id, false)}
                    accessibilityLabel={`Let go: ${c.cue}`}
                  >
                    <Text style={[typography.body, { color: colors.textSecondary }]}>Let it fade</Text>
                  </TouchableOpacity>
                </View>
              </Card>
            ))
          )}

          {/* the curves */}
          <Section label={`Tending · ${tending.length}`} accent={EMBER} />
          {tending.length === 0 ? (
            <Card>
              <Text style={[typography.body, { color: colors.textSecondary }]}>
                Nothing under tending yet. Keep a moment above and the glasses will glow its cue at the right place, at widening intervals.
              </Text>
            </Card>
          ) : (
            tending.map((e, i) => (
              <Card key={e.id} delay={i * 30}>
                <Text style={[typography.body, { color: colors.textPrimary, fontWeight: "600" }]}>“{e.cue}”</Text>
                <CurveBar e={e} />
                <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 4 }]}>
                  {`recalled ×${e.reps}${e.lapses ? ` · slipped ×${e.lapses}` : ""} · ${dueLabel(e.due_in_days)}${e.anchored ? " · anchored to its place" : ""}`}
                </Text>
              </Card>
            ))
          )}

          {/* the ceremony */}
          <Section label={`Lives in you · ${st.offers.length}`} accent={EMBER} />
          {st.offers.length === 0 ? (
            <Card>
              <Text style={[typography.body, { color: colors.textSecondary }]}>
                When a memory's curve crosses {GRADUATE_AT_DAYS} days of stability, it lives in you — and its recording becomes yours to burn.
              </Text>
            </Card>
          ) : (
            st.offers.map((e) => (
              <Card key={e.id}>
                <Text style={[typography.body, { color: colors.textPrimary, fontWeight: "600" }]}>“{e.cue}”</Text>
                <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 4 }]}>
                  {`kept ${e.kept_days}d · recalled ×${e.reps} — this one is yours now`}
                </Text>
                {confirmBurn === e.id ? (
                  <View style={s.rowButtons}>
                    <TouchableOpacity
                      style={[s.btn, { borderColor: colors.accentError }]}
                      onPress={async () => {
                        await st.burn(e.id, true);
                        setConfirmBurn(null);
                      }}
                      accessibilityLabel={`Confirm burn: ${e.cue}`}
                    >
                      <Text style={[typography.body, { color: colors.accentError }]}>Burn it — the cue remains, the tape does not</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={[s.btn, { borderColor: colors.borderSubtle }]} onPress={() => setConfirmBurn(null)}>
                      <Text style={[typography.body, { color: colors.textSecondary }]}>Not yet</Text>
                    </TouchableOpacity>
                  </View>
                ) : (
                  <View style={s.rowButtons}>
                    <TouchableOpacity
                      style={[s.btn, { borderColor: EMBER }]}
                      onPress={() => setConfirmBurn(e.id)}
                      accessibilityLabel={`Burn the recording: ${e.cue}`}
                    >
                      <Text style={[typography.body, { color: EMBER }]}>Burn the recording</Text>
                    </TouchableOpacity>
                  </View>
                )}
              </Card>
            ))
          )}

          {/* the honest ledger */}
          {(st.status.burned ?? 0) > 0 ? (
            <Card>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                {`${st.status.burned} recording${(st.status.burned ?? 0) === 1 ? "" : "s"} burned so far. What remains of each: its cue, and you.`}
              </Text>
            </Card>
          ) : null}
        </>
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  rowButtons: { flexDirection: "row", gap: space.sm, marginTop: space.md, flexWrap: "wrap" },
  btn: {
    borderWidth: 1.5,
    borderRadius: radius.pill,
    paddingVertical: 8,
    paddingHorizontal: 16,
  },
  barTrack: { height: 6, borderRadius: radius.pill, backgroundColor: colors.borderSubtle, overflow: "hidden", marginTop: space.sm },
  barFill: { height: "100%", borderRadius: radius.pill },
});
