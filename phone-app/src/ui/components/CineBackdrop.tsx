import React from "react";
import { View, useWindowDimensions, StyleSheet } from "react-native";
import Svg, { Defs, Pattern, RadialGradient, LinearGradient, Stop, Rect, Line } from "react-native-svg";
import { platinum } from "../theme/colors";

/**
 * CineBackdrop — the Platinum desktop behind every window. The Mac OS 8.1 grey
 * with its faint horizontal pinstripe, a soft light fall from the top-left (the
 * classic "the light comes from up here"), and a gentle vignette so the light
 * cards read as raised panels floating on the desktop. Inert (pointer-through)
 * and cheap (a tiled pattern + two gradient rects).
 */
export function CineBackdrop() {
  const { width, height } = useWindowDimensions();
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      <Svg width={width} height={height}>
        <Defs>
          {/* the desktop pinstripe: a 1px darker line every 3px */}
          <Pattern id="pin" width={3} height={3} patternUnits="userSpaceOnUse">
            <Rect x={0} y={0} width={3} height={3} fill={platinum.desk} />
            <Line x1={0} y1={0.5} x2={3} y2={0.5} stroke={platinum.deskLine} strokeWidth={1} strokeOpacity={0.5} />
          </Pattern>
          {/* light falling from the upper-left, the Platinum convention */}
          <LinearGradient id="sheen" x1="0" y1="0" x2="0.55" y2="1">
            <Stop offset="0" stopColor="#FFFFFF" stopOpacity={0.22} />
            <Stop offset="0.4" stopColor="#FFFFFF" stopOpacity={0} />
          </LinearGradient>
          <RadialGradient id="vig" cx="50%" cy="42%" rx="75%" ry="72%">
            <Stop offset="0.55" stopColor="#000000" stopOpacity={0} />
            <Stop offset="1" stopColor="#3A3E42" stopOpacity={0.28} />
          </RadialGradient>
        </Defs>
        <Rect x={0} y={0} width={width} height={height} fill="url(#pin)" />
        <Rect x={0} y={0} width={width} height={height} fill="url(#sheen)" />
        <Rect x={0} y={0} width={width} height={height} fill="url(#vig)" />
      </Svg>
    </View>
  );
}
