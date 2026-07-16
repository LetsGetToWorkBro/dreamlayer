/**
 * Confluence — two wearers, one entangled sky.
 *
 * Three moments on one screen:
 *   Bond        — propose (show the code) / accept (enter the code);
 *                 the bond is live only after both sides act, and it
 *                 dissolves from either side in one tap.
 *   The sky     — a togetherness dial mirroring the entangled state:
 *                 merged (one front) or split (a seam, widening).
 *   The string  — TinCan quick pings and a Weather Gift picker.
 *
 * Shapes mirror host-python confluence/* (BondManager / EntangledSky /
 * TinCan / gift). This screen is presentational until the phone bridge
 * streams live bond state, same discipline as rehearsal.tsx.
 */
import React, { useState } from "react";
import { View, Text, TextInput, StyleSheet } from "react-native";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card } from "../src/ui/components/Card";
import { Tappable } from "../src/ui/components/Tappable";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";

type BondState = "none" | "proposed" | "live";

const DEMO_CODE = "rune-birch";

export default function Confluence() {
  const [bond, setBond] = useState<BondState>("none");
  const [codeEntry, setCodeEntry] = useState("");
  const [togetherness, setTogetherness] = useState(0.82);
  const [lastPing, setLastPing] = useState<string | null>(null);

  const merged = togetherness >= 0.72;

  const bondPill = (
    <View style={[s.bondPill, bond === "live" && { borderColor: colors.accentMemory }]}>
      <View
        style={[
          s.dot,
          {
            backgroundColor:
              bond === "live" ? colors.accentSuccess : bond === "proposed" ? colors.accentAttention : colors.statusPaused,
          },
        ]}
      />
      <Text style={[typography.caption, { color: colors.textSecondary }]}>
        {bond === "live" ? "bonded" : bond === "proposed" ? "waiting" : "solo"}
      </Text>
    </View>
  );

  return (
    <Screen>
      <ScreenHeader title="Confluence" eyebrow="Together" right={bondPill} />

      {bond === "none" && (
        <Card animate>
          <Text style={[typography.eyebrow, s.eyebrow]}>Bond</Text>
          <Text style={[typography.body, { color: colors.textSecondary, marginTop: space.sm }]}>
            A bond is explicit, mutual, and expires by morning. Only weather crosses it — never words, places, or names.
          </Text>
          <Tappable style={s.primary} onPress={() => setBond("proposed")}>
            <Text style={[typography.body, { color: "#FFFFFF", fontWeight: "700" }]}>Propose a bond</Text>
          </Tappable>
          <View style={s.acceptRow}>
            <TextInput
              style={[s.codeInput, typography.mono]}
              placeholder="their code…"
              placeholderTextColor={colors.statusPaused}
              autoCapitalize="none"
              value={codeEntry}
              onChangeText={setCodeEntry}
            />
            <Tappable style={[s.secondary, !codeEntry && { opacity: 0.4 }]} disabled={!codeEntry} onPress={() => setBond("live")}>
              <Text style={[typography.caption, { color: colors.accentMemory }]}>Accept</Text>
            </Tappable>
          </View>
        </Card>
      )}

      {bond === "proposed" && (
        <Card animate>
          <Text style={[typography.eyebrow, s.eyebrow]}>Bond</Text>
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm }]}>
            Say this code to them — the bond lives when they accept:
          </Text>
          <Text style={[typography.headline, s.code]}>{DEMO_CODE}</Text>
          <Tappable style={s.secondary} onPress={() => setBond("live")}>
            <Text style={[typography.caption, { color: colors.accentMemory }]}>They accepted — confirm</Text>
          </Tappable>
        </Card>
      )}

      {bond === "live" && (
        <>
          <Card animate>
            <Text style={[typography.eyebrow, s.eyebrow]}>One sky</Text>
            <View style={s.skyRow}>
              <View style={[s.skyHalf, { backgroundColor: colors.accentMemory, opacity: 0.25 + 0.5 * togetherness }]} />
              {!merged && <View style={s.seam} />}
              <View
                style={[
                  s.skyHalf,
                  { backgroundColor: merged ? colors.accentMemory : colors.accentAttention, opacity: 0.25 + 0.5 * togetherness },
                ]}
              />
            </View>
            <Text style={[typography.body, { color: colors.textPrimary, textAlign: "center", marginTop: space.md }]}>
              {merged ? "one front" : "the sky is split"}
            </Text>
            <Text style={[typography.caption, { color: colors.textSecondary, textAlign: "center" }]}>
              togetherness {(togetherness * 100).toFixed(0)}%
            </Text>
            <View style={s.simRow}>
              <Tappable onPress={() => setTogetherness(Math.max(0.1, togetherness - 0.15))}>
                <Text style={[typography.caption, { color: colors.statusPaused }]}>drift</Text>
              </Tappable>
              <Tappable onPress={() => setTogetherness(Math.min(0.98, togetherness + 0.15))}>
                <Text style={[typography.caption, { color: colors.accentMemory }]}>settle</Text>
              </Tappable>
            </View>
          </Card>

          <Card animate delay={60}>
            <Text style={[typography.eyebrow, s.eyebrow]}>The string</Text>
            <View style={s.pingRow}>
              {([["·", "here"], ["· ·", "look up"], ["· · ·", "let's go"]] as const).map(([glyph, label]) => (
                <Tappable key={label} style={s.pingBtn} onPress={() => setLastPing(label)}>
                  <Text style={[typography.title, { color: colors.accentMemory }]}>{glyph}</Text>
                  <Text style={[typography.caption, { color: colors.textSecondary }]}>{label}</Text>
                </Tappable>
              ))}
            </View>
            {lastPing && (
              <Text style={[typography.caption, { color: colors.accentSuccess, textAlign: "center" }]}>
                ping sent — light on their rim, not a word said
              </Text>
            )}
            <Tappable style={s.secondary} onPress={() => setLastPing("gift")}>
              <Text style={[typography.caption, { color: colors.accentMemory }]}>Send a Weather Gift — this morning, 8:00</Text>
            </Tappable>
          </Card>

          <Tappable style={s.dissolve} onPress={() => { setBond("none"); setLastPing(null); }}>
            <Text style={[typography.caption, { color: colors.accentError }]}>Dissolve the bond</Text>
          </Tappable>
        </>
      )}

      <Text style={[typography.caption, s.footer]}>
        veiled means silent: while privacy is paused, nothing of you crosses the bond
      </Text>
    </Screen>
  );
}

const s = StyleSheet.create({
  bondPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    paddingVertical: space.sm,
    paddingHorizontal: space.lg,
  },
  dot: { width: 8, height: 8, borderRadius: 4 },
  eyebrow: { color: colors.textSecondary },
  primary: { backgroundColor: colors.accentMemory, borderRadius: radius.pill, paddingVertical: space.md, alignItems: "center", marginTop: space.md },
  secondary: { borderWidth: 1, borderColor: colors.borderSubtle, borderRadius: radius.pill, paddingVertical: space.md, alignItems: "center", marginTop: space.md },
  acceptRow: { flexDirection: "row", gap: space.md, alignItems: "center", marginTop: space.md },
  codeInput: {
    flex: 1,
    color: colors.textPrimary,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.sm,
    paddingHorizontal: space.md,
    paddingVertical: space.md,
  },
  code: { color: colors.accentMemory, textAlign: "center", letterSpacing: 2, marginTop: space.md },
  skyRow: { flexDirection: "row", height: 46, borderRadius: radius.sm, overflow: "hidden", alignItems: "stretch", marginTop: space.sm },
  skyHalf: { flex: 1 },
  seam: { width: 2, backgroundColor: colors.textPrimary, opacity: 0.6 },
  simRow: { flexDirection: "row", justifyContent: "space-around", paddingTop: space.sm },
  pingRow: { flexDirection: "row", justifyContent: "space-around", marginTop: space.sm },
  pingBtn: { alignItems: "center", gap: 2, paddingVertical: space.sm, paddingHorizontal: space.lg },
  dissolve: { alignSelf: "center", marginTop: space.lg, paddingVertical: space.md, paddingHorizontal: space.xxl },
  footer: { color: colors.statusPaused, textAlign: "center", marginTop: space.xxl, marginBottom: space.lg, paddingHorizontal: space.xxxl },
});
