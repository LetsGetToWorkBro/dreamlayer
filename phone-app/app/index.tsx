import React from "react";
import { View } from "react-native";
import { Redirect } from "expo-router";
import { useBrainStore } from "../src/state/useBrainStore";
import { colors } from "../src/ui/theme/colors";

/**
 * Boot route — decide where a cold launch lands once state has hydrated.
 * First run (nothing paired, no demo, tour unseen) → the onboarding tour;
 * everyone else → Now. Renders a black hold until hydrated so we never flash
 * onboarding at a returning user.
 */
export default function Index() {
  const hydrated = useBrainStore((s) => s.hydrated);
  const demoMode = useBrainStore((s) => s.demoMode);
  const paired = useBrainStore((s) => s.macMini.connected || s.glasses.connected);
  const onboardingSeen = useBrainStore((s) => s.onboardingSeen);

  if (!hydrated) return <View style={{ flex: 1, backgroundColor: colors.background }} />;
  const firstRun = !onboardingSeen && !paired && !demoMode;
  return <Redirect href={firstRun ? "/onboarding" : "/now"} />;
}
