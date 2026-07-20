import React, { useEffect } from "react";
import { View, Text, ScrollView, StyleSheet } from "react-native";

import { useCapabilityStore, CapItem } from "../src/state/useCapabilityStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { useTheme, makeThemedStyles } from "../src/ui/theme/useTheme";
import { typography } from "../src/ui/theme/typography";
import { space } from "../src/ui/theme/spacing";

function Impact({ n }: { n: number }) {
  const { colors } = useTheme();
  const k = Math.max(0, Math.min(5, n));
  return (
    <Text style={{ color: colors.accentMemory, letterSpacing: 2 }}>
      {"●".repeat(k)}
      <Text style={{ color: colors.textSecondary }}>{"○".repeat(5 - k)}</Text>
    </Text>
  );
}

function CapRow({ c }: { c: CapItem }) {
  const st = useSt();
  const { colors } = useTheme();
  const profile = c.profiles && c.profiles.length ? c.profiles[0] : null;
  return (
    <Card style={{ marginBottom: space.md }}>
      <Text style={[typography.title, { color: colors.textPrimary }]}>{c.title}</Text>
      <Text style={[typography.body, { color: colors.textSecondary, marginTop: space.xs }]}>{c.gain}</Text>
      <View style={st.meta}>
        <Impact n={c.impact} />
        {profile ? (
          <Text style={[typography.caption, { color: colors.textSecondary }]}>in {profile}</Text>
        ) : null}
      </View>
    </Card>
  );
}

export default function Capabilities() {
  const { colors } = useTheme();
  const { learnable, activeCount, items, loaded, connected, load } = useCapabilityStore();
  useEffect(() => {
    load();
  }, [load]);

  const canLearn = learnable();

  return (
    <Screen>
      <ScreenHeader title="Capabilities" subtitle="What your Brain can learn to do" />
      {loaded && !connected ? (
        <EmptyState
          glyph="◍"
          title="No Brain paired"
          hint="Pair your Mac Brain to see what it can learn — and switch it on there."
        />
      ) : (
        <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: space.xxxl }}>
          {items.length ? (
            <Text style={[typography.body, { color: colors.textSecondary, marginBottom: space.md }]}>
              {activeCount()} of {items.length} active
            </Text>
          ) : null}
          {canLearn.length ? (
            <>
              <Section label="Your Brain can also learn to" first />
              {canLearn.map((c) => (
                <CapRow key={c.key} c={c} />
              ))}
              <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm }]}>
                Install the matching profile on your Mac to switch these on — the phone never installs code.
              </Text>
            </>
          ) : loaded ? (
            <EmptyState glyph="◉" title="Fully equipped" hint="Every capability the Brain knows about is switched on." />
          ) : null}
        </ScrollView>
      )}
    </Screen>
  );
}

const useSt = makeThemedStyles(({ colors, platinum }) => StyleSheet.create({
  meta: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: space.sm,
  },
}));
