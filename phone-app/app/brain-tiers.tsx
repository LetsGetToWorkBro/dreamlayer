import React, { useEffect } from "react";
import { View, Text, ScrollView, StyleSheet, Switch } from "react-native";

import { useBrainTiersStore, BrainTier } from "../src/state/useBrainTiersStore";
import { useBrainStore } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { space } from "../src/ui/theme/spacing";

function latencyLabel(t: BrainTier): string {
  if (!t.enabled) return "off";
  if (t.latency_ms == null) return t.seen ? "—" : "not used yet";
  return `${Math.round(t.latency_ms)} ms`;
}

function TierRow({ tier, active }: { tier: BrainTier; active: boolean }) {
  const on = tier.enabled;
  const accent = active ? colors.accentMemory : colors.textSecondary;
  return (
    <Card active={active} style={{ marginBottom: space.sm, opacity: on ? 1 : 0.5 }}>
      <View style={st.row}>
        <View style={{ flex: 1, paddingRight: 12 }}>
          <View style={st.titleRow}>
            <Text style={[typography.title, { color: on ? colors.textPrimary : colors.textSecondary }]}>
              {tier.name}
            </Text>
            {active ? (
              <Text style={[typography.caption, { color: colors.accentMemory }]}>answers first</Text>
            ) : null}
          </View>
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>{tier.note}</Text>
          {tier.failed > 0 ? (
            <Text style={[typography.caption, { color: colors.accentAttention, marginTop: 2 }]}>
              {tier.answered}/{tier.answered + tier.failed} answered
            </Text>
          ) : null}
        </View>
        <Text style={[typography.title, { color: accent, fontVariant: ["tabular-nums"] }]}>
          {latencyLabel(tier)}
        </Text>
      </View>
    </Card>
  );
}

export default function BrainTiers() {
  const { model, cloud_provider, incognito, active_tier, tiers, loaded, connected, load } =
    useBrainTiersStore();
  const cloud = useBrainStore((s) => s.cloud);
  const setCloud = useBrainStore((s) => s.setCloud);
  const setIncognito = useBrainStore((s) => s.setIncognito);
  const phoneIncognito = useBrainStore((s) => s.incognito);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Screen>
      <ScreenHeader title="Brain" subtitle="Your intelligence is a cartridge — swap it, and nothing on the glasses blinks" />
      <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: space.xxxl }}>
        {/* the loaded cartridge */}
        <Card accent={colors.accentMemory} active style={{ marginBottom: space.lg }}>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>Loaded model</Text>
          <Text style={[typography.display, { color: colors.textPrimary }]}>{model || "on-device"}</Text>
          {cloud_provider ? (
            <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>
              cloud vendor: {cloud_provider}
            </Text>
          ) : null}
          {!connected && loaded ? (
            <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.xs }]}>
              No Mac Brain paired — the phone is the brain. Pair one for a bigger local model over your own files.
            </Text>
          ) : null}
        </Card>

        {/* the live tier ladder, in the order the router prefers */}
        <Section label="The ladder — lowest tier that can, answers" first />
        {tiers.map((tier) => (
          <TierRow key={tier.id} tier={tier} active={tier.id === active_tier && tier.enabled} />
        ))}
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.xs, marginBottom: space.lg }]}>
          Latency is the round-trip your Brain actually measured. A dead tier is skipped, never fatal — the next one answers.
        </Text>

        {/* the swap controls */}
        <Section label="Swap" />
        <View style={st.ctrl}>
          <View style={{ flex: 1, paddingRight: 12 }}>
            <Text style={[typography.body, { color: colors.textPrimary }]}>Cloud tier</Text>
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              {cloud ? "on for the hardest, non-personal asks" : "off — nothing leaves the device"}
            </Text>
          </View>
          <Switch value={cloud} onValueChange={setCloud} />
        </View>
        <View style={st.ctrl}>
          <View style={{ flex: 1, paddingRight: 12 }}>
            <Text style={[typography.body, { color: colors.textPrimary }]}>Incognito</Text>
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              forces cloud off and pauses capture for the session
            </Text>
          </View>
          <Switch value={phoneIncognito || incognito} onValueChange={setIncognito} />
        </View>
      </ScrollView>
    </Screen>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  ctrl: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: space.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.borderSubtle,
  },
});
