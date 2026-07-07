import { Tabs } from "expo-router";
import { Platform, View, StyleSheet } from "react-native";
import { BlurView } from "expo-blur";
import {
  useFonts,
  SpaceGrotesk_400Regular,
  SpaceGrotesk_500Medium,
  SpaceGrotesk_700Bold,
} from "@expo-google-fonts/space-grotesk";
import { colors } from "../src/ui/theme/colors";
import { fonts } from "../src/ui/theme/fonts";
import { TabIcon } from "../src/ui/components/TabIcon";

/** Frosted glass under the tab bar — a blur on native, a translucent wash on web. */
function TabBarBackground() {
  return (
    <View style={StyleSheet.absoluteFill}>
      {Platform.OS === "web" ? (
        <View style={[StyleSheet.absoluteFill, { backgroundColor: "rgba(8,13,15,0.86)" }]} />
      ) : (
        <BlurView intensity={40} tint="dark" style={StyleSheet.absoluteFill} />
      )}
      <View style={s.hairline} />
    </View>
  );
}

export default function Layout() {
  const [loaded] = useFonts({
    SpaceGrotesk_400Regular,
    SpaceGrotesk_500Medium,
    SpaceGrotesk_700Bold,
  });
  if (!loaded) return <View style={{ flex: 1, backgroundColor: colors.background }} />;

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
          paddingTop: 9,
          paddingBottom: Platform.OS === "ios" ? 30 : 16,
        },
        tabBarLabelStyle: { fontFamily: fonts.medium, fontSize: 10.5, letterSpacing: 0.2 },
        tabBarItemStyle: { paddingVertical: 2 },
        sceneStyle: { backgroundColor: colors.background },
      }}
    >
      <Tabs.Screen
        name="brain"
        options={{ title: "Brain", tabBarIcon: ({ color }) => <TabIcon name="brain" color={color} /> }}
      />
      <Tabs.Screen
        name="now"
        options={{ title: "Now", tabBarIcon: ({ color }) => <TabIcon name="now" color={color} /> }}
      />
      <Tabs.Screen
        name="messages"
        options={{ title: "Messages", tabBarIcon: ({ color }) => <TabIcon name="messages" color={color} /> }}
      />
      <Tabs.Screen
        name="people"
        options={{ title: "People", tabBarIcon: ({ color }) => <TabIcon name="people" color={color} /> }}
      />
      <Tabs.Screen
        name="memories"
        options={{ title: "Memories", tabBarIcon: ({ color }) => <TabIcon name="memories" color={color} /> }}
      />
      <Tabs.Screen
        name="settings"
        options={{ title: "Settings", tabBarIcon: ({ color }) => <TabIcon name="settings" color={color} /> }}
      />
      {/* reachable from Settings → Labs, kept out of the bar */}
      <Tabs.Screen name="brief" options={{ href: null }} />
      <Tabs.Screen name="plugins" options={{ href: null }} />
      <Tabs.Screen name="rewind" options={{ href: null }} />
      <Tabs.Screen name="saga" options={{ href: null }} />
      <Tabs.Screen name="profile" options={{ href: null }} />
      <Tabs.Screen name="rehearsal" options={{ href: null }} />
      <Tabs.Screen name="confluence" options={{ href: null }} />
      <Tabs.Screen name="onboarding" options={{ href: null }} />
      <Tabs.Screen name="index" options={{ href: null }} />
    </Tabs>
  );
}

const s = StyleSheet.create({
  hairline: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    height: 1,
    backgroundColor: "rgba(140,190,190,0.12)",
  },
});
