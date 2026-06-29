import React, { useEffect, useRef } from "react";
import { View, Animated, Easing } from "react-native";
import { colors } from "../theme/colors";

export function HaloPairingRing({ scanning }: { scanning: boolean }) {
  const scale = useRef(new Animated.Value(1)).current;
  const opacity = useRef(new Animated.Value(0.3)).current;

  useEffect(() => {
    if (!scanning) return;
    const loop = Animated.loop(
      Animated.sequence([
        Animated.parallel([
          Animated.timing(scale,   { toValue: 1.18, duration: 1200, easing: Easing.inOut(Easing.sine), useNativeDriver: true }),
          Animated.timing(opacity, { toValue: 0.08, duration: 1200, easing: Easing.inOut(Easing.sine), useNativeDriver: true }),
        ]),
        Animated.parallel([
          Animated.timing(scale,   { toValue: 1.0,  duration: 1200, easing: Easing.inOut(Easing.sine), useNativeDriver: true }),
          Animated.timing(opacity, { toValue: 0.30, duration: 1200, easing: Easing.inOut(Easing.sine), useNativeDriver: true }),
        ]),
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [scanning]);

  return (
    <View style={{ width: 160, height: 160, alignItems: "center", justifyContent: "center", alignSelf: "center" }}>
      <Animated.View style={{
        position: "absolute",
        width: 160, height: 160, borderRadius: 80,
        borderWidth: 2, borderColor: colors.accentMemory,
        transform: [{ scale }], opacity,
      }} />
      <View style={{
        width: 112, height: 112, borderRadius: 56,
        borderWidth: 1.5, borderColor: colors.accentMemory,
        alignItems: "center", justifyContent: "center",
      }}>
        <View style={{ width: 72, height: 72, borderRadius: 36, backgroundColor: colors.surface }} />
      </View>
    </View>
  );
}
