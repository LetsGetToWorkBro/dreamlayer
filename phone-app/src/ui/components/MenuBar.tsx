import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import Svg, { Circle } from "react-native-svg";
import { useRouter } from "expo-router";
import { useTheme, makeThemedStyles } from "../theme/useTheme";
import { fonts } from "../theme/fonts";
import { Tappable } from "./Tappable";

/**
 * MenuBar — the Mac OS 8.1 menu bar, pinned to the top of every screen the way
 * it crowns the website and the Mac Brain panel: the six-color ring mark on the
 * left (tap = home), the app name in Chicago, and a live clock on the right.
 * One strip that says "this whole product is one desktop."
 */

/* the six-color ring — same mark6 conic the site draws, as six arc segments */
const MARK6 = ["#61BB46", "#FDB827", "#F5821F", "#E03A3E", "#963D97", "#009DDC"];
function RingMark({ size = 14 }: { size?: number }) {
  const c = size / 2;
  const r = c - 2;
  const circ = 2 * Math.PI * r;
  const seg = circ / 6;
  return (
    <Svg width={size} height={size}>
      {MARK6.map((col, i) => (
        <Circle
          key={col}
          cx={c}
          cy={c}
          r={r}
          stroke={col}
          strokeWidth={3.4}
          fill="none"
          strokeDasharray={`${seg} ${circ - seg}`}
          strokeDashoffset={-i * seg}
        />
      ))}
    </Svg>
  );
}

function fmt(d: Date): string {
  let h = d.getHours();
  const m = d.getMinutes();
  const ap = h >= 12 ? "PM" : "AM";
  h = h % 12;
  if (h === 0) h = 12;
  return `${h}:${m < 10 ? "0" : ""}${m} ${ap}`;
}

export function MenuBar() {
  const s = useS();
  const { platinum, dark } = useTheme();
  const router = useRouter();
  const [time, setTime] = React.useState(() => fmt(new Date()));
  React.useEffect(() => {
    const id = setInterval(() => setTime(fmt(new Date())), 20_000);
    return () => clearInterval(id);
  }, []);
  return (
    <View style={s.bar}>
      <LinearGradient
        colors={[platinum.faceHi, dark ? platinum.face2 : "#D8D8D8"]}
        start={{ x: 0, y: 0 }}
        end={{ x: 0, y: 1 }}
        style={s.fill}
        pointerEvents="none"
      />
      <View style={s.topHi} pointerEvents="none" />
      <Tappable
        onPress={() => router.push("/now")}
        haptic={false}
        scaleTo={0.9}
        accessibilityLabel="DreamLayer home"
        style={s.mark}
      >
        <RingMark />
      </Tappable>
      <Text style={s.name}>DreamLayer</Text>
      <View style={{ flex: 1 }} />
      <Text style={s.clock}>{time}</Text>
    </View>
  );
}

const useS = makeThemedStyles(({ platinum, dark }) => StyleSheet.create({
  bar: {
    height: 28,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 12,
    gap: 9,
    borderBottomWidth: 1,
    borderBottomColor: platinum.frame,
    overflow: "hidden",
  },
  fill: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  topHi: { position: "absolute", top: 0, left: 0, right: 0, height: 1, backgroundColor: platinum.hi },
  mark: { paddingVertical: 6, paddingRight: 1 },
  name: { fontFamily: fonts.chicago, fontSize: 13.5, color: dark ? platinum.ink : "#111111" },
  clock: { fontFamily: fonts.chicago, fontSize: 13.5, color: dark ? platinum.ink : "#111111" },
}));
