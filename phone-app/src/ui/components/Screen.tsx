import React from "react";
import { View, ScrollView, SafeAreaView, StyleSheet, StyleProp, ViewStyle } from "react-native";
import { colors } from "../theme/colors";
import { gutter, space } from "../theme/spacing";
import { CineBackdrop } from "./CineBackdrop";

/**
 * Screen — the frame every screen shares: a cinematic backdrop (teal glow +
 * vignette), full-bleed black, safe area, one horizontal gutter, and either a
 * scroll body or a fixed one. Keeps every page on the same luminous surface.
 */
export function Screen({
  children,
  scroll = true,
  contentStyle,
  gutters = true,
}: {
  children: React.ReactNode;
  scroll?: boolean;
  contentStyle?: StyleProp<ViewStyle>;
  gutters?: boolean;
}) {
  const pad = gutters ? { paddingHorizontal: gutter } : null;
  return (
    <View style={s.root}>
      <CineBackdrop />
      {scroll ? (
        <SafeAreaView style={s.safe}>
          <ScrollView
            contentContainerStyle={[s.scroll, pad, contentStyle]}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            {children}
          </ScrollView>
        </SafeAreaView>
      ) : (
        <SafeAreaView style={s.safe}>
          <View style={[s.fixed, pad, contentStyle]}>{children}</View>
        </SafeAreaView>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  safe: { flex: 1, backgroundColor: "transparent" },
  // extra bottom room so the last card clears the floating (absolute) tab bar
  scroll: { paddingTop: space.xl, paddingBottom: 116 },
  fixed: { flex: 1, paddingTop: space.xl, paddingBottom: 84 },
});
