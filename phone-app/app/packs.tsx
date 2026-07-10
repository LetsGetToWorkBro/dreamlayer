import React, { useEffect } from "react";
import { View, Text, ScrollView, StyleSheet } from "react-native";

import { PACKS, usePackStore } from "../src/state/usePackStore";
import { play } from "../src/services/haptics";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card } from "../src/ui/components/Card";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { space } from "../src/ui/theme/spacing";

export default function Packs() {
  const { selectedId, select, hydrate } = usePackStore();
  useEffect(() => {
    hydrate();
  }, [hydrate]);

  return (
    <Screen>
      <ScreenHeader title="Feel" subtitle="Reskin the platform's touch — pick an earcon & haptic pack" />
      <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: space.xxxl }}>
        {PACKS.map((p) => {
          const on = p.id === selectedId;
          return (
            <Card
              key={p.id}
              active={on}
              onPress={() => {
                select(p.id);
                play("confirm"); // feel the pack you just chose
              }}
              style={{ marginBottom: space.md }}
            >
              <View style={st.row}>
                <Text style={[typography.title, { color: on ? colors.accentMemory : colors.textPrimary }]}>
                  {p.name}
                </Text>
                {on ? <Text style={{ color: colors.accentMemory }}>✓ active</Text> : null}
              </View>
              <Text style={[typography.body, { color: colors.textSecondary, marginTop: space.xs }]}>
                {p.description}
              </Text>
            </Card>
          );
        })}
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm }]}>
          Every pack passes the same sensory gate — patterns ≤400ms, the silent signal stays silent.
        </Text>
      </ScrollView>
    </Screen>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
});
