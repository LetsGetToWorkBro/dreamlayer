import React from "react";
import { Tabs } from "expo-router";
import { Platform, View, Text, Image, Animated, Easing, AccessibilityInfo, StyleSheet } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import {
  useFonts,
  SpaceGrotesk_400Regular,
  SpaceGrotesk_500Medium,
  SpaceGrotesk_700Bold,
} from "@expo-google-fonts/space-grotesk";
import { colors, platinum } from "../src/ui/theme/colors";
import { fonts } from "../src/ui/theme/fonts";
import { TabIcon } from "../src/ui/components/TabIcon";
import { CineBackdrop } from "../src/ui/components/CineBackdrop";
import { useBrainStore } from "../src/state/useBrainStore";
import { usePackStore } from "../src/state/usePackStore";
import { t } from "../src/i18n";

/** The Platinum control strip under the tabs — a light beveled bar: a hard black
 * top rule, a white highlight under it, and the top-lit platinum gradient face. */
function TabBarBackground() {
  return (
    <View style={StyleSheet.absoluteFill}>
      <LinearGradient
        colors={[platinum.faceHi, platinum.face, platinum.face2]}
        start={{ x: 0, y: 0 }}
        end={{ x: 0, y: 1 }}
        style={StyleSheet.absoluteFill}
      />
      <View style={s.topFrame} />
      <View style={s.topHi} />
    </View>
  );
}

/* ------------------------------------------------------------------ boot --
 * The Mac OS 8.1 boot moment, sized for a phone: the desktop, a beveled
 * "Welcome to DreamLayer." panel with the little-Mac mark, and an extensions-
 * style progress bar that fills — then the whole thing zooms away into the
 * app. Plays once per cold launch; reduce-motion skips it entirely. */
const EASE = Easing.bezier(0.16, 1, 0.3, 1);
const BOOT_BAR_W = 176;
let bootPlayed = false;

function BootScreen({ onDone }: { onDone: () => void }) {
  const fade = React.useRef(new Animated.Value(1)).current;
  const zoom = React.useRef(new Animated.Value(1)).current;
  const fill = React.useRef(new Animated.Value(0)).current;

  React.useEffect(() => {
    let alive = true;
    AccessibilityInfo.isReduceMotionEnabled?.()
      .then((r) => { if (r && alive) onDone(); })
      .catch(() => {});
    Animated.timing(fill, { toValue: 1, duration: 950, delay: 120, easing: EASE, useNativeDriver: true }).start();
    const tmr = setTimeout(() => {
      Animated.parallel([
        Animated.timing(fade, { toValue: 0, duration: 300, easing: EASE, useNativeDriver: true }),
        Animated.timing(zoom, { toValue: 1.08, duration: 300, easing: EASE, useNativeDriver: true }),
      ]).start(() => onDone());
    }, 1250);
    return () => { alive = false; clearTimeout(tmr); };
  }, []);

  const barX = fill.interpolate({ inputRange: [0, 1], outputRange: [-BOOT_BAR_W, 0] });
  return (
    <Animated.View style={[StyleSheet.absoluteFill, s.boot, { opacity: fade, transform: [{ scale: zoom }] }]}>
      <CineBackdrop />
      <View style={s.bootPanel}>
        <Image source={require("../assets/splash.png")} style={s.bootMac} resizeMode="contain" />
        <Text style={s.bootTitle}>Welcome to DreamLayer.</Text>
        <View style={s.bootTrack}>
          <Animated.View style={[s.bootFill, { transform: [{ translateX: barX }] }]} />
        </View>
      </View>
    </Animated.View>
  );
}

export default function Layout() {
  const [loaded] = useFonts({
    SpaceGrotesk_400Regular,
    SpaceGrotesk_500Medium,
    SpaceGrotesk_700Bold,
    // the Mac OS 8.1 system face — titles, chrome, tab labels
    ChicagoFLF: require("../assets/fonts/ChicagoFLF.ttf"),
  });
  const hydrate = useBrainStore((s) => s.hydrate);
  const hydrated = useBrainStore((s) => s.hydrated);
  // apply the chosen earcon/haptic pack (B8) app-wide on launch
  React.useEffect(() => {
    usePackStore.getState().hydrate();
  }, []);
  // BLE: attach the native transport once at startup (P2-14). On a dev build
  // react-native-ble-plx is present, makeBlePlxTransport() returns a real
  // transport, and the glasses store drives the radio; in Expo Go / tests it
  // returns null and everything stays inert — demo behaviour unchanged.
  React.useEffect(() => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const { makeBlePlxTransport } = require("../src/ble/transport.blePlx");
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const { useGlassesStore } = require("../src/state/useGlassesStore");
      const transport = makeBlePlxTransport();
      if (transport) useGlassesStore.getState().attachTransport(transport);
    } catch {
      /* no native BLE module in this runtime — the link stays demo-only */
    }
  }, []);
  React.useEffect(() => {
    if (!hydrated) {
      hydrate();
      // offline read-caches: show what you knew (and when) before any network
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      require("../src/state/useMemoryStore").useMemoryStore.getState().hydrateCache();
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      require("../src/state/usePeopleStore").usePeopleStore.getState().hydrateCache();
    }
  }, [hydrated, hydrate]);
  const [booted, setBooted] = React.useState(bootPlayed);
  if (!loaded) return <View style={{ flex: 1, backgroundColor: platinum.desk }} />;

  // hide the tab bar on the first-run tour and the boot redirect
  const noBar = { tabBarStyle: { display: "none" as const } };

  return (
    <View style={{ flex: 1 }}>
    <Tabs
      // drill-ins (Brain -> Preferences/Labs, Now -> Look) live off the bar as
      // hidden tabs; "history" back-behavior makes the back control return to
      // the tab you came from, not jump to the first tab.
      backBehavior="history"
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.accentMemory,
        tabBarInactiveTintColor: colors.textSecondary,
        tabBarBackground: () => <TabBarBackground />,
        tabBarStyle: {
          position: "absolute",
          backgroundColor: "transparent",
          borderTopWidth: 0,
          elevation: 0,
          height: Platform.OS === "ios" ? 90 : 78,
          paddingTop: 10,
          paddingBottom: Platform.OS === "ios" ? 30 : 16,
        },
        // Chicago is too wide for a 7-up label row (and truncates the longer
        // localized strings) — the control strip uses the narrower reading face,
        // the way the Mac used Geneva for small labels and Chicago for titles.
        tabBarLabelStyle: { fontFamily: fonts.medium, fontSize: 9, letterSpacing: 0 },
        tabBarItemStyle: { paddingTop: 3, paddingBottom: 2, paddingHorizontal: 0 },
        tabBarAllowFontScaling: false,
        sceneStyle: { backgroundColor: platinum.desk },
      }}
    >
      {/* The five destinations. iOS convention is <=5 in the tab bar; the rest
          live inside the Brain hub and the Now home, one tap away. Order:
          the home first, the control hub last. */}
      <Tabs.Screen
        name="now"
        options={{ title: t("tabs.now"), tabBarIcon: ({ color }) => <TabIcon name="now" color={color} /> }}
      />
      <Tabs.Screen
        name="memories"
        options={{ title: t("tabs.memories"), tabBarIcon: ({ color }) => <TabIcon name="memories" color={color} /> }}
      />
      <Tabs.Screen
        name="people"
        options={{ title: t("tabs.people"), tabBarIcon: ({ color }) => <TabIcon name="people" color={color} /> }}
      />
      <Tabs.Screen
        name="messages"
        options={{ title: t("tabs.messages"), tabBarIcon: ({ color }) => <TabIcon name="messages" color={color} /> }}
      />
      <Tabs.Screen
        name="brain"
        options={{ title: t("tabs.brain"), tabBarIcon: ({ color }) => <TabIcon name="brain" color={color} /> }}
      />
      {/* off the bar — Look is a quick action on Now; Settings folded into the
          Brain hub; the rest are reachable from the hub's Labs list */}
      <Tabs.Screen name="look" options={{ href: null }} />
      <Tabs.Screen name="settings" options={{ href: null }} />
      <Tabs.Screen name="labs" options={{ href: null }} />
      <Tabs.Screen name="brief" options={{ href: null }} />
      <Tabs.Screen name="plugins" options={{ href: null }} />
      <Tabs.Screen name="capabilities" options={{ href: null }} />
      <Tabs.Screen name="vitals" options={{ href: null }} />
      <Tabs.Screen name="cloud" options={{ href: null }} />
      <Tabs.Screen name="brain-tiers" options={{ href: null }} />
      <Tabs.Screen name="waypath" options={{ href: null }} />
      <Tabs.Screen name="packs" options={{ href: null }} />
      <Tabs.Screen name="rewind" options={{ href: null }} />
      <Tabs.Screen name="saga" options={{ href: null }} />
      <Tabs.Screen name="profile" options={{ href: null }} />
      <Tabs.Screen name="rehearsal" options={{ href: null }} />
      <Tabs.Screen name="ember" options={{ href: null }} />
      <Tabs.Screen name="confluence" options={{ href: null }} />
      <Tabs.Screen name="onboarding" options={{ href: null, ...noBar }} />
      <Tabs.Screen name="index" options={{ href: null, ...noBar }} />
    </Tabs>
    {!booted ? <BootScreen onDone={() => { bootPlayed = true; setBooted(true); }} /> : null}
    </View>
  );
}

const s = StyleSheet.create({
  // the hard black top rule of the control strip
  topFrame: { position: "absolute", top: 0, left: 0, right: 0, height: 1, backgroundColor: platinum.frame },
  // the white highlight just under it — the raised bevel
  topHi: { position: "absolute", top: 1, left: 0, right: 0, height: 1, backgroundColor: platinum.hi },
  // ------- boot moment -------
  boot: { alignItems: "center", justifyContent: "center", backgroundColor: platinum.desk, zIndex: 10 },
  bootPanel: {
    alignItems: "center",
    backgroundColor: platinum.face,
    borderRadius: 12,
    borderTopColor: platinum.hi,
    borderLeftColor: platinum.hi,
    borderBottomColor: platinum.sh,
    borderRightColor: platinum.sh,
    borderWidth: 1.5,
    paddingVertical: 28,
    paddingHorizontal: 32,
    // the hard Platinum drop shadow
    shadowColor: "#000000",
    shadowOffset: { width: 3, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 0,
    elevation: 6,
  },
  bootMac: { width: 96, height: 96, marginBottom: 14 },
  bootTitle: { fontFamily: fonts.chicago, fontSize: 19, color: platinum.ink, marginBottom: 20 },
  // the extensions-march progress bar: a white inset well, teal fill sliding in
  bootTrack: {
    width: BOOT_BAR_W,
    height: 11,
    backgroundColor: platinum.well,
    borderWidth: 1,
    borderColor: platinum.frame,
    borderRadius: 3,
    overflow: "hidden",
  },
  bootFill: { width: BOOT_BAR_W, height: "100%", backgroundColor: colors.accentMemory },
});
