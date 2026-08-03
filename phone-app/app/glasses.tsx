import React from "react";
import { View, Text, StyleSheet, ActivityIndicator } from "react-native";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Tappable } from "../src/ui/components/Tappable";
import { makeThemedStyles } from "../src/ui/theme/useTheme";
import { typography } from "../src/ui/theme/typography";
import { space } from "../src/ui/theme/spacing";
import { useBrainStore } from "../src/state/useBrainStore";

/**
 * Glasses — the link between the Brain and the Halo.
 *
 * There is deliberately almost nothing here, and that is the feature. The
 * Brain's link subscribes to the same fan-out the Live Lens does, so once it is
 * up EVERY card the phone shows the glasses show too — including cards from
 * producers written long after this screen. There is no per-feature switch to
 * forget to turn on, so this screen is a connect button and an honest status.
 *
 * The status distinguishes two things a simpler screen would conflate:
 * CONNECTED (a radio is up) and DRIVING (a card has actually landed on the
 * device). A connected link that has carried nothing is not a working one, the
 * same distinction the capability report draws between an importable adapter
 * and a used one.
 */
export default function GlassesScreen() {
  const s = useS();
  const status = useBrainStore((st) => st.haloStatus);
  const getHalo = useBrainStore((st) => st.getHalo);
  const connectHalo = useBrainStore((st) => st.connectHalo);
  const disconnectHalo = useBrainStore((st) => st.disconnectHalo);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    getHalo();
  }, [getHalo]);

  const onConnect = async (bridge: "emulator" | "real") => {
    setBusy(true);
    try {
      await connectHalo(bridge);
    } finally {
      setBusy(false);
    }
  };

  const onDisconnect = async () => {
    setBusy(true);
    try {
      await disconnectHalo();
    } finally {
      setBusy(false);
    }
  };

  const state = !status.connected
    ? "Not linked"
    : status.driving
      ? "Linked · showing cards"
      : "Linked · nothing shown yet";

  return (
    <Screen>
      <ScreenHeader title="Glasses" />
      <View style={s.card} accessibilityRole="summary">
        <Text style={s.state} accessibilityLabel={"Glasses: " + state}>
          {state}
        </Text>
        <Text style={s.detail}>
          {status.connected
            ? `${status.sent} card${status.sent === 1 ? "" : "s"} sent` +
              (status.failures ? ` · ${status.failures} failed` : "") +
              (status.queued ? ` · ${status.queued} waiting` : "")
            : "Everything the Live Lens shows will appear on the glasses once linked."}
        </Text>
        {!!status.last_error && (
          <Text style={s.error}>Last error: {status.last_error}</Text>
        )}
      </View>

      {busy ? (
        <ActivityIndicator style={{ marginTop: space.lg }} />
      ) : status.connected ? (
        <Tappable onPress={onDisconnect} style={s.row}>
          <Text style={s.rowLabel}>Unlink</Text>
        </Tappable>
      ) : (
        <>
          <Tappable onPress={() => onConnect("real")} style={s.row}>
            <Text style={s.rowLabel}>Link my Halo</Text>
            <Text style={s.rowHint}>Over Bluetooth, on this device only</Text>
          </Tappable>
          <Tappable onPress={() => onConnect("emulator")} style={s.row}>
            <Text style={s.rowLabel}>Link the emulator</Text>
            <Text style={s.rowHint}>
              No hardware needed — the same wire, drawn on a stand-in
            </Text>
          </Tappable>
        </>
      )}
    </Screen>
  );
}

const useS = makeThemedStyles(({ colors, platinum }) =>
  StyleSheet.create({
    card: {
      marginHorizontal: space.md,
      marginTop: space.md,
      padding: space.md,
      borderRadius: 14,
      backgroundColor: platinum.face,
    },
    state: { ...typography.title, color: colors.textPrimary },
    detail: {
      ...typography.body,
      color: colors.textSecondary,
      marginTop: space.xs,
    },
    error: {
      ...typography.caption,
      color: colors.accentError,
      marginTop: space.xs,
    },
    row: {
      marginHorizontal: space.md,
      marginTop: space.sm,
      padding: space.md,
      borderRadius: 14,
      backgroundColor: platinum.face,
    },
    rowLabel: { ...typography.body, color: colors.textPrimary },
    rowHint: {
      ...typography.caption,
      color: colors.textSecondary,
      marginTop: 2,
    },
  }),
);
