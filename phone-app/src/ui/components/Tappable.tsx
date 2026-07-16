import React from "react";
import { Animated, Pressable, ViewStyle, StyleProp, AccessibilityRole } from "react-native";
import { usePressScale } from "../anim";
import { tapLight } from "../../services/haptics";

/**
 * Tappable — the one touch primitive. A spring scale-down plus a light haptic
 * tick on press gives every interactive surface the same tactile feel. Drop-in
 * for TouchableOpacity. Pass haptic={false} for surfaces that shouldn't buzz.
 *
 * Children may be a render function `(pressed) => node` — that's how the
 * Platinum push buttons invert their bevel and go dark while held, the way a
 * real Mac OS 8 button presses IN instead of merely shrinking.
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
  containerStyle,
  scaleTo = 0.96,
  hitSlop = 6,
  haptic = true,
  accessibilityLabel,
  accessibilityHint,
  accessibilityRole = "button",
}: {
  children: React.ReactNode | ((pressed: boolean) => React.ReactNode);
  onPress?: () => void;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  /** style for the OUTER Pressable — the node that actually sits in the parent
   * layout. Flex weights (`flex: 1` in a row of equal tiles) must go here;
   * on `style` they land on the inner view and the Pressable just hugs. */
  containerStyle?: StyleProp<ViewStyle>;
  scaleTo?: number;
  hitSlop?: number;
  haptic?: boolean;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  accessibilityRole?: AccessibilityRole;
}) {
  const { scale, onPressIn, onPressOut } = usePressScale(scaleTo);
  const [pressed, setPressed] = React.useState(false);
  return (
    <Pressable
      style={containerStyle}
      onPress={onPress}
      onPressIn={() => {
        if (haptic && !disabled) tapLight();
        if (!disabled) setPressed(true);
        onPressIn();
      }}
      onPressOut={() => {
        setPressed(false);
        onPressOut();
      }}
      disabled={disabled}
      hitSlop={hitSlop}
      accessible
      accessibilityRole={accessibilityRole}
      accessibilityLabel={accessibilityLabel}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: !!disabled }}
    >
      <Animated.View style={[{ opacity: disabled ? 0.45 : 1, transform: [{ scale }] }, style]}>
        {typeof children === "function" ? children(pressed) : children}
      </Animated.View>
    </Pressable>
  );
}
