import React from "react";
import { Animated, Pressable, ViewStyle, StyleProp } from "react-native";
import { usePressScale } from "../anim";

/**
 * Tappable — the one touch primitive. A spring scale-down on press gives every
 * interactive surface the same tactile feel. Drop-in for TouchableOpacity.
 */
export function Tappable({
  children,
  onPress,
  disabled,
  style,
  scaleTo = 0.96,
  hitSlop = 6,
}: {
  children: React.ReactNode;
  onPress?: () => void;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  scaleTo?: number;
  hitSlop?: number;
}) {
  const { scale, onPressIn, onPressOut } = usePressScale(scaleTo);
  return (
    <Pressable
      onPress={onPress}
      onPressIn={onPressIn}
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
