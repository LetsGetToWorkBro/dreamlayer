// Juno.tsx
// Juno — the DreamLayer assistant — alive on the phone.
//
// She's a real animated clip, not a still: assets/juno.webp is an animated,
// true-alpha WebP (her AI-matted idle loop — she drifts, her wings and hair and
// dress move) played by expo-image, which handles animated WebP with
// transparency on both iOS and Android. Around her we keep a soft, state-tinted
// aura and a few rising sparkles, plus a gentle float — the *ambient* motion,
// while the clip itself carries her performance.
//
// Reduce-motion (AccessibilityInfo) → she holds still on the first frame
// (assets/juno.png) with a faint steady aura, and nothing loops.
// `state` (idle | thinking | success) tints the aura and her glow.
//
//   <Juno size={135} state="thinking" />
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  View, Animated, Easing, StyleSheet, AccessibilityInfo, Platform, Image as RNImage,
  type ViewStyle, type StyleProp,
} from "react-native";
import { Image as ExpoImage } from "expo-image";
import { colors } from "../theme/colors";

export type JunoState = "idle" | "thinking" | "success";

const AURA_BY_STATE: Record<JunoState, string> = {
  idle:    colors.accentMemory,   // teal
  thinking:colors.accentMemory,
  success: colors.accentSuccess,  // green
};

// A handful of sparkles at fixed positions around her (fractions of the frame),
// each with its own drift so they don't pulse in lockstep. Deterministic — no
// Math.random — so tests and renders are stable.
const SPARKS = [
  { x: 0.16, y: 0.30, r: 2.4, delay: 0,    rise: 22, dur: 3200 },
  { x: 0.82, y: 0.24, r: 3.0, delay: 600,  rise: 26, dur: 3800 },
  { x: 0.70, y: 0.58, r: 2.0, delay: 1400, rise: 18, dur: 3000 },
  { x: 0.24, y: 0.62, r: 2.6, delay: 900,  rise: 24, dur: 3500 },
  { x: 0.90, y: 0.46, r: 1.8, delay: 1900, rise: 20, dur: 4200 },
  { x: 0.08, y: 0.48, r: 2.2, delay: 300,  rise: 16, dur: 3600 },
];

const ANIM = require("../../../assets/juno.webp");   // animated true-alpha loop
const STILL = require("../../../assets/juno.png");    // first-frame poster

export function Juno({
  size = 135,
  state = "idle",
  style,
}: {
  size?: number;
  state?: JunoState;
  style?: StyleProp<ViewStyle>;
}) {
  const aura = AURA_BY_STATE[state] ?? colors.accentMemory;
  const h = Math.round(size * 426 / 240);   // the clip's aspect (poster matches)

  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    let alive = true;
    AccessibilityInfo.isReduceMotionEnabled().then((v) => { if (alive) setReduce(!!v); });
    const sub = AccessibilityInfo.addEventListener("reduceMotionChanged", (v) => setReduce(!!v));
    return () => { alive = false; sub?.remove?.(); };
  }, []);

  // Ambient motion values — the clip carries her body; these carry the mood.
  const float  = useRef(new Animated.Value(0)).current;   // 0..1 gentle bob
  const auraA  = useRef(new Animated.Value(0.35)).current;
  const sparks = useMemo(() => SPARKS.map((s) => ({ ...s, v: new Animated.Value(0) })), []);

  useEffect(() => {
    if (reduce) { float.setValue(0.5); auraA.setValue(0.26); return; }
    const loops = [
      Animated.loop(Animated.sequence([
        Animated.timing(float, { toValue: 1, duration: 3200, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        Animated.timing(float, { toValue: 0, duration: 3200, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      ])),
      Animated.loop(Animated.sequence([
        Animated.timing(auraA, { toValue: 0.5,  duration: 2600, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        Animated.timing(auraA, { toValue: 0.22, duration: 2600, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      ])),
      ...sparks.map((s) => Animated.loop(Animated.sequence([
        Animated.delay(s.delay),
        Animated.timing(s.v, { toValue: 1, duration: s.dur, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
        Animated.timing(s.v, { toValue: 0, duration: 0, useNativeDriver: true }),
      ]))),
    ];
    loops.forEach((l) => l.start());
    return () => loops.forEach((l) => l.stop());
  }, [reduce, float, auraA, sparks]);

  const translateY = float.interpolate({ inputRange: [0, 1], outputRange: [5, -6] });

  const glow = Platform.OS === "ios"
    ? { shadowColor: aura, shadowOpacity: state === "idle" ? 0.3 : 0.5, shadowRadius: 18, shadowOffset: { width: 0, height: 0 } }
    : null;

  return (
    <View style={[{ width: size, height: h, alignItems: "center", justifyContent: "center" }, style]}>
      {/* Aura — three soft concentric glows so the bloom reads on Android too. */}
      <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.center, { opacity: auraA }]}>
        <View style={[styles.glow, { width: size * 0.92, height: size * 0.92, borderRadius: size, backgroundColor: aura, opacity: 0.16 }]} />
        <View style={[styles.glow, { width: size * 0.62, height: size * 0.62, borderRadius: size, backgroundColor: aura, opacity: 0.20 }]} />
        <View style={[styles.glow, { width: size * 0.34, height: size * 0.34, borderRadius: size, backgroundColor: aura, opacity: 0.28 }]} />
      </Animated.View>

      {/* Sparkles rising through her aura. */}
      {sparks.map((s, i) => {
        const op = s.v.interpolate({ inputRange: [0, 0.15, 0.7, 1], outputRange: [0, 0.9, 0.7, 0] });
        const ty = s.v.interpolate({ inputRange: [0, 1], outputRange: [0, -s.rise] });
        return (
          <Animated.View
            key={i}
            pointerEvents="none"
            style={{
              position: "absolute",
              left: size * s.x, top: h * s.y,
              width: s.r * 2, height: s.r * 2, borderRadius: s.r,
              backgroundColor: aura,
              opacity: reduce ? 0 : op,
              transform: [{ translateY: ty }],
            }}
          />
        );
      })}

      {/* Juno herself — the animated clip, gently floating. Still poster when
          reduce-motion is on. */}
      <Animated.View style={{ transform: [{ translateY }], ...(glow || {}) }}>
        {reduce
          ? <RNImage source={STILL} accessibilityLabel="Juno, the DreamLayer assistant" resizeMode="contain" style={{ width: size, height: h }} />
          : <ExpoImage source={ANIM} accessibilityLabel="Juno, the DreamLayer assistant" contentFit="contain" autoplay style={{ width: size, height: h }} />}
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { alignItems: "center", justifyContent: "center" },
  glow:   { position: "absolute" },
});

export default Juno;
