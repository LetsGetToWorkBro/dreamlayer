/**
 * anim.ts — the app's motion vocabulary, native-driven and reduce-motion aware.
 *
 * Two building blocks:
 *   useEntrance(delay) — a fade + gentle rise, for a view appearing on mount.
 *   usePressScale()    — a spring scale-down while pressed, for tactile taps.
 *
 * Timing mirrors src/ui/theme/motion.ts so the phone breathes with the HUD.
 */
import { useEffect, useRef } from "react";
import { Animated, Easing } from "react-native";
import { motion } from "./theme/motion";

const EASE = Easing.bezier(0.16, 1, 0.3, 1); // motion.easeOut

/** A fade + rise that plays once when the view mounts. `delay` staggers lists. */
export function useEntrance(delay = 0, rise = 14) {
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(rise)).current;

  useEffect(() => {
    if (motion.reduceMotion) {
      opacity.setValue(1);
      translateY.setValue(0);
      return;
    }
    Animated.parallel([
      Animated.timing(opacity, { toValue: 1, duration: motion.base, delay, easing: EASE, useNativeDriver: true }),
      Animated.timing(translateY, { toValue: 0, duration: motion.slow, delay, easing: EASE, useNativeDriver: true }),
    ]).start();
  }, []);

  return { opacity, transform: [{ translateY }] };
}

/** Returns a scale value + press handlers for a springy, tactile press. */
export function usePressScale(to = 0.96) {
  const scale = useRef(new Animated.Value(1)).current;
  const spring = (toValue: number) =>
    Animated.spring(scale, { toValue, useNativeDriver: true, speed: 40, bounciness: 6 }).start();
  return {
    scale,
    onPressIn: () => spring(motion.reduceMotion ? 1 : to),
    onPressOut: () => spring(1),
  };
}
