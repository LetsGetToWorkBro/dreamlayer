import React from "react";
import { Animated, Pressable, ViewStyle, StyleProp } from "react-native";
import { usePressScale } from "../anim";
import { tapLight } from "../../services/haptics";

/**
 * Tappable — the one touch primitive. A spring scale-down plus a light haptic
 * tick on press gives every interactive surface the same tactile feel. Drop-in
 * for TouchableOpacity. Pass haptic={false} for surfaces that shouldn't buzz.
 */
export function Tappable({
  children,
  onPress,
  disabled,
  style,
  scaleTo = 0.96,
  hitSlop = 6,
  haptic = true,
}: {
  children: React.ReactNode;
  onPress?: () => void;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  scaleTo?: number;
  hitSlop?: number;
  haptic?: boolean;
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
    >
      <Animated.View style={[{ opacity: disabled ? 0.45 : 1, transform: [{ scale }] }, style]}>
        {children}
      </Animated.View>
    </Pressable>
  );
}
