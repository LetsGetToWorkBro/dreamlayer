import React from "react";
import Svg, { Path, Circle } from "react-native-svg";

/**
 * TabIcon — crisp line icons for the tab bar, drawn in the active/inactive tint
 * expo-router passes. One visual language with the Mac panel's SVG nav icons.
 */
export function TabIcon({ name, color, size = 23 }: { name: string; color: string; size?: number }) {
  const p = { stroke: color, strokeWidth: 1.7, fill: "none", strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {name === "brain" && (
        <>
          <Circle cx={12} cy={12} r={8} {...p} />
          <Circle cx={12} cy={12} r={3} fill={color} stroke="none" />
        </>
      )}
      {name === "now" && <Path d="M2 12h4l2.5-6 4 12 2.5-6H21" {...p} />}
      {name === "messages" && <Path d="M4 5h16v11H9l-4 4z" {...p} />}
      {name === "people" && (
        <>
          <Circle cx={9} cy={8} r={3} {...p} />
          <Path d="M3.5 19a5.5 5.5 0 0 1 11 0" {...p} />
          <Path d="M16 6a3 3 0 0 1 0 6M17 19a6 6 0 0 0-1.2-3.6" {...p} />
        </>
      )}
      {name === "memories" && (
        <>
          <Path d="M12 3l9 5-9 5-9-5z" {...p} />
          <Path d="M3 13l9 5 9-5" {...p} />
        </>
      )}
      {name === "settings" && (
        <>
          <Path d="M4 8h9M17 8h3M4 16h3M11 16h9" {...p} />
          <Circle cx={15} cy={8} r={2.3} {...p} />
          <Circle cx={9} cy={16} r={2.3} {...p} />
        </>
      )}
    </Svg>
  );
}
