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

const CLIP_W = 400, CLIP_H = 226;   // the clip's intrinsic (landscape) size

const ANIM = require("../../../assets/juno.webp");   // animated true-alpha loop
const STILL = require("../../../assets/juno.png");    // still poster

export function Juno({
  width = 300,
  state = "idle",
  style,
}: {
  width?: number;
  state?: JunoState;
  style?: StyleProp<ViewStyle>;
}) {
  const aura = AURA_BY_STATE[state] ?? colors.accentMemory;
  const h = Math.round(width * CLIP_H / CLIP_W);   // preserve the clip's aspect

  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    let alive = true;
    AccessibilityInfo.isReduceMotionEnabled().then((v) => { if (alive) setReduce(!!v); });
    const sub = AccessibilityInfo.addEventListener("reduceMotionChanged", (v) => setReduce(!!v));
    return () => { alive = false; sub?.remove?.(); };
  }, []);

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

  return (
    <View style={[{ width, height: h, alignItems: "center", justifyContent: "center" }, style]}>
      {/* Aura — a soft wide bloom behind her, pulsing and state-tinted. */}
      <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.center, { opacity: auraA }]}>
        <View style={{ width: width * 0.72, height: h * 0.86, borderRadius: h, backgroundColor: aura, opacity: 0.14 }} />
        <View style={{ position: "absolute", width: width * 0.42, height: h * 0.6, borderRadius: h, backgroundColor: aura, opacity: 0.2 }} />
      </Animated.View>

      {/* Juno herself — the animated clip, gently floating. Still poster under
          reduce-motion. */}
      <Animated.View style={{ transform: [{ translateY }], ...(glow || {}) }}>
        {reduce
          ? <RNImage source={STILL} accessibilityLabel="Juno, the DreamLayer assistant" resizeMode="contain" style={{ width, height: h }} />
          : <ExpoImage source={ANIM} accessibilityLabel="Juno, the DreamLayer assistant" contentFit="contain" autoplay style={{ width, height: h }} />}
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { alignItems: "center", justifyContent: "center" },
});

export default Juno;
