/**
 * Rehearsal — the Reality Compiler v2 surface (live).
 *
 * You don't describe a behavior — you perform it. Tap the stage (tap ●,
 * double ●●, hold ◉) and speak beats ("rolling — three minutes", "last ten
 * seconds, pulse"). Speaking uses your keyboard's own dictation, so the mic is
 * real; each beat is sent to the Brain, which infers a Figment, proves it's
 * bounded, and hands back the live Score, the folded run-through you watch, or
 * a teach card when a beat can't be staged.
 *
 * The inference, budget proof, signing, and hot-swap all run on the Brain
 * (host-python reality_compiler/v2). This screen mirrors that state over the
 * local bridge via useRehearsalStore — it never re-implements the machine.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, TextInput } from "react-native";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { Tappable } from "../src/ui/components/Tappable";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";
import { useBrainStore } from "../src/state/useBrainStore";
import { useRehearsalStore, BeatKind } from "../src/state/useRehearsalStore";

const BEAT_GLYPH: Record<BeatKind, string> = {
  tap: "●",
  double_tap: "●●",
  long_press: "◉",
  say: "◆",
  dwell: "…",
};

function fmtFold(sec: number): string {
  return `⋯${Math.floor(sec / 60)}:${String(Math.round(sec % 60)).padStart(2, "0")}⋯`;
}

export default function Rehearsal() {
  const macConnected = useBrainStore((s) => s.macMini.connected || s.demoMode);

  const onStage = useRehearsalStore((s) => s.onStage);
  const score = useRehearsalStore((s) => s.score);
  const proof = useRehearsalStore((s) => s.proof);
  const brief = useRehearsalStore((s) => s.brief);
  const preview = useRehearsalStore((s) => s.preview);
  const teach = useRehearsalStore((s) => s.teach);
  const figmentId = useRehearsalStore((s) => s.figmentId);
  const busy = useRehearsalStore((s) => s.busy);
  const beats = useRehearsalStore((s) => s.beats);
  const repertoire = useRehearsalStore((s) => s.repertoire);
  const paired = useRehearsalStore((s) => s.paired);

  const start = useRehearsalStore((s) => s.start);
  const addBeat = useRehearsalStore((s) => s.addBeat);
  const removeLastBeat = useRehearsalStore((s) => s.removeLastBeat);
  const clearStage = useRehearsalStore((s) => s.clearStage);
  const keep = useRehearsalStore((s) => s.keep);
  const refresh = useRehearsalStore((s) => s.refresh);
  const arm = useRehearsalStore((s) => s.arm);
  const revoke = useRehearsalStore((s) => s.revoke);

  const [utterance, setUtterance] = useState("");

  useEffect(() => {
    refresh();
  }, [macConnected, refresh]);

  const say = () => {
    const t = utterance.trim();
    if (!t) return;
    setUtterance("");
    addBeat({ kind: "say", text: t });
  };

  const recordPill = (
    <Tappable
      onPress={() => (onStage ? clearStage() : start("Rehearsed behavior"))}
      style={[s.recordPill, onStage && { borderColor: colors.accentAttention }]}
    >
      <View style={[s.recordDot, { backgroundColor: onStage ? colors.accentAttention : colors.textSecondary }]} />
      <Text style={[typography.caption, { color: onStage ? colors.accentAttention : colors.textSecondary }]}>
        {onStage ? "on stage" : "rehearse"}
      </Text>
    </Tappable>
  );

  return (
    <Screen>
      <ScreenHeader title="Rehearsal" eyebrow="Reality Compiler" right={recordPill} />

      {!macConnected && (
        <Card>
          <Text style={[typography.body, { color: colors.textPrimary }]}>Connect your Brain to rehearse.</Text>
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.xs }]}>
            Performances are inferred, proved, and signed on your paired Mac — the phone is the stage, the
            Brain is the compiler.
          </Text>
        </Card>
      )}

      {onStage ? (
        <>
          {/* the stage: perform beats */}
          <Section label="Perform" first accent={colors.accentMemory} />
          <Card>
            <View style={s.beatRow}>
              <BeatButton glyph="●" label="Tap" onPress={() => addBeat({ kind: "tap" })} disabled={busy || !macConnected} />
              <BeatButton glyph="●●" label="Double" onPress={() => addBeat({ kind: "double_tap" })} disabled={busy || !macConnected} />
              <BeatButton glyph="◉" label="Hold" onPress={() => addBeat({ kind: "long_press" })} disabled={busy || !macConnected} />
            </View>
            <View style={s.sayRow}>
              <TextInput
                style={s.sayInput}
                placeholder="Say a beat…  “rolling — three minutes”"
                placeholderTextColor={colors.statusPaused}
                value={utterance}
                onChangeText={setUtterance}
                onSubmitEditing={say}
                returnKeyType="send"
                autoCapitalize="none"
                editable={!!macConnected}
              />
              <Tappable style={[s.sayBtn, (!utterance.trim() || busy) && { opacity: 0.4 }]} onPress={say} disabled={!utterance.trim() || busy}>
                <Text style={[typography.body, { color: "#00201C", fontWeight: "700" }]}>Say</Text>
              </Tappable>
            </View>
            <Text style={[typography.caption, s.micHint]}>🎙 tap the mic on your keyboard to speak the beat</Text>
          </Card>

          {/* the live score */}
          {score.length > 0 && (
            <Card>
              <View style={s.timeline}>
                {score.map((b, i) => (
                  <React.Fragment key={i}>
                    {i > 0 && <View style={s.timelineRule} />}
                    <View style={s.beat}>
                      <Text style={[typography.title, { color: b.kind === "say" ? colors.accentMemory : colors.textPrimary }]}>
                        {BEAT_GLYPH[b.kind]}
                      </Text>
                      {b.foldedSec != null && (
                        <Text style={[typography.caption, { color: colors.textSecondary }]}>{fmtFold(b.foldedSec)}</Text>
                      )}
                    </View>
                  </React.Fragment>
                ))}
              </View>
              {score.map((b, i) => {
                const flagged = teach?.beat === i;
                return (
                  <View key={i} style={[s.readingRow, flagged && { backgroundColor: "rgba(224,107,82,0.10)" }]}>
                    <Text style={[typography.caption, { color: colors.textSecondary, width: 22 }]}>{i + 1}</Text>
                    <View style={{ flex: 1 }}>
                      {b.text ? <Text style={[typography.body, { color: colors.textPrimary }]}>“{b.text}”</Text> : null}
                      <Text style={[typography.caption, { color: flagged ? colors.accentAttention : colors.accentMemory }]}>{b.reading}</Text>
                    </View>
                  </View>
                );
              })}
              <View style={s.stageActions}>
                <Tappable onPress={removeLastBeat} disabled={!beats.length || busy} style={s.ghostPill}>
                  <Text style={[typography.caption, { color: beats.length ? colors.textPrimary : colors.statusPaused }]}>Undo beat</Text>
                </Tappable>
                <Tappable
                  onPress={keep}
                  disabled={!figmentId || busy}
                  style={[s.keepPill, !figmentId && { backgroundColor: "transparent", borderColor: colors.borderSubtle }]}
                >
                  <Text style={[typography.body, { color: figmentId ? "#00201C" : colors.statusPaused, fontWeight: "700" }]}>Keep</Text>
                </Tappable>
              </View>
            </Card>
          )}

          {/* teach card — a beat that couldn't be staged */}
          {teach && (
            <Card>
              <Text style={[typography.eyebrow, { color: colors.accentAttention }]}>{teach.title}</Text>
              {teach.lines.map((ln, i) => (
                <Text key={i} style={[typography.body, { color: colors.textPrimary, marginTop: i ? 2 : space.xs }]}>{ln}</Text>
              ))}
              {teach.suggestion ? (
                <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm }]}>{teach.suggestion}</Text>
              ) : null}
            </Card>
          )}

          {/* the proof + folded run-through you watch before keeping */}
          {proof && (
            <Card>
              <View style={s.proofRow}>
                <Text style={[typography.caption, { color: colors.accentSuccess }]}>✓ proved</Text>
                <Text style={[typography.caption, { color: colors.textSecondary }]}>
                  {proof.scenes} {proof.scenes === 1 ? "scene" : "scenes"} · ≤{proof.display_hz}Hz · ≤{proof.emit_per_sec}/s
                </Text>
                {brief ? (
                  <Text style={[typography.caption, { color: colors.textSecondary }]}>{brief.trigger} · {brief.length}</Text>
                ) : null}
              </View>
              {preview.length > 0 && (
                <View style={{ marginTop: space.sm }}>
                  {preview.map((r, i) => (
                    <View key={i} style={s.previewRow}>
                      <Text style={[s.previewT, { color: r.pulse ? colors.accentAttention : colors.statusPaused }]}>
                        {r.folded ? "⋯" : r.pulse ? "●" : " "} {r.t.toFixed(0)}s
                      </Text>
                      <Text style={[typography.caption, { color: colors.textPrimary, flex: 1 }]} numberOfLines={1}>{r.text}</Text>
                    </View>
                  ))}
                </View>
              )}
              <Text style={[typography.caption, s.hint]}>you watch what you authored — before it deploys</Text>
            </Card>
          )}
        </>
      ) : (
        <Card>
          <Text style={[typography.body, { color: colors.textPrimary }]}>Make a behavior of your own.</Text>
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.xs }]}>
            This is the studio for things you invent — a custom drill, a counter, a two-phase routine. You
            perform it once (tap the stage, speak the beats) and the glasses learn it and run it forever.
          </Text>
          <View style={s.junoNote}>
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              <Text style={{ color: colors.accentMemory }}>Just need a timer or a clock?</Text> Don’t rehearse —
              ask Juno: <Text style={{ color: colors.textPrimary }}>“set a timer for 5 minutes,”</Text>{" "}
              <Text style={{ color: colors.textPrimary }}>“interval timer, 30 on, 15 off, 8 rounds,”</Text>{" "}
              <Text style={{ color: colors.textPrimary }}>“what time is it.”</Text> Juno builds those for you.
            </Text>
          </View>
        </Card>
      )}

      {/* the repertoire — kept figments, live from the Brain */}
      <Section label="Repertoire" accent={colors.textSecondary} />
      {repertoire.length === 0 ? (
        <Text style={[typography.caption, s.hint]}>
          {paired ? "nothing kept yet — rehearse something and keep it" : "connect your Brain to see your Repertoire"}
        </Text>
      ) : (
        repertoire.map((f, i) => (
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
        ))
      )}
      <Text style={[typography.caption, s.hint]}>figments are signed on this phone and never leave it unless you export them</Text>
    </Screen>
  );
}

function BeatButton({ glyph, label, onPress, disabled }: { glyph: string; label: string; onPress: () => void; disabled?: boolean }) {
  return (
    <Tappable style={[s.beatBtn, disabled && { opacity: 0.4 }]} onPress={onPress} disabled={disabled}>
      <Text style={[typography.title, { color: colors.textPrimary }]}>{glyph}</Text>
      <Text style={[typography.caption, { color: colors.textSecondary }]}>{label}</Text>
    </Tappable>
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
  junoNote: {
    marginTop: space.md,
    paddingTop: space.md,
    borderTopWidth: 1,
    borderTopColor: colors.borderSubtle,
  },
  beatRow: { flexDirection: "row", gap: space.sm },
  beatBtn: {
    flex: 1,
    alignItems: "center",
    gap: 2,
    paddingVertical: space.md,
    borderRadius: radius.lg ?? 14,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    backgroundColor: colors.surface,
  },
  sayRow: { flexDirection: "row", gap: space.sm, marginTop: space.md, alignItems: "center" },
  sayInput: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.pill,
    color: colors.textPrimary,
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
  },
  sayBtn: {
    backgroundColor: colors.accentMemory,
    borderRadius: radius.pill,
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
  },
  micHint: { color: colors.statusPaused, marginTop: space.sm, textAlign: "center" },
  timeline: { flexDirection: "row", alignItems: "center", marginBottom: space.md },
  timelineRule: { flex: 1, height: 1, backgroundColor: colors.borderSubtle, marginHorizontal: space.sm },
  beat: { alignItems: "center" },
  readingRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    paddingVertical: space.sm,
    paddingHorizontal: space.xs,
    borderTopWidth: 1,
    borderTopColor: colors.borderSubtle,
    borderRadius: 6,
  },
  stageActions: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: space.md },
  ghostPill: {
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    paddingVertical: space.sm,
    paddingHorizontal: space.lg,
  },
  keepPill: {
    backgroundColor: colors.accentMemory,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.accentMemory,
    paddingVertical: space.sm,
    paddingHorizontal: space.xl,
  },
  proofRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space.md },
  previewRow: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingVertical: 2 },
  previewT: { fontFamily: "monospace", fontSize: 12, width: 56 },
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
