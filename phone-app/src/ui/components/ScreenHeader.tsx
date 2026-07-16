import React from "react";
import { Animated, View, Text, StyleSheet } from "react-native";
import { colors, platinum } from "../theme/colors";
import { typography } from "../theme/typography";
import { space, radius } from "../theme/spacing";
import { useEntrance } from "../anim";
import { Pinstripe } from "./Pinstripe";

/**
 * ScreenHeader — the screen's title, rendered as a Mac OS 8.1 window title bar:
 * a pinstriped bar with close/zoom boxes and the title in Chicago, framed and
 * shadowed so every screen reads as a window opening on the desktop. An optional
 * eyebrow labels it above; a subtitle sits below; the `right` slot (a status
 * pill, an action) tucks into the bar. Rises in on mount. API unchanged.
 */
export function ScreenHeader({
  title,
  eyebrow,
  subtitle,
  right,
}: {
  title: string;
  eyebrow?: string;
  subtitle?: string;
  right?: React.ReactNode;
}) {
  const anim = useEntrance(0);
  return (
    <Animated.View style={[s.wrap, anim]}>
      {eyebrow ? <Text style={[typography.eyebrow, s.eyebrow]}>{eyebrow}</Text> : null}
      <View style={s.bar}>
        <Pinstripe />
        <View style={s.close} />
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
    shadowColor: "#000000",
    shadowOffset: { width: 2, height: 3 },
    shadowOpacity: 0.34,
    shadowRadius: 0,
    elevation: 4,
  },
  close: box,
  zoom: box,
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
