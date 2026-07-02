import React from "react";
import { View, Text, StyleSheet } from "react-native";
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
        <View style={s.ring} />
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 20 }]}>
          Nothing on the glasses right now
        </Text>
      </View>
    );
  }
  return (
    <View style={s.wrap}>
      <View style={s.card}>
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
    borderWidth: 2,
    borderColor: colors.borderSubtle,
  },
  card: {
    width: "100%",
    backgroundColor: colors.surface,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: 22,
  },
});
