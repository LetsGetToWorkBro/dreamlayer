import React from "react";
import { View, StyleSheet, StyleProp, ViewStyle } from "react-native";
import Svg, { Defs, Pattern, Rect, Line } from "react-native-svg";
import { platinum } from "../theme/colors";

/**
 * Pinstripe — the Mac OS 8.1 active-title-bar fill: crisp horizontal hairlines,
 * light over dark, 2px pitch. Drawn as a tiled SVG pattern so it stays 1px-sharp
 * at any density. Fills its parent; pointer-through. The window title and its
 * boxes render on top.
 */
export function Pinstripe({ style }: { style?: StyleProp<ViewStyle> }) {
  return (
    <View pointerEvents="none" style={[StyleSheet.absoluteFill, style]}>
      <Svg width="100%" height="100%">
        <Defs>
          <Pattern id="tstripe" width={2} height={2} patternUnits="userSpaceOnUse">
            <Rect x={0} y={0} width={2} height={2} fill={platinum.stripe[1]} />
            <Line x1={0} y1={0.5} x2={2} y2={0.5} stroke={platinum.stripe[0]} strokeWidth={1} />
            <Line x1={0} y1={1.5} x2={2} y2={1.5} stroke={platinum.stripe[2]} strokeWidth={1} strokeOpacity={0.85} />
          </Pattern>
        </Defs>
        <Rect x={0} y={0} width="100%" height="100%" fill="url(#tstripe)" />
      </Svg>
    </View>
  );
}
