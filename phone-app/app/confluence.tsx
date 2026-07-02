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
import { View, Text, SafeAreaView, TouchableOpacity, TextInput, StyleSheet } from "react-native";
import { colors }     from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";

type BondState = "none" | "proposed" | "live";

const DEMO_CODE = "rune-birch";

export default function Confluence() {
  const [bond, setBond] = useState<BondState>("none");
  const [codeEntry, setCodeEntry] = useState("");
  const [togetherness, setTogetherness] = useState(0.82);
  const [lastPing, setLastPing] = useState<string | null>(null);

  const merged = togetherness >= 0.72;

  return (
    <SafeAreaView style={s.safe}>
      <View style={s.header}>
        <Text style={[typography.title, { color: colors.textPrimary }]}>Confluence</Text>
        <View style={[s.bondPill, bond === "live" && { borderColor: colors.accentMemory }]}>
          <View style={[s.dot, { backgroundColor:
            bond === "live" ? colors.accentSuccess :
            bond === "proposed" ? colors.accentAttention : colors.statusPaused }]} />
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {bond === "live" ? "bonded" : bond === "proposed" ? "waiting" : "solo"}
          </Text>
        </View>
      </View>

      {bond !== "live" && (
        <View style={s.card}>
          <Text style={[typography.eyebrow, s.eyebrow]}>Bond</Text>
          {bond === "none" && (
            <>
              <Text style={[typography.body, { color: colors.textSecondary }]}>
                A bond is explicit, mutual, and expires by morning. Only weather crosses it — never words, places, or names.
              </Text>
              <TouchableOpacity style={s.primary} onPress={() => setBond("proposed")}>
                <Text style={[typography.body, { color: colors.background, fontWeight: "600" }]}>Propose a bond</Text>
              </TouchableOpacity>
              <View style={s.acceptRow}>
                <TextInput
                  style={[s.codeInput, typography.mono]}
                  placeholder="their code…"
                  placeholderTextColor={colors.statusPaused}
                  value={codeEntry}
                  onChangeText={setCodeEntry}
                />
                <TouchableOpacity
                  style={[s.secondary, !codeEntry && { opacity: 0.4 }]}
                  disabled={!codeEntry}
                  onPress={() => setBond("live")}
                >
                  <Text style={[typography.caption, { color: colors.accentMemory }]}>Accept</Text>
                </TouchableOpacity>
              </View>
            </>
          )}
          {bond === "proposed" && (
            <>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                Say this code to them — the bond lives when they accept:
              </Text>
              <Text style={[typography.headline, s.code]}>{DEMO_CODE}</Text>
              <TouchableOpacity style={s.secondary} onPress={() => setBond("live")}>
                <Text style={[typography.caption, { color: colors.accentMemory }]}>They accepted — confirm</Text>
              </TouchableOpacity>
            </>
          )}
        </View>
      )}

      {bond === "live" && (
        <>
          <View style={s.card}>
            <Text style={[typography.eyebrow, s.eyebrow]}>One sky</Text>
            <View style={s.skyRow}>
              <View style={[s.skyHalf, { backgroundColor: colors.accentMemory,
                opacity: 0.25 + 0.5 * togetherness }]} />
              {!merged && <View style={s.seam} />}
              <View style={[s.skyHalf, { backgroundColor: merged ? colors.accentMemory : colors.accentAttention,
                opacity: 0.25 + 0.5 * togetherness }]} />
            </View>
            <Text style={[typography.body, { color: colors.textPrimary, textAlign: "center" }]}>
              {merged ? "one front" : "the sky is split"}
            </Text>
            <Text style={[typography.caption, { color: colors.textSecondary, textAlign: "center" }]}>
              togetherness {(togetherness * 100).toFixed(0)}%
            </Text>
            <View style={s.simRow}>
              <TouchableOpacity onPress={() => setTogetherness(Math.max(0.1, togetherness - 0.15))}>
                <Text style={[typography.caption, { color: colors.statusPaused }]}>drift</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => setTogetherness(Math.min(0.98, togetherness + 0.15))}>
                <Text style={[typography.caption, { color: colors.accentMemory }]}>settle</Text>
              </TouchableOpacity>
            </View>
          </View>

          <View style={s.card}>
            <Text style={[typography.eyebrow, s.eyebrow]}>The string</Text>
            <View style={s.pingRow}>
              {[["·", "here"], ["· ·", "look up"], ["· · ·", "let's go"]].map(([glyph, label]) => (
                <TouchableOpacity key={label} style={s.pingBtn}
                  onPress={() => setLastPing(label)}>
                  <Text style={[typography.title, { color: colors.accentMemory }]}>{glyph}</Text>
                  <Text style={[typography.caption, { color: colors.textSecondary }]}>{label}</Text>
                </TouchableOpacity>
              ))}
            </View>
            {lastPing && (
              <Text style={[typography.caption, { color: colors.accentSuccess, textAlign: "center" }]}>
                ping sent — light on their rim, not a word said
              </Text>
            )}
            <TouchableOpacity style={s.secondary} onPress={() => setLastPing("gift")}>
              <Text style={[typography.caption, { color: colors.accentMemory }]}>
                Send a Weather Gift — this morning, 8:00
              </Text>
            </TouchableOpacity>
          </View>

          <TouchableOpacity style={s.dissolve} onPress={() => { setBond("none"); setLastPing(null); }}>
            <Text style={[typography.caption, { color: colors.accentError }]}>Dissolve the bond</Text>
          </TouchableOpacity>
        </>
      )}

      <Text style={[typography.caption, s.footer]}>
        veiled means silent: while privacy is paused, nothing of you crosses the bond
      </Text>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe:     { flex: 1, backgroundColor: colors.background },
  header:   { flexDirection: "row", justifyContent: "space-between", alignItems: "center",
              paddingHorizontal: 24, paddingTop: 24, paddingBottom: 12 },
  bondPill: { flexDirection: "row", alignItems: "center", gap: 8, borderRadius: 999,
              borderWidth: 1, borderColor: colors.borderSubtle,
              paddingVertical: 8, paddingHorizontal: 16 },
  dot:      { width: 8, height: 8, borderRadius: 4 },
  card:     { backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1,
              borderColor: colors.borderSubtle, padding: 16,
              marginHorizontal: 24, marginTop: 14, gap: 10 },
  eyebrow:  { color: colors.textSecondary },
  primary:  { backgroundColor: colors.accentMemory, borderRadius: 999,
              paddingVertical: 12, alignItems: "center" },
  secondary:{ borderWidth: 1, borderColor: colors.borderSubtle, borderRadius: 999,
              paddingVertical: 10, alignItems: "center" },
  acceptRow:{ flexDirection: "row", gap: 10, alignItems: "center" },
  codeInput:{ flex: 1, color: colors.textPrimary, borderWidth: 1,
              borderColor: colors.borderSubtle, borderRadius: 10,
              paddingHorizontal: 12, paddingVertical: 8 },
  code:     { color: colors.accentMemory, textAlign: "center", letterSpacing: 2 },
  skyRow:   { flexDirection: "row", height: 46, borderRadius: 10, overflow: "hidden",
              alignItems: "stretch" },
  skyHalf:  { flex: 1 },
  seam:     { width: 2, backgroundColor: colors.textPrimary, opacity: 0.6 },
  simRow:   { flexDirection: "row", justifyContent: "space-around", paddingTop: 4 },
  pingRow:  { flexDirection: "row", justifyContent: "space-around" },
  pingBtn:  { alignItems: "center", gap: 2, paddingVertical: 6, paddingHorizontal: 14 },
  dissolve: { alignSelf: "center", marginTop: 16, paddingVertical: 10,
              paddingHorizontal: 24 },
  footer:   { color: colors.statusPaused, textAlign: "center", marginTop: "auto",
              marginBottom: 18, paddingHorizontal: 32 },
});
