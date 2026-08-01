/**
 * anim.ts — the app's motion vocabulary, native-driven and reduce-motion aware.
 *
 * Three building blocks:
 *   useReduceMotion()  — the OS "reduce motion" setting, live.
 *   useEntrance(delay) — a fade + gentle rise, for a view appearing on mount.
 *   usePressScale()    — a spring scale-down while pressed, for tactile taps.
 *
 * Timing mirrors src/ui/theme/motion.ts so the phone breathes with the HUD.
 */
import { useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Animated, Easing } from "react-native";
import { motion, setReduceMotion, subscribeReduceMotion } from "./theme/motion";

const EASE = Easing.bezier(0.16, 1, 0.3, 1); // motion.easeOut

/* ------------------------------------------------------- reduce motion --
 * ONE subscription to the OS for the whole app, refcounted by the hook: the
 * first component that asks attaches it, the last one to unmount removes it.
 * Everything downstream reads motion.reduceMotion instead of calling
 * AccessibilityInfo itself, so the setting has a single seam (see
 * theme/motion.ts) and screens stay testable without mocking react-native. */

let osWatchers = 0;
// RN 0.86: addEventListener returns an EmitterSubscription and there is no
// removeEventListener any more — the subscription is the only way back out.
let osSub: { remove: () => void } | null = null;

function watchOsReduceMotion(): () => void {
  if (osWatchers++ === 0) {
    osSub = AccessibilityInfo.addEventListener("reduceMotionChanged", (on) =>
      setReduceMotion(!!on)
    );
    // ...and the current value, which the change event alone never gives us.
    // If everyone unmounted before this settles, drop it on the floor.
    AccessibilityInfo.isReduceMotionEnabled()
      .then((on) => { if (osSub) setReduceMotion(!!on); })
      .catch(() => { /* no a11y manager in this runtime — motion stays on */ });
  }
  let released = false;
  return () => {
    if (released) return;   // a double teardown must not orphan the listener
    released = true;
    if (--osWatchers > 0) return;
    osSub?.remove();
    osSub = null;
  };
}

/** How many components are currently watching the OS setting. Test seam —
 * a leaked subscription shows up here as a count that never returns to 0. */
export function reduceMotionWatcherCount(): number {
  return osWatchers;
}

/** The OS "reduce motion" setting, live: re-renders the caller when it flips. */
export function useReduceMotion(): boolean {
  const [on, setOn] = useState(motion.reduceMotion);
  useEffect(() => {
    const stopWatching = watchOsReduceMotion();
    const unsubscribe = subscribeReduceMotion(setOn);
    setOn(motion.reduceMotion);   // a value that landed between render and effect
    return () => { unsubscribe(); stopWatching(); };
  }, []);
  return on;
}

/** The Mac OS 8 "zoom open": a window doesn't fade in, it GROWS in — a fade +
 * scale-up from 94% with a slight rise, the phone-sized read of the classic
 * zoom-rect. Plays once when the view mounts; `delay` staggers lists.
 * Under reduce motion there is no travel and no zoom: the view is simply
 * there, at rest, on the first frame. */
export function useEntrance(delay = 0, rise = 10) {
  const reduce = useReduceMotion();
  // Start at rest when motion is already reduced: the view must not render one
  // frame of the animation's start state before the effect snaps it.
  const opacity = useRef(new Animated.Value(reduce ? 1 : 0)).current;
  const translateY = useRef(new Animated.Value(reduce ? 0 : rise)).current;
  const scale = useRef(new Animated.Value(reduce ? 1 : 0.94)).current;
  // an entrance is a once-per-mount event: flipping the OS setting afterwards
  // must not replay it, only cut a running one short
  const played = useRef(false);

  useEffect(() => {
    if (reduce) {
      played.current = true;
      opacity.setValue(1);
      translateY.setValue(0);
      scale.setValue(1);
      return;
    }
    if (played.current) return;
    played.current = true;
    Animated.parallel([
      Animated.timing(opacity, { toValue: 1, duration: motion.base, delay, easing: EASE, useNativeDriver: true }),
      Animated.timing(translateY, { toValue: 0, duration: motion.slow, delay, easing: EASE, useNativeDriver: true }),
      Animated.timing(scale, { toValue: 1, duration: motion.slow, delay, easing: EASE, useNativeDriver: true }),
    ]).start();
  }, [reduce]);

  return { opacity, transform: [{ translateY }, { scale }] };
}

/** Returns a scale value + press handlers for a springy, tactile press.
 * Under reduce motion the surface holds its size — the haptic tick and the
 * pressed-in bevel still report the touch. */
export function usePressScale(to = 0.96) {
  const reduce = useReduceMotion();
  const scale = useRef(new Animated.Value(1)).current;
  const spring = (toValue: number) =>
    Animated.spring(scale, { toValue, useNativeDriver: true, speed: 40, bounciness: 6 }).start();
  return {
    scale,
    onPressIn: () => spring(reduce ? 1 : to),
    onPressOut: () => spring(1),
  };
}
