import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { useBrainStore } from "../../state/useBrainStore";
import { colors } from "../theme/colors";
import { typography } from "../theme/typography";
import { space, radius } from "../theme/spacing";
import { Tappable } from "./Tappable";
import { t } from "../../i18n";

/**
 * DemoBanner — an honest, always-visible marker that the screen is showing
 * labeled SAMPLE data (Demo Mode), not your real memory. Rendered by every
 * Screen when demoMode is on; tapping it jumps to Settings to turn it off and
 * pair a real Brain. Keeps us inside the repo's honesty contract.
 */
export function DemoBanner() {
  const router = useRouter();
  const demoMode = useBrainStore((s) => s.demoMode);
  if (!demoMode) return null;
  return (
    <View nativeID="dl-demo-banner" style={s.hold}>
      <Tappable onPress={() => router.push("/settings")} style={s.wrap}>
        <View style={s.dot} />
        <Text style={s.text}>
          {t("demo.bannerLabel")} — <Text style={s.link}>{t("demo.pairCta")}</Text>
        </Text>
      </Tappable>
    </View>
  );
}

const s = StyleSheet.create({
  hold: { alignSelf: "flex-start" },
  wrap: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: space.sm,
    backgroundColor: "rgba(47, 212, 196, 0.12)",
    borderColor: "rgba(47, 212, 196, 0.35)",
    borderWidth: 1,
    borderRadius: radius.pill,
    paddingVertical: 6,
    paddingHorizontal: space.md,
    marginBottom: space.md,
  },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.accentMemory },
  text: { ...typography.caption, color: colors.textPrimary, opacity: 1 },
  link: { color: colors.accentMemory, fontFamily: typography.eyebrow.fontFamily },
});
