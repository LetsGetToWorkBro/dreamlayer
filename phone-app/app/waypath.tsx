import React, { useEffect, useState } from "react";
import { View, Text, TextInput, StyleSheet } from "react-native";

import { useWaypathStore } from "../src/state/useWaypathStore";
import { type Dot, type LatLng } from "../src/nav/waypath";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { PrimaryButton } from "../src/ui/components/PrimaryButton";
import { Tappable } from "../src/ui/components/Tappable";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { space } from "../src/ui/theme/spacing";

// expo-location is optional (absent in Expo Go / tests) — guard it.
let Location: any = null;
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  Location = require("expo-location");
} catch {
  Location = null;
}

export function parseLatLng(s: string): LatLng | null {
  const m = (s || "").split(",").map((x) => parseFloat(x.trim()));
  if (m.length === 2 && Number.isFinite(m[0]) && Number.isFinite(m[1])) {
    return { lat: m[0] as number, lng: m[1] as number };
  }
  return null;
}

const D = 220;
const R = D / 2;

/** The whole lens: one dot leaning where to go, or the arrival check. */
function Ring({ dot }: { dot: Dot | null }) {
  let x = R;
  let y = R;
  if (dot && !dot.arrived) {
    const rad = (dot.angle * Math.PI) / 180; // 0 = dead ahead (top of the ring)
    x = R + (R - 16) * Math.sin(rad);
    y = R - (R - 16) * Math.cos(rad);
  }
  return (
    <View style={st.ringWrap} accessibilityLabel="waypath-ring">
      <View style={st.ring} />
      {dot?.arrived ? (
        <Text style={st.arrived}>✓ arrived</Text>
      ) : dot ? (
        <View style={[st.dot, { left: x - 8, top: y - 8 }]} />
      ) : null}
    </View>
  );
}

export default function Waypath() {
  const { route, dot, status, error, navigateTo, update, clear } = useWaypathStore();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  async function useMyLocation() {
    if (!Location?.getCurrentPositionAsync) return;
    try {
      await Location.requestForegroundPermissionsAsync?.();
      const loc = await Location.getCurrentPositionAsync({});
      setFrom(`${loc.coords.latitude.toFixed(5)}, ${loc.coords.longitude.toFixed(5)}`);
    } catch {
      /* no-op — leave the field for manual entry */
    }
  }

  function go() {
    const a = parseLatLng(from);
    const b = parseLatLng(to);
    if (a && b) navigateTo(a, b);
  }

  // Live GPS while navigating (guarded — no-op without expo-location).
  useEffect(() => {
    if (status !== "navigating" || !Location?.watchPositionAsync) return;
    let sub: any;
    let hsub: any;
    let heading = 0;
    (async () => {
      try {
        await Location.requestForegroundPermissionsAsync?.();
        hsub = await Location.watchHeadingAsync?.((h: any) => {
          heading = h.trueHeading ?? h.magHeading ?? 0;
        });
        sub = await Location.watchPositionAsync?.(
          { accuracy: 5, distanceInterval: 5 },
          (loc: any) => update({ lat: loc.coords.latitude, lng: loc.coords.longitude }, heading),
        );
      } catch {
        /* no-op */
      }
    })();
    return () => {
      sub?.remove?.();
      hsub?.remove?.();
    };
  }, [status, update]);

  return (
    <Screen>
      <ScreenHeader title="Waypath" subtitle="One point of light — no map, no maps app" />
      <TextInput
        style={st.input}
        placeholder="From — lat, lng  (or use my location)"
        placeholderTextColor={colors.textSecondary}
        value={from}
        onChangeText={setFrom}
      />
      <Tappable onPress={useMyLocation}>
        <Text style={st.link}>📍 Use my location</Text>
      </Tappable>
      <TextInput
        style={st.input}
        placeholder="To — lat, lng"
        placeholderTextColor={colors.textSecondary}
        value={to}
        onChangeText={setTo}
      />
      <PrimaryButton label={route.length ? "Re-route" : "Navigate"} onPress={go} />

      <Ring dot={dot} />

      <Text style={st.status}>
        {status === "routing" && "finding a route…"}
        {status === "error" && `couldn't route: ${error}`}
        {status === "navigating" && dot && `${dot.distanceM} m to the next turn`}
        {status === "arrived" && "you're here."}
        {status === "idle" && "set a destination to begin."}
      </Text>
      {route.length ? (
        <Tappable onPress={clear}>
          <Text style={st.link}>Clear route</Text>
        </Tappable>
      ) : null}
    </Screen>
  );
}

const st = StyleSheet.create({
  input: {
    backgroundColor: colors.textPrimary + "0D",
    borderColor: colors.textSecondary + "44",
    borderWidth: 1,
    borderRadius: 12,
    color: colors.textPrimary,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
    marginBottom: space.sm,
    fontSize: 16,
  },
  link: { color: colors.accentMemory, marginBottom: space.md, ...typography.body },
  ringWrap: { width: D, height: D, alignSelf: "center", marginVertical: space.xl },
  ring: {
    position: "absolute",
    width: D,
    height: D,
    borderRadius: R,
    borderWidth: 1,
    borderColor: colors.textSecondary,
    opacity: 0.35,
  },
  dot: {
    position: "absolute",
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: colors.accentMemory,
  },
  arrived: {
    position: "absolute",
    width: D,
    textAlign: "center",
    top: R - 14,
    color: colors.accentSuccess,
    fontSize: 22,
  },
  status: { textAlign: "center", color: colors.textSecondary, ...typography.body },
});
