// Juno.tsx
// Juno — the DreamLayer assistant — alive on the phone.
//
// She's a real animated clip: assets/juno.webp is an animated, true-alpha WebP
// (her luma-keyed idle loop — she drifts, her four wings and hair move, the orb
// glows, memory-glyphs orbit her) played by expo-image, which handles animated
// WebP with transparency on iOS and Android. The clip carries her performance
// and its own orbiting glyphs; around her we keep only a soft, state-tinted aura
// and a gentle float. She's a wide (landscape) composition.
//
// Reduce-motion (AccessibilityInfo) → she holds still on a frame (assets/juno.png)
// with a faint steady aura, and nothing loops.
// `state` (idle | thinking | success) tints the aura and her glow.
//
//   <Juno width={300} state="thinking" />
import React, { useEffect, useRef, useState } from "react";
import {
  View, Text, Pressable, Animated, Easing, StyleSheet, Platform, Image as RNImage,
  type ViewStyle, type StyleProp,
} from "react-native";
import { Image as ExpoImage } from "expo-image";
import Svg, { Defs, RadialGradient, Stop, Ellipse } from "react-native-svg";
import { useTheme, makeThemedStyles } from "../theme/useTheme";
import type { Theme } from "../theme/useTheme";
import { useReduceMotion } from "../anim";
import { playEarcon } from "../../services/sound";

export type JunoState = "idle" | "thinking" | "success";

// Tap-to-speak: she cycles through her attention cues, out loud, with a caption
// to match — the phone version of the website's "click Juno, she says things".
// Each entry maps a caption to one of sound.ts's earcon families (which pick a
// random variant), so repeated taps never feel canned.
const SPEAK_CYCLE: readonly { phrase: string; family: string }[] = [
  { phrase: "hey.",       family: "hey" },
  { phrase: "hello.",     family: "hey" },      // hey2 is the "Hello" take
  { phrase: "look.",      family: "look" },
  { phrase: "watch out.", family: "watchout" },
  { phrase: "listen.",    family: "listen" },
  { phrase: "kept — not uploaded — kept.", family: "sfx" },
];

const auraByState = ({ colors }: Theme): Record<JunoState, string> => ({
  idle:    colors.accentMemory,   // teal
  thinking:colors.accentMemory,
  success: colors.accentSuccess,  // green
});

const CLIP_W = 400, CLIP_H = 226;   // the clip's intrinsic (landscape) size

/** What a screen reader calls her. One constant — the animated clip and the
 * reduce-motion still are the same character. */
const JUNO_LABEL = "Juno, the DreamLayer assistant";

const ANIM = require("../../../assets/juno.webp");   // animated true-alpha loop
const STILL = require("../../../assets/juno.png");    // still poster

export function Juno({
  width = 300,
  state = "idle",
  style,
  speakOnTap = true,
  onSpeak,
}: {
  width?: number;
  state?: JunoState;
  style?: StyleProp<ViewStyle>;
  /** Tap her to hear a cue + see a caption. On by default; pass false where
   * Juno sits inside another touchable that should own the tap. */
  speakOnTap?: boolean;
  /** Notified with the caption each time she speaks (for a parent-owned bubble). */
  onSpeak?: (phrase: string) => void;
}) {
  const styles = useStyles();
  const theme = useTheme();
  const { colors } = theme;
  const aura = auraByState(theme)[state] ?? colors.accentMemory;
  const h = Math.round(width * CLIP_H / CLIP_W);   // preserve the clip's aspect

  // the OS setting, through the app's one seam (src/ui/anim.ts) rather than a
  // second AccessibilityInfo subscription of her own
  const reduce = useReduceMotion();

  // Ambient motion — the clip carries her body; these carry the mood.
  const float = useRef(new Animated.Value(0)).current;   // 0..1 gentle bob
  const auraA = useRef(new Animated.Value(0.32)).current;

  useEffect(() => {
    if (reduce) { float.setValue(0.5); auraA.setValue(0.24); return; }
    const loops = [
      Animated.loop(Animated.sequence([
        Animated.timing(float, { toValue: 1, duration: 3400, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        Animated.timing(float, { toValue: 0, duration: 3400, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      ])),
      Animated.loop(Animated.sequence([
        Animated.timing(auraA, { toValue: 0.46, duration: 2600, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        Animated.timing(auraA, { toValue: 0.2,  duration: 2600, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      ])),
    ];
    loops.forEach((l) => l.start());
    return () => loops.forEach((l) => l.stop());
  }, [reduce, float, auraA]);

  const translateY = float.interpolate({ inputRange: [0, 1], outputRange: [4, -5] });

  const glow = Platform.OS === "ios"
    ? { shadowColor: aura, shadowOpacity: state === "idle" ? 0.28 : 0.5, shadowRadius: 20, shadowOffset: { width: 0, height: 0 } }
    : null;

  // Tap-to-speak: a cue out loud + a caption that fades. (Feedback is the sound
  // + the caption bubble; we deliberately don't add another Animated timeline on
  // top of her two idle loops.)
  const [caption, setCaption] = useState<string | null>(null);
  const cycleRef = useRef(0);
  const capTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (capTimer.current) clearTimeout(capTimer.current); }, []);

  const speak = () => {
    if (!speakOnTap) return;           // inert when disabled, but the node still mounts (keeps testID/layout stable)
    const c = SPEAK_CYCLE[cycleRef.current++ % SPEAK_CYCLE.length]!;
    playEarcon(c.family);              // never throws; silent no-op if audio is unavailable
    setCaption(c.phrase);
    onSpeak?.(c.phrase);
    if (capTimer.current) clearTimeout(capTimer.current);
    capTimer.current = setTimeout(() => setCaption(null), 2600);
  };

  return (
    <View style={[{ width, height: h, alignItems: "center", justifyContent: "center" }, style]}>
      {/* Caption — a Platinum speech well that appears when she speaks, then fades. */}
      {caption ? (
        <View
          pointerEvents="none"
          style={styles.capWrap}
          // what she just said is a status readout: announce it when it
          // appears instead of leaving it as silent decoration
          accessibilityLiveRegion="polite"
          accessibilityRole="text"
        >
          <View style={styles.capBubble}>
            <Text style={styles.capText}>{caption}</Text>
          </View>
        </View>
      ) : null}

      {/* Aura — a soft wide bloom behind her, pulsing and state-tinted. */}
      <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.center, { opacity: auraA }]}>
        <View style={{ width: width * 0.72, height: h * 0.86, borderRadius: h, backgroundColor: aura, opacity: 0.14 }} />
        <View style={{ position: "absolute", width: width * 0.42, height: h * 0.6, borderRadius: h, backgroundColor: aura, opacity: 0.2 }} />
      </Animated.View>

      {/* Juno herself — the animated clip, gently floating. Still poster under
          reduce-motion. Tapping her (when speakOnTap) fires a cue + caption —
          so when she is tappable she must announce as a button; when she is
          not, the Pressable stays out of the a11y tree entirely and her image
          remains the single labeled node (she sits inside someone else's
          touchable in that case). */}
      <Pressable
        testID="juno-tap"
        onPress={speak}
        accessible={speakOnTap}
        accessibilityRole={speakOnTap ? "button" : undefined}
        accessibilityHint={speakOnTap ? "Plays one of Juno's cues" : undefined}
        hitSlop={8}
      >
        <Animated.View style={{ transform: [{ translateY }], ...(glow || {}) }}>
          {/* Android can't render the iOS layer glow (shadow* is a no-op and a
              boxShadow would hug her rectangle, not her). A radial bloom behind
              the clip carries the same steady, state-tinted light, and floats
              with her because it lives inside the same translated view. */}
          {Platform.OS === "android" ? (
            <View pointerEvents="none" style={StyleSheet.absoluteFill}>
              <Svg width={width} height={h}>
                <Defs>
                  <RadialGradient id="junoBloom" cx="50%" cy="50%" rx="50%" ry="50%">
                    <Stop offset="0%" stopColor={aura} stopOpacity={state === "idle" ? 0.28 : 0.5} />
                    <Stop offset="65%" stopColor={aura} stopOpacity={(state === "idle" ? 0.28 : 0.5) * 0.35} />
                    <Stop offset="100%" stopColor={aura} stopOpacity={0} />
                  </RadialGradient>
                </Defs>
                <Ellipse cx={width / 2} cy={h / 2} rx={width / 2} ry={h / 2} fill="url(#junoBloom)" />
              </Svg>
            </View>
          ) : null}
          {/* her mood is carried by the aura tint alone, which is nothing to a
              screen reader — carry it as the image's value instead */}
          {reduce
            ? <RNImage source={STILL} accessibilityRole="image" accessibilityLabel={JUNO_LABEL} accessibilityValue={{ text: state }} resizeMode="contain" style={{ width, height: h }} />
            : <ExpoImage source={ANIM} accessibilityRole="image" accessibilityLabel={JUNO_LABEL} accessibilityValue={{ text: state }} contentFit="contain" autoplay style={{ width, height: h }} />}
        </Animated.View>
      </Pressable>
    </View>
  );
}

const useStyles = makeThemedStyles(({ colors, platinum }) => StyleSheet.create({
  center: { alignItems: "center", justifyContent: "center" },
  capWrap: { position: "absolute", top: -6, left: 0, right: 0, alignItems: "center", zIndex: 5 },
  capBubble: {
    maxWidth: "92%",
    backgroundColor: colors.surfaceElevated,
    borderColor: colors.borderSubtle,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  capText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600", textAlign: "center" },
}));

export default Juno;
