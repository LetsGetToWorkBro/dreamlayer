// HaloPairingRing.tsx
// Animated breathing ring shown on the Pair onboarding step.
//
// New Architecture (RN 0.79+) notes:
// - useNativeDriver: true is still valid and preferred for transform/opacity.
// - The Animated.loop / Animated.sequence / Animated.parallel APIs are
//   unchanged in the New Architecture.
// - useEffect / useRef are imported from "react" (not "react-native").
// - Easing is re-exported from react-native; no change needed.
import React, { useEffect, useRef } from "react";
import { View, Animated, Easing } from "react-native";
import { useTheme } from "../theme/useTheme";

export function HaloPairingRing({ scanning }: { scanning: boolean }) {
  const { colors } = useTheme();
  const scale   = useRef(new Animated.Value(1)).current;
  const opacity = useRef(new Animated.Value(0.3)).current;

  useEffect(() => {
    if (!scanning) {
      // Reset to idle state when not scanning
      scale.setValue(1);
      opacity.setValue(0.3);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.parallel([
          Animated.timing(scale, {
            toValue: 1.18,
            duration: 1200,
            easing: Easing.inOut(Easing.sin),
            useNativeDriver: true,
          }),
          Animated.timing(opacity, {
            toValue: 0.08,
            duration: 1200,
            easing: Easing.inOut(Easing.sin),
            useNativeDriver: true,
          }),
        ]),
        Animated.parallel([
          Animated.timing(scale, {
            toValue: 1.0,
            duration: 1200,
            easing: Easing.inOut(Easing.sin),
            useNativeDriver: true,
          }),
          Animated.timing(opacity, {
            toValue: 0.30,
            duration: 1200,
            easing: Easing.inOut(Easing.sin),
            useNativeDriver: true,
          }),
        ]),
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [scanning, scale, opacity]);

  return (
    <View
      style={{
        width: 160,
        height: 160,
        alignItems: "center",
        justifyContent: "center",
        alignSelf: "center",
      }}
    >
      {/* Outer animated breathing ring */}
      <Animated.View
        style={{
          position: "absolute",
          width: 160,
          height: 160,
          borderRadius: 80,
          borderWidth: 2,
          borderColor: colors.accentMemory,
          transform: [{ scale }],
          opacity,
        }}
      />
      {/* Static inner ring */}
      <View
        style={{
          width: 112,
          height: 112,
          borderRadius: 56,
          borderWidth: 1.5,
          borderColor: colors.accentMemory,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {/* Centre fill */}
        <View
          style={{
            width: 72,
            height: 72,
            borderRadius: 36,
            backgroundColor: colors.surface,
          }}
        />
      </View>
    </View>
  );
}
