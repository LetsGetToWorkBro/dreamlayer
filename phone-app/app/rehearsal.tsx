/**
 * Rehearsal — the Reality Compiler v2 surface.
 *
 * Two panes:
 *   Score      — the last rehearsal as a beat timeline (taps ●, folded
 *                time ⋯3:00⋯, marks ◆) with the choreographer's plain-words
 *                reading under each beat. Tap a beat to re-perform it.
 *   Repertoire — the vault: every kept figment as a card (signed dot,
 *                trigger, length) with Arm / Revoke actions.
 *
 * The heavy lifting (inference, budgets, signing, deploy) happens in
 * host-python reality_compiler/v2; this screen mirrors its state over the
 * local bridge. Shapes below match RehearsalResult / VaultEntry.
 */
import React, { useState } from "react";
import { View, Text, StyleSheet } from "react-native";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { Tappable } from "../src/ui/components/Tappable";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";

type BeatKind = "tap" | "double_tap" | "long_press" | "say" | "dwell";
interface ScoreBeat {
  kind: BeatKind;
  reading: string;
  text?: string;
  foldedSec?: number;
}
interface Repertoire {
  id: string;
  name: string;
  trigger: string;
  length: string;
  signed: boolean;
  active: boolean;
}

const DEMO_SCORE: ScoreBeat[] = [
  { kind: "double_tap", reading: "strong beat — trigger" },
  { kind: "say", text: "rolling — three minutes", reading: "ROLLING · 3:00 folded", foldedSec: 180 },
  { kind: "say", text: "last ten seconds, pulse", reading: "pulse · final 10s" },
  { kind: "say", text: "then it starts again", reading: "loop closes" },
];
const DEMO_VAULT: Repertoire[] = [
  { id: "a1", name: "Rolling rounds", trigger: "double-tap", length: "3:00 + pulse", signed: true, active: true },
  { id: "b2", name: "Water break", trigger: "every 30 min", length: "5s card", signed: true, active: false },
];

const BEAT_GLYPH: Record<BeatKind, string> = {
  tap: "●",
  double_tap: "●●",
  long_press: "◉",
  say: "◆",
  dwell: "…",
};

export default function Rehearsal() {
  const [score] = useState<ScoreBeat[]>(DEMO_SCORE);
  const [vault, setVault] = useState<Repertoire[]>(DEMO_VAULT);
  const [rehearsing, setRehearsing] = useState(false);

  const arm = (id: string) => setVault((v) => v.map((f) => ({ ...f, active: f.id === id })));
  const revoke = (id: string) =>
    setVault((v) => v.map((f) => (f.id === id ? { ...f, active: false, signed: false } : f)));

  const recordPill = (
    <Tappable onPress={() => setRehearsing((r) => !r)} style={[s.recordPill, rehearsing && { borderColor: colors.accentAttention }]}>
      <View style={[s.recordDot, { backgroundColor: rehearsing ? colors.accentAttention : colors.textSecondary }]} />
      <Text style={[typography.caption, { color: rehearsing ? colors.accentAttention : colors.textSecondary }]}>
        {rehearsing ? "on stage" : "rehearse"}
      </Text>
    </Tappable>
  );

  return (
    <Screen>
      <ScreenHeader title="Rehearsal" eyebrow="Reality Compiler" right={recordPill} />

      <Section label="Score" first accent={colors.textSecondary} />
      <Card>
        <View style={s.timeline}>
          {score.map((b, i) => (
            <React.Fragment key={i}>
              {i > 0 && <View style={s.timelineRule} />}
              <Tappable style={s.beat} onPress={() => setRehearsing(true)}>
                <Text style={[typography.title, { color: b.kind === "say" ? colors.accentMemory : colors.textPrimary }]}>
                  {BEAT_GLYPH[b.kind]}
                </Text>
                {b.foldedSec != null && (
                  <Text style={[typography.caption, { color: colors.textSecondary }]}>
                    ⋯{Math.floor(b.foldedSec / 60)}:{String(b.foldedSec % 60).padStart(2, "0")}⋯
                  </Text>
                )}
              </Tappable>
            </React.Fragment>
          ))}
        </View>
        {score.map((b, i) => (
          <View key={i} style={s.readingRow}>
            <Text style={[typography.caption, { color: colors.textSecondary, width: 22 }]}>{i + 1}</Text>
            <View style={{ flex: 1 }}>
              {b.text && <Text style={[typography.body, { color: colors.textPrimary }]}>“{b.text}”</Text>}
              <Text style={[typography.caption, { color: colors.accentMemory }]}>{b.reading}</Text>
            </View>
            <Tappable onPress={() => setRehearsing(true)}>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>redo</Text>
            </Tappable>
          </View>
        ))}
        <Text style={[typography.caption, s.hint]}>tap a beat to re-perform just that beat</Text>
      </Card>

      <Section label="Repertoire" accent={colors.textSecondary} />
      {vault.map((f, i) => (
        <Card key={f.id} active={f.active} delay={i * 50}>
          <View style={s.figmentRow}>
            <View style={{ flex: 1 }}>
              <View style={s.figmentTitleRow}>
                <View style={[s.signedDot, { backgroundColor: f.signed ? colors.accentSuccess : colors.accentError }]} />
                <Text style={[typography.body, { color: colors.textPrimary, fontWeight: "600" }]}>{f.name}</Text>
              </View>
              <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.xs }]}>
                {f.trigger} · {f.length}
                {f.active ? "  ·  on stage" : ""}
              </Text>
            </View>
            {f.active ? (
              <Tappable onPress={() => revoke(f.id)} style={s.actionPill}>
                <Text style={[typography.caption, { color: colors.accentError }]}>Revoke</Text>
              </Tappable>
            ) : (
              <Tappable onPress={() => arm(f.id)} style={s.actionPill} disabled={!f.signed}>
                <Text style={[typography.caption, { color: f.signed ? colors.accentMemory : colors.statusPaused }]}>
                  {f.signed ? "Arm" : "Unsigned"}
                </Text>
              </Tappable>
            )}
          </View>
        </Card>
      ))}
      <Text style={[typography.caption, s.hint]}>figments are signed on this phone and never leave it unless you export them</Text>
    </Screen>
  );
}

const s = StyleSheet.create({
  recordPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    paddingVertical: space.sm,
    paddingHorizontal: space.lg,
  },
  recordDot: { width: 8, height: 8, borderRadius: 4 },
  timeline: { flexDirection: "row", alignItems: "center", marginBottom: space.md },
  timelineRule: { flex: 1, height: 1, backgroundColor: colors.borderSubtle, marginHorizontal: space.sm },
  beat: { alignItems: "center" },
  readingRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    paddingVertical: space.sm,
    borderTopWidth: 1,
    borderTopColor: colors.borderSubtle,
  },
  hint: { color: colors.statusPaused, marginTop: space.md, textAlign: "center" },
  figmentRow: { flexDirection: "row", alignItems: "center" },
  figmentTitleRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  signedDot: { width: 6, height: 6, borderRadius: 3 },
  actionPill: {
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    paddingVertical: space.sm,
    paddingHorizontal: space.md,
  },
});
