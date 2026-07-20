import React from "react";
import { View, ScrollView, StyleSheet, StyleProp, ViewStyle } from "react-native";
// react-native-safe-area-context, not the RN one: RN's SafeAreaView is
// deprecated and — crucially — a no-op on Android, where SDK 57 draws the app
// edge-to-edge. This one insets identically on iOS and actually insets the
// status/navigation bars on Android.
import { SafeAreaView } from "react-native-safe-area-context";
import { makeThemedStyles } from "../theme/useTheme";
import { gutter, space } from "../theme/spacing";
import { CineBackdrop } from "./CineBackdrop";
import { DemoBanner } from "./DemoBanner";
import { MenuBar } from "./MenuBar";

/**
 * Screen — the frame every screen shares: the pinstripe Platinum desktop, the
 * menu bar across the top (ring mark + clock, like the website and Mac panel),
 * safe area, one horizontal gutter, and either a scroll body or a fixed one.
 * Keeps every page on the same desktop. Pass menuBar={false} for full-bleed
 * moments (the tour) that shouldn't wear the chrome.
 */
export function Screen({
  children,
  scroll = true,
  contentStyle,
  gutters = true,
  menuBar = true,
}: {
  children: React.ReactNode;
  scroll?: boolean;
  contentStyle?: StyleProp<ViewStyle>;
  gutters?: boolean;
  menuBar?: boolean;
}) {
  const s = useS();
  const pad = gutters ? { paddingHorizontal: gutter } : null;
  return (
    <View style={s.root}>
      <CineBackdrop />
      {scroll ? (
        <SafeAreaView style={s.safe}>
          {menuBar ? <MenuBar /> : null}
          <ScrollView
            contentContainerStyle={[s.scroll, pad, contentStyle]}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            <DemoBanner />
            {children}
          </ScrollView>
        </SafeAreaView>
      ) : (
        <SafeAreaView style={s.safe}>
          {menuBar ? <MenuBar /> : null}
          <View style={[s.fixed, pad, contentStyle]}>
            <DemoBanner />
            {children}
          </View>
        </SafeAreaView>
      )}
    </View>
  );
}

const useS = makeThemedStyles(({ colors, platinum }) => StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  safe: { flex: 1, backgroundColor: "transparent" },
  // extra bottom room so the last card clears the floating (absolute) tab bar
  scroll: { paddingTop: space.xl, paddingBottom: 116 },
  fixed: { flex: 1, paddingTop: space.xl, paddingBottom: 84 },
}));
