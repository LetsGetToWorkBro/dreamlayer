import { Tabs } from "expo-router";
import { Platform } from "react-native";
import { colors } from "../src/ui/theme/colors";

export default function Layout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.accentMemory,
        tabBarInactiveTintColor: colors.textSecondary,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.borderSubtle,
          borderTopWidth: 1,
          height: Platform.OS === "ios" ? 88 : 64,
          paddingTop: 6,
          paddingBottom: Platform.OS === "ios" ? 28 : 8,
        },
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600", letterSpacing: 0.2 },
        tabBarItemStyle: { paddingVertical: 2 },
        sceneStyle: { backgroundColor: colors.background },
      }}
    >
      <Tabs.Screen name="brain" options={{ title: "Brain" }} />
      <Tabs.Screen name="now" options={{ title: "Now" }} />
      <Tabs.Screen name="messages" options={{ title: "Messages" }} />
      <Tabs.Screen name="memories" options={{ title: "Memories" }} />
      <Tabs.Screen name="settings" options={{ title: "Settings" }} />
      {/* reachable from Settings → Labs, kept out of the bar for a clean 5 */}
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
