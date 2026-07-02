import React from "react";
import { View, ScrollView, SafeAreaView, StyleSheet, StyleProp, ViewStyle } from "react-native";
import { colors } from "../theme/colors";
import { gutter, space } from "../theme/spacing";

/**
 * Screen — the frame every screen shares: full-bleed background, safe area,
 * one horizontal gutter, and either a scroll body or a fixed one. Keeps every
 * page on the same grid so the app reads as one surface.
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
  if (scroll) {
    return (
      <SafeAreaView style={s.safe}>
        <ScrollView
          contentContainerStyle={[s.scroll, pad, contentStyle]}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {children}
        </ScrollView>
      </SafeAreaView>
    );
  }
  return (
    <SafeAreaView style={s.safe}>
      <View style={[s.fixed, pad, contentStyle]}>{children}</View>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { paddingTop: space.xl, paddingBottom: space.huge },
  fixed: { flex: 1, paddingTop: space.xl },
});
