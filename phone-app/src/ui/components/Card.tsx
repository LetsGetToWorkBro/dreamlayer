import React from "react";
import {
  Animated, View, Text, Pressable, StyleSheet, StyleProp, ViewStyle,
  LayoutAnimation, Platform, UIManager,
} from "react-native";
import { colors, platinum } from "../theme/colors";
import { typography } from "../theme/typography";
import { radius, space } from "../theme/spacing";
import { hardShadow } from "../theme/shadow";
import { useEntrance } from "../anim";
import { motion } from "../theme/motion";
import { Tappable } from "./Tappable";
import { Pinstripe } from "./Pinstripe";

// classic-architecture Android needs LayoutAnimation switched on explicitly
if (Platform.OS === "android" && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

/**
 * Card — a Mac OS 8.1 window/group-box. A light platinum face with a hard bevel
 * (light top-left, shadow bottom-right) reads as a raised panel on the desktop.
 * Pass `title` to grow a real pinstriped title bar — and with it, a working
 * **WindowShade**: tap the bar (or its collapse box) and the window rolls up to
 * just the title, exactly like the desk accessory on the website. A shaded
 * window drops its pinstripes — the Platinum cue for "not the active window."
 * `active` swaps the bevel for an accent frame; `onPress` makes the whole card
 * a tactile Tappable (which disables shading); `delay` staggers a column into
 * view. Every prop the app already passes is unchanged.
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
  shade,
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
  /** optional right-hand slot inside the title bar (e.g. an action) */
  titleRight?: React.ReactNode;
  /** WindowShade — on by default for titled, non-pressable windows */
  shade?: boolean;
}) {
  const anim = useEntrance(delay);
  const framed = !!title;
  const shadeable = framed && !onPress && shade !== false;
  const [shut, setShut] = React.useState(false);

  const toggleShade = () => {
    if (!motion.reduceMotion) {
      LayoutAnimation.configureNext(LayoutAnimation.create(200, "easeInEaseOut", "opacity"));
    }
    setShut((v) => !v);
  };

  const body = (
    <View
      style={[
        framed ? s.window : s.panel,
        active ? { borderColor: accent } : null,
        style,
      ]}
    >
      {framed ? (
        <Pressable
          onPress={shadeable ? toggleShade : undefined}
          accessibilityRole={shadeable ? "button" : undefined}
          accessibilityLabel={shadeable ? `${title} — WindowShade` : undefined}
          accessibilityState={shadeable ? { expanded: !shut } : undefined}
          style={[s.tbar, shut ? s.tbarShut : null]}
        >
          {!shut && <Pinstripe />}
          <View style={s.wbox} />
          <Text style={[s.ttext, shut ? { color: platinum.ink2 } : null]} numberOfLines={1}>
            {title}
          </Text>
          {titleRight ? <View style={s.tright}>{titleRight}</View> : null}
          {shadeable ? (
            <View style={s.wbox}>
              <View style={s.shadeLine} />
            </View>
          ) : !titleRight ? (
            <View style={s.wbox} />
          ) : null}
        </Pressable>
      ) : null}
      {!shut || !framed ? <View style={framed ? s.wbody : null}>{children}</View> : null}
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
    ...hardShadow(2, 3, 0.34),
  },
  tbar: {
    height: 26,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 7,
    borderBottomWidth: 1,
    borderBottomColor: platinum.frame,
    gap: 7,
    overflow: "hidden",
  },
  // a shaded (rolled-up) window: plain face, no bottom rule needed but the
  // frame's own border closes the shape — keep the rule for the ledge read
  tbarShut: { backgroundColor: platinum.face },
  ttext: {
    flex: 1,
    ...typography.title,
    fontSize: 14.5,
    lineHeight: 18,
    color: platinum.ink,
    textAlign: "center",
  },
  tright: { alignItems: "flex-end", justifyContent: "center" },
  wbox: {
    width: 13,
    height: 13,
    borderRadius: 2,
    borderWidth: 1,
    borderColor: platinum.frame,
    backgroundColor: platinum.face,
    alignItems: "center",
    justifyContent: "center",
  },
  // the WindowShade box's horizontal tick
  shadeLine: { width: 7, height: 1.5, backgroundColor: "#333333" },
  wbody: { padding: space.lg },
});
