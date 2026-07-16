import React from "react";
import { Animated, View, Text, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { colors, platinum } from "../theme/colors";
import { typography } from "../theme/typography";
import { space, radius } from "../theme/spacing";
import { hardShadow } from "../theme/shadow";
import { useEntrance } from "../anim";
import { Pinstripe } from "./Pinstripe";
import { Tappable } from "./Tappable";

/**
 * ScreenHeader — the screen's title, rendered as a Mac OS 8.1 window title bar:
 * a pinstriped bar with the title in Chicago, framed and shadowed so every
 * screen reads as a window on the desktop. When the screen was pushed onto the
 * stack (a drill-in from the Brain hub or the Now home), the left box becomes a
 * back control — the iOS convention, in Platinum dress; a tab root shows the
 * plain close box. An optional eyebrow labels it above; a subtitle sits below;
 * the `right` slot (a status pill, an action) tucks into the bar. Pass
 * `back={false}` to force the plain box. API is otherwise unchanged.
 */
export function ScreenHeader({
  title,
  eyebrow,
  subtitle,
  right,
  back,
}: {
  title: string;
  eyebrow?: string;
  subtitle?: string;
  right?: React.ReactNode;
  /** override the auto back control (defaults to on when the stack can pop) */
  back?: boolean;
}) {
  const anim = useEntrance(0);
  const router = useRouter();
  const canBack = back !== false && (back === true || (router.canGoBack?.() ?? false));
  return (
    <Animated.View style={[s.wrap, anim]}>
      {eyebrow ? <Text style={[typography.eyebrow, s.eyebrow]}>{eyebrow}</Text> : null}
      <View style={s.bar}>
        <Pinstripe />
        {canBack ? (
          <Tappable onPress={() => router.back()} accessibilityLabel="Back" style={s.backBtn}>
            <Text style={s.backGlyph}>‹</Text>
          </Tappable>
        ) : (
          <View style={s.close} />
        )}
        <Text style={s.title} numberOfLines={1}>{title}</Text>
        {right ? <View style={s.right}>{right}</View> : <View style={s.zoom} />}
      </View>
      {subtitle ? <Text style={[typography.body, s.subtitle]}>{subtitle}</Text> : null}
    </Animated.View>
  );
}

const box = {
  width: 13,
  height: 13,
  borderRadius: 2,
  borderWidth: 1,
  borderColor: platinum.frame,
  backgroundColor: platinum.face,
} as const;

const s = StyleSheet.create({
  wrap: { marginBottom: space.lg },
  eyebrow: { color: colors.accentMemory, marginBottom: space.sm },
  bar: {
    flexDirection: "row",
    alignItems: "center",
    minHeight: 34,
    paddingHorizontal: space.sm,
    gap: space.sm,
    backgroundColor: platinum.face,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: platinum.frame,
    overflow: "hidden",
    ...hardShadow(2, 3, 0.34),
  },
  close: box,
  zoom: box,
  // a wider beveled back control with a chevron, in place of the close box
  backBtn: {
    minWidth: 34,
    height: 20,
    paddingHorizontal: 6,
    borderRadius: 3,
    borderWidth: 1,
    borderColor: platinum.frame,
    backgroundColor: platinum.faceHi,
    alignItems: "center",
    justifyContent: "center",
  },
  backGlyph: { ...typography.title, fontSize: 18, lineHeight: 20, color: platinum.ink, marginTop: -2 },
  title: {
    flex: 1,
    ...typography.title,
    fontSize: 19,
    lineHeight: 24,
    color: platinum.ink,
    textAlign: "center",
  },
  right: { minWidth: 13, alignItems: "flex-end", justifyContent: "center" },
  subtitle: { color: colors.textSecondary, marginTop: space.md, paddingHorizontal: space.xs },
});
