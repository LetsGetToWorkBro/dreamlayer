import React from "react";
import { Animated, View, Text, StyleSheet, StyleProp, ViewStyle } from "react-native";
import { colors, platinum } from "../theme/colors";
import { typography } from "../theme/typography";
import { radius, space } from "../theme/spacing";
import { useEntrance } from "../anim";
import { Tappable } from "./Tappable";
import { Pinstripe } from "./Pinstripe";

/**
 * Card — a Mac OS 8.1 window/group-box. A light platinum face with a hard bevel
 * (light top-left, shadow bottom-right) reads as a raised panel on the desktop.
 * Pass `title` to grow a real pinstriped title bar with close/zoom boxes — a
 * window; leave it off for a plain group box. `active` swaps the bevel for an
 * accent frame; `onPress` makes it a tactile Tappable; `delay` staggers a
 * column into view. Every prop the app already passes is unchanged.
 */
export function Card({
  children,
  active,
  accent = colors.accentMemory,
  onPress,
  style,
  delay = 0,
  animate = true,
  title,
  titleRight,
}: {
  children: React.ReactNode;
  active?: boolean;
  accent?: string;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
  delay?: number;
  animate?: boolean;
  /** optional — render a pinstriped window title bar with this label */
  title?: string;
  /** optional right-hand slot inside the title bar (e.g. a status) */
  titleRight?: React.ReactNode;
}) {
  const anim = useEntrance(delay);
  const framed = !!title;

  const body = (
    <View
      style={[
        framed ? s.window : s.panel,
        active ? { borderColor: accent } : null,
        style,
      ]}
    >
      {framed ? (
        <View style={s.tbar}>
          <Pinstripe />
          <View style={[s.wbox, s.wclose]} />
          <Text style={s.ttext} numberOfLines={1}>{title}</Text>
          {titleRight ? <View style={s.tright}>{titleRight}</View> : <View style={[s.wbox, s.wzoom]} />}
        </View>
      ) : null}
      <View style={framed ? s.wbody : null}>
        {children}
      </View>
    </View>
  );

  const wrapped = onPress ? <Tappable onPress={onPress}>{body}</Tappable> : body;
  if (!animate) return wrapped;
  return <Animated.View style={anim}>{wrapped}</Animated.View>;
}

/** A small uppercase section label — the eyebrow that announces a group. */
export function Section({ label, accent = colors.accentMemory, first }: { label: string; accent?: string; first?: boolean }) {
  return (
    <Text style={[typography.eyebrow, { color: accent, marginTop: first ? 0 : space.xl, marginBottom: space.md }]}>
      {label}
    </Text>
  );
}

const BEVEL = {
  borderTopColor: platinum.hi,
  borderLeftColor: platinum.hi,
  borderBottomColor: platinum.sh,
  borderRightColor: platinum.sh,
  borderWidth: 1.5,
} as const;

const s = StyleSheet.create({
  // plain group box — a raised platinum panel
  panel: {
    backgroundColor: platinum.face,
    borderRadius: radius.sm,
    ...BEVEL,
    padding: space.lg,
    marginBottom: space.md,
    overflow: "hidden",
  },
  // a full window — black frame + drop shadow + a title bar
  window: {
    backgroundColor: platinum.face,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: platinum.frame,
    marginBottom: space.md,
    overflow: "hidden",
    shadowColor: "#000000",
    shadowOffset: { width: 2, height: 3 },
    shadowOpacity: 0.34,
    shadowRadius: 0,
    elevation: 4,
  },
  tbar: {
    height: 24,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 7,
    borderBottomWidth: 1,
    borderBottomColor: platinum.frame,
    gap: 7,
  },
  ttext: {
    flex: 1,
    ...typography.title,
    fontSize: 14.5,
    lineHeight: 18,
    color: platinum.ink,
    textAlign: "center",
  },
  tright: { minWidth: 12, alignItems: "flex-end" },
  wbox: {
    width: 12,
    height: 12,
    borderRadius: 2,
    borderWidth: 1,
    borderColor: platinum.frame,
    backgroundColor: platinum.face,
  },
  wclose: {},
  wzoom: {},
  wbody: { padding: space.lg },
});
