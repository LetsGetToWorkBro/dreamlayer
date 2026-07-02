import React from "react";
import { Animated, View, Text, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { useHaloStore } from "../src/state/useHaloStore";
import { useBrainStore } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { HaloMirror } from "../src/ui/components/HaloMirror";
import { StatusPill } from "../src/ui/components/StatusPill";
import { Tappable } from "../src/ui/components/Tappable";
import { useEntrance } from "../src/ui/anim";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";

export default function Now() {
  const router = useRouter();
  const { paused, connected, togglePause, connect, service } = useHaloStore();
  const brainKind = useBrainStore((s) => (s.macMini.connected ? "Mac mini" : "phone"));
  const mirror = useEntrance(60);

  return (
    <Screen scroll={false}>
      <ScreenHeader title="Now" eyebrow="DreamLayer" right={<StatusPill paused={paused} />} />

      <Animated.View style={[s.stage, mirror]}>
        <HaloMirror card={paused ? null : service.lastCard} />
        {!connected ? (
          <Tappable onPress={connect} style={s.pairChip}>
            <Text style={[typography.caption, { color: colors.accentMemory }]}>Halo not connected · tap to pair</Text>
          </Tappable>
        ) : (
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.lg }]}>
            Brain: {brainKind}{paused ? " · capture paused" : " · listening for what matters"}
          </Text>
        )}
      </Animated.View>

      <View style={s.actions}>
        <Tappable onPress={() => router.push("/brain")} style={[s.action, { backgroundColor: colors.accentMemory }]}>
          <Text style={[typography.body, { color: colors.background, fontWeight: "700" }]}>Ask your brain</Text>
        </Tappable>
        <Tappable
          onPress={togglePause}
          style={[s.action, s.actionGhost, { borderColor: paused ? colors.statusPaused : colors.borderSubtle }]}
        >
          <Text style={[typography.body, { color: paused ? colors.statusPaused : colors.textSecondary, fontWeight: "600" }]}>
            {paused ? "Resume memory" : "Pause capture"}
          </Text>
        </Tappable>
      </View>
    </Screen>
  );
}

const s = StyleSheet.create({
  stage: { flex: 1, alignItems: "center", justifyContent: "center" },
  pairChip: {
    marginTop: space.xl,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.pill,
    paddingVertical: space.sm,
    paddingHorizontal: space.lg,
  },
  actions: { flexDirection: "row", gap: space.md, paddingBottom: space.xl },
  action: { flex: 1, borderRadius: radius.pill, paddingVertical: space.lg, alignItems: "center" },
  actionGhost: { backgroundColor: "transparent", borderWidth: 1 },
});
