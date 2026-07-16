import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { useBrainStore } from "../../state/useBrainStore";
import { colors, platinum } from "../theme/colors";
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
  // the pale-yellow Balloon Help note, hard-framed with a dropped shadow
  wrap: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: space.sm,
    backgroundColor: "#FFFFE8",
    borderColor: platinum.frame,
    borderWidth: 1,
    borderRadius: 4,
    paddingVertical: 6,
    paddingHorizontal: space.md,
    marginBottom: space.md,
    shadowColor: "#000000",
    shadowOffset: { width: 1, height: 2 },
    shadowOpacity: 0.3,
    shadowRadius: 0,
    elevation: 3,
  },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.accentAttention },
  text: { ...typography.caption, color: "#222222", opacity: 1 },
  link: { color: colors.accentMemory, fontFamily: typography.eyebrow.fontFamily },
});
