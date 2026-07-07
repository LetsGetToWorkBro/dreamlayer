import React from "react";
import { View, useWindowDimensions, StyleSheet } from "react-native";
import Svg, { Defs, RadialGradient, Stop, Rect } from "react-native-svg";
import { colors } from "../theme/colors";

/**
 * CineBackdrop — the cinematic depth layer behind every screen: a soft teal
 * glow spilling from the top and a gentle vignette at the edges, so the pure
 * black gains the same luminous depth as the Mac panel. Inert (pointer-through)
 * and cheap (two static gradient rects).
 */
export function CineBackdrop() {
  const { width, height } = useWindowDimensions();
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      <Svg width={width} height={height}>
        <Defs>
          <RadialGradient id="glow" cx="50%" cy="0%" rx="80%" ry="52%">
            <Stop offset="0" stopColor={colors.accentMemory} stopOpacity={0.16} />
            <Stop offset="1" stopColor={colors.accentMemory} stopOpacity={0} />
          </RadialGradient>
          <RadialGradient id="vig" cx="50%" cy="40%" rx="75%" ry="70%">
            <Stop offset="0.5" stopColor="#000000" stopOpacity={0} />
            <Stop offset="1" stopColor="#000000" stopOpacity={0.6} />
          </RadialGradient>
        </Defs>
        <Rect x={0} y={0} width={width} height={height} fill="url(#glow)" />
        <Rect x={0} y={0} width={width} height={height} fill="url(#vig)" />
      </Svg>
    </View>
  );
}
