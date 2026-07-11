// Juno.tsx
// Juno — the DreamLayer assistant — rendered "alive" on the phone.
//
// The web build composites a packed color+matte video to a canvas for true
// transparency (assets/juno/juno.js). React Native has no <video> compositor,
// so here she's a transparent PNG (assets/juno.png, AI-matted full body) that
// we make *feel* living with RN Animated: a slow float bob, a breathing scale,
// a soft turning drift, a pulsing aura behind her, and a few rising sparkles.
// Everything runs on the native driver (transform/opacity only) so it stays
// smooth and never blocks JS.
//
// Reduce-motion (AccessibilityInfo) → she holds still with a faint steady aura.
// `state` (idle | thinking | success) tints the aura and her glow, mirroring
// the web sprite's data-state.
//
//   <Juno size={180} state="thinking" />
//
// New Architecture (RN 0.81): Animated.loop/sequence/parallel + useNativeDriver
// are unchanged; Easing is re-exported from react-native.
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  View, Animated, Easing, StyleSheet, AccessibilityInfo, Platform,
  type ViewStyle, type StyleProp,
} from "react-native";
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

export function Juno({
  size = 180,
  state = "idle",
  style,
}: {
  size?: number;
  state?: JunoState;
  style?: StyleProp<ViewStyle>;
}) {
  const aura = AURA_BY_STATE[state] ?? colors.accentMemory;
  const h = Math.round(size * 458 / 318);   // preserve the matte's aspect ratio

  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    let alive = true;
    AccessibilityInfo.isReduceMotionEnabled().then((v) => { if (alive) setReduce(!!v); });
    const sub = AccessibilityInfo.addEventListener("reduceMotionChanged", (v) => setReduce(!!v));
    return () => { alive = false; sub?.remove?.(); };
  }, []);

  // Motion values — created once, driven by loops below.
  const float   = useRef(new Animated.Value(0)).current;  // 0..1 bob
  const breathe = useRef(new Animated.Value(0)).current;  // 0..1 scale
  const turn    = useRef(new Animated.Value(0)).current;  // -1..1 sway
  const auraA   = useRef(new Animated.Value(0.35)).current;
  const sparks  = useMemo(() => SPARKS.map((s) => ({ ...s, v: new Animated.Value(0) })), []);

  useEffect(() => {
    if (reduce) {
      float.setValue(0.5); breathe.setValue(0.5); turn.setValue(0); auraA.setValue(0.28);
      return;
    }
    const pingpong = (v: Animated.Value, to: number, dur: number) =>
      Animated.loop(Animated.sequence([
        Animated.timing(v, { toValue: to, duration: dur, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        Animated.timing(v, { toValue: 0,  duration: dur, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      ]));

    const loops = [
      pingpong(float, 1, 2600),
      pingpong(breathe, 1, 3300),
      Animated.loop(Animated.sequence([
        Animated.timing(turn, { toValue: 1,  duration: 4200, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        Animated.timing(turn, { toValue: -1, duration: 4200, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
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
  }, [reduce, float, breathe, turn, auraA, sparks]);

  const translateY = float.interpolate({ inputRange: [0, 1], outputRange: [6, -10] });
  const scale      = breathe.interpolate({ inputRange: [0, 1], outputRange: [0.99, 1.02] });
  const rotate     = turn.interpolate({ inputRange: [-1, 1], outputRange: ["-2.2deg", "2.2deg"] });
  const translateX = turn.interpolate({ inputRange: [-1, 1], outputRange: [-4, 4] });

  return (
    <View style={[{ width: size, height: h, alignItems: "center", justifyContent: "center" }, style]}>
      {/* Aura — three soft concentric glows so the bloom reads on Android too
          (where shadowRadius doesn't paint). Pulses with auraA. */}
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

      {/* Juno herself. */}
      <Animated.Image
        source={require("../../../assets/juno.png")}
        accessibilityLabel="Juno, the DreamLayer assistant"
        resizeMode="contain"
        style={{
          width: size, height: h,
          transform: [{ translateY }, { translateX }, { rotate }, { scale }],
          ...(Platform.OS === "ios"
            ? { shadowColor: aura, shadowOpacity: state === "idle" ? 0.35 : 0.55, shadowRadius: 18, shadowOffset: { width: 0, height: 0 } }
            : null),
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  center: { alignItems: "center", justifyContent: "center" },
  glow:   { position: "absolute" },
});

export default Juno;
