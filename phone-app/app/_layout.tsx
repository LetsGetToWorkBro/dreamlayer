import React from "react";
import { Tabs } from "expo-router";
import { Platform, View, StyleSheet } from "react-native";
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
  if (!loaded) return <View style={{ flex: 1, backgroundColor: platinum.desk }} />;

  // hide the tab bar on the first-run tour and the boot redirect
  const noBar = { tabBarStyle: { display: "none" as const } };

  return (
    <Tabs
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
      <Tabs.Screen
        name="brain"
        options={{ title: t("tabs.brain"), tabBarIcon: ({ color }) => <TabIcon name="brain" color={color} /> }}
      />
      <Tabs.Screen
        name="now"
        options={{ title: t("tabs.now"), tabBarIcon: ({ color }) => <TabIcon name="now" color={color} /> }}
      />
      <Tabs.Screen
        name="look"
        options={{ title: t("tabs.look"), tabBarIcon: ({ color }) => <TabIcon name="look" color={color} /> }}
      />
      <Tabs.Screen
        name="messages"
        options={{ title: t("tabs.messages"), tabBarIcon: ({ color }) => <TabIcon name="messages" color={color} /> }}
      />
      <Tabs.Screen
        name="people"
        options={{ title: t("tabs.people"), tabBarIcon: ({ color }) => <TabIcon name="people" color={color} /> }}
      />
      <Tabs.Screen
        name="memories"
        options={{ title: t("tabs.memories"), tabBarIcon: ({ color }) => <TabIcon name="memories" color={color} /> }}
      />
      <Tabs.Screen
        name="settings"
        options={{ title: t("tabs.settings"), tabBarIcon: ({ color }) => <TabIcon name="settings" color={color} /> }}
      />
      {/* reachable from Settings → Labs, kept out of the bar */}
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
  );
}

const s = StyleSheet.create({
  // the hard black top rule of the control strip
  topFrame: { position: "absolute", top: 0, left: 0, right: 0, height: 1, backgroundColor: platinum.frame },
  // the white highlight just under it — the raised bevel
  topHi: { position: "absolute", top: 1, left: 0, right: 0, height: 1, backgroundColor: platinum.hi },
});
