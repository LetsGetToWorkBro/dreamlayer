import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Tappable } from "../src/ui/components/Tappable";
import { useTheme, makeThemedStyles } from "../src/ui/theme/useTheme";
import { typography } from "../src/ui/theme/typography";
import { space } from "../src/ui/theme/spacing";
import { t } from "../src/i18n";

/**
 * Labs — the experiments, drilled into from the Brain hub. Every screen that
 * used to hang off the old Settings "Labs" list lives here as a grouped,
 * tappable row; nothing was removed, only regrouped one tap deeper.
 */
type Row = { route: string; labelKey: string };
const GROUPS: { section: string; rows: Row[] }[] = [
  {
    section: "Memory & story",
    rows: [
      { route: "/rewind", labelKey: "settings.rewindLink" },
      { route: "/saga", labelKey: "settings.sagaLink" },
      { route: "/ember", labelKey: "settings.emberLink" },
      { route: "/profile", labelKey: "settings.profileLink" },
    ],
  },
  {
    section: "Around you",
    rows: [
      { route: "/waypath", labelKey: "settings.waypathLink" },
      { route: "/packs", labelKey: "settings.feelLink" },
    ],
  },
  {
    section: "The layer",
    rows: [
      { route: "/terminal", labelKey: "settings.terminalLink" },
    ],
  },
  {
    section: "Your brain",
    rows: [
      { route: "/brain-tiers", labelKey: "settings.brainTierLink" },
      { route: "/capabilities", labelKey: "settings.capabilitiesLink" },
      { route: "/cloud", labelKey: "settings.cloudLink" },
      { route: "/vitals", labelKey: "settings.vitalsLink" },
      { route: "/plugins", labelKey: "settings.pluginsLink" },
      { route: "/receipts", labelKey: "settings.receiptsLink" },
    ],
  },
];

function LinkRow({ label, onPress, last }: { label: string; onPress: () => void; last?: boolean }) {
  const s = useS();
  const { colors } = useTheme();
  return (
    <Tappable onPress={onPress} style={[s.row, last ? s.rowLast : null]}>
      <Text style={[typography.body, { color: colors.textPrimary, flex: 1 }]}>{label}</Text>
      <Text style={s.chev}>›</Text>
    </Tappable>
  );
}

export default function Labs() {
  const s = useS();
  const router = useRouter();
  return (
    <Screen>
      <ScreenHeader title="Labs" eyebrow="Brain" subtitle="Experiments and deeper tools — one tap in, one tap back." />
      {GROUPS.map((g) => (
        <View key={g.section}>
          <Text style={[typography.eyebrow, s.section]}>{g.section}</Text>
          <View style={s.panel}>
            {g.rows.map((r, i) => (
              <LinkRow
                key={r.route + i}
                label={t(r.labelKey).replace(/\s*[→›]\s*$/, "")}
                onPress={() => router.push(r.route as never)}
                last={i === g.rows.length - 1}
              />
            ))}
          </View>
        </View>
      ))}
      <View style={{ height: space.xl }} />
    </Screen>
  );
}

const useS = makeThemedStyles(({ colors, platinum }) => StyleSheet.create({
  section: { color: colors.accentMemory, marginTop: space.xl, marginBottom: space.sm },
  panel: {
    backgroundColor: platinum.face,
    borderRadius: 10,
    borderTopColor: platinum.hi,
    borderLeftColor: platinum.hi,
    borderBottomColor: platinum.sh,
    borderRightColor: platinum.sh,
    borderWidth: 1.5,
    paddingHorizontal: space.lg,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: platinum.line,
  },
  rowLast: { borderBottomWidth: 0 },
  chev: { ...typography.title, fontSize: 18, color: platinum.sh, marginLeft: space.sm },
}));
