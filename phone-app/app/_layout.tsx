import { Tabs } from "expo-router";
import { colors } from "../src/ui/theme/colors";
export default function Layout() {
  return (
    <Tabs screenOptions={{
      tabBarStyle:            { backgroundColor: colors.surface, borderTopColor: colors.borderSubtle },
      tabBarActiveTintColor:  colors.accentMemory,
      tabBarInactiveTintColor:colors.textSecondary,
      headerShown:            false,
    }}>
      <Tabs.Screen name="now"         options={{ title: "Now" }} />
      <Tabs.Screen name="rehearsal"   options={{ title: "Rehearsal" }} />
      <Tabs.Screen name="confluence"  options={{ title: "Confluence" }} />
      <Tabs.Screen name="memories"    options={{ title: "Memories" }} />
      <Tabs.Screen name="settings"    options={{ title: "Settings" }} />
      <Tabs.Screen name="onboarding"  options={{ href: null }} />
      <Tabs.Screen name="index"       options={{ href: null }} />
    </Tabs>
  );
}
