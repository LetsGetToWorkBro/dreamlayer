import React, { useEffect } from "react";
import { View, Text, ScrollView, StyleSheet } from "react-native";

import { useCloudViewStore } from "../src/state/useCloudViewStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { space } from "../src/ui/theme/spacing";

function kb(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${Math.round(n / 1000)} KB`;
}

export default function Cloud() {
  const { enabled, vault, relay, listings, cannot_see, loaded, connected, load } = useCloudViewStore();
  useEffect(() => {
    load();
  }, [load]);

  const guarantees = cannot_see.length
    ? cannot_see
    : [
        "your memories — they never leave the device unencrypted",
        "who you are — the relay learns only a room id",
        "what a figment means — a dozen integers, nothing more",
      ];

  return (
    <Screen>
      <ScreenHeader title="What the cloud can see" subtitle="The byte-shapes the server holds — nothing else" />
      {loaded && !connected ? (
        <EmptyState glyph="☁" title="No Brain paired" hint="Pair your Mac Brain to see exactly what the cloud holds." />
      ) : (
        <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: space.xxxl }}>
          {!enabled ? (
            <Card accent={colors.accentSuccess} active style={{ marginBottom: space.lg }}>
              <Text style={[typography.title, { color: colors.textPrimary }]}>Cloud is off</Text>
              <Text style={[typography.body, { color: colors.textSecondary, marginTop: space.xs }]}>
                The server holds nothing about you. Everything below is what it would hold — opaque
                shapes only — if you turned Continuity on.
              </Text>
            </Card>
          ) : (
            <>
              <Section label="What it holds (opaque)" first />
              <Card style={{ marginBottom: space.md }}>
                <Text style={[typography.body, { color: colors.textPrimary }]}>
                  Vault: {vault ? `${kb(vault.bytes)} of ciphertext` : "no backup stored"}
                </Text>
                <Text style={[typography.body, { color: colors.textPrimary, marginTop: space.xs }]}>
                  Relay: {relay.rooms.length} room{relay.rooms.length === 1 ? "" : "s"}
                  {relay.rooms.length ? ` (${relay.rooms.map((r) => `${r.id.slice(0, 6)}·${r.members}`).join(", ")})` : ""}
                </Text>
                <Text style={[typography.body, { color: colors.textPrimary, marginTop: space.xs }]}>
                  Listings: {listings}
                </Text>
                <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm }]}>
                  Sizes, ids, and counts — never content. The server cannot open the ciphertext.
                </Text>
              </Card>
            </>
          )}

          <Section label="What it can never see" />
          {guarantees.map((g, i) => (
            <Card key={i} style={{ marginBottom: space.sm }} accent={colors.accentMemory}>
              <View style={st.row}>
                <Text style={[typography.title, { color: colors.accentMemory }]}>✕</Text>
                <Text style={[typography.body, { color: colors.textSecondary, flex: 1, marginLeft: space.sm }]}>{g}</Text>
              </View>
            </Card>
          ))}
        </ScrollView>
      )}
    </Screen>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-start" },
});
