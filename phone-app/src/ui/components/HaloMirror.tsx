import React from "react";
import { View, Text, StyleSheet, Platform } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import type { HaloCard } from "../../state/useMemoryStore";
import { colors } from "../theme/colors";
import { typography } from "../theme/typography";

/**
 * HaloMirror — a phone-side mirror of the card currently on the glasses.
 * When nothing is showing it rests as a calm halo ring; when a card is live
 * it renders the same primary line + supporting lines the Halo draws.
 */
export function HaloMirror({ card }: { card: HaloCard }) {
  if (!card) {
    return (
      <View style={s.wrap}>
        <View style={s.ringGlow} />
        <View style={s.ring} />
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 22 }]}>
          Nothing on the glasses right now
        </Text>
      </View>
    );
  }
  return (
    <View style={s.wrap}>
      <View style={s.card}>
        <LinearGradient
          colors={["rgba(255,255,255,0.06)", "rgba(255,255,255,0)"]}
          start={{ x: 0.1, y: 0 }}
          end={{ x: 0.5, y: 0.9 }}
          style={s.sheen}
          pointerEvents="none"
        />
        <Text style={[typography.eyebrow, { color: colors.accentMemory }]}>{card.kind}</Text>
        <Text style={[typography.headline, { color: colors.textPrimary, marginTop: 6 }]}>{card.primary}</Text>
        {(card.lines ?? []).map((line, i) => (
          <Text key={i} style={[typography.body, { color: colors.textSecondary, marginTop: 4 }]}>
            {line}
          </Text>
        ))}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { alignItems: "center", justifyContent: "center", paddingHorizontal: 24 },
  ring: {
    width: 160,
    height: 160,
    borderRadius: 80,
    borderWidth: 1.5,
    borderColor: "rgba(140, 190, 190, 0.28)",
  },
  // a soft teal bloom sitting behind the calm ring
  ringGlow: {
    position: "absolute",
    top: -10,
    width: 200,
    height: 200,
    borderRadius: 100,
    backgroundColor: colors.accentMemory,
    opacity: 0.08,
  },
  card: {
    width: "100%",
    backgroundColor: "rgba(20, 31, 35, 0.64)",
    borderRadius: 20,
    borderWidth: 1,
    borderColor: "rgba(140, 190, 190, 0.14)",
    padding: 22,
    overflow: "hidden",
    shadowColor: "#000000",
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.35,
    shadowRadius: 22,
    ...(Platform.OS === "android" ? { elevation: 6 } : null),
  },
  sheen: { position: "absolute", top: 0, left: 0, right: 0, height: "60%" },
});
