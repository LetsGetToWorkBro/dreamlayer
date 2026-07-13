import React from "react";
import { Animated, Pressable, ViewStyle, StyleProp, AccessibilityRole } from "react-native";
import { usePressScale } from "../anim";
import { tapLight } from "../../services/haptics";

/**
 * Tappable — the one touch primitive. A spring scale-down plus a light haptic
 * tick on press gives every interactive surface the same tactile feel. Drop-in
 * for TouchableOpacity. Pass haptic={false} for surfaces that shouldn't buzz.
 *
 * Accessibility: every Tappable announces itself as a button (override with
 * accessibilityRole) and reports its disabled state, so screen readers see an
 * actionable control, not a silent view. Text children are read automatically;
 * icon-only surfaces MUST pass accessibilityLabel or they are unlabeled to
 * VoiceOver/TalkBack.
 */
export function Tappable({
  children,
  onPress,
  disabled,
  style,
  scaleTo = 0.96,
  hitSlop = 6,
  haptic = true,
  accessibilityLabel,
  accessibilityHint,
  accessibilityRole = "button",
}: {
  children: React.ReactNode;
  onPress?: () => void;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  scaleTo?: number;
  hitSlop?: number;
  haptic?: boolean;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  accessibilityRole?: AccessibilityRole;
}) {
  const { scale, onPressIn, onPressOut } = usePressScale(scaleTo);
  return (
    <Pressable
      onPress={onPress}
      onPressIn={() => {
        if (haptic && !disabled) tapLight();
        onPressIn();
      }}
      onPressOut={onPressOut}
      disabled={disabled}
      hitSlop={hitSlop}
      accessible
      accessibilityRole={accessibilityRole}
      accessibilityLabel={accessibilityLabel}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: !!disabled }}
    >
      <Animated.View style={[{ opacity: disabled ? 0.45 : 1, transform: [{ scale }] }, style]}>
        {children}
      </Animated.View>
    </Pressable>
  );
}
