import React, { useEffect, useRef } from "react";
import {
  View, Text, SafeAreaView, Animated, Easing,
  StyleSheet, Dimensions, TouchableOpacity,
} from "react-native";
import { useRouter } from "expo-router";
import { useOnboardingStore } from "../src/state/useOnboardingStore";
import { useHaloStore }        from "../src/state/useHaloStore";
import { useBrainStore }       from "../src/state/useBrainStore";
import { ONBOARDING_STEPS }    from "../src/services/OnboardingService";
import { tapMedium, tapSuccess, tapWarn } from "../src/services/haptics";
import { colors }      from "../src/ui/theme/colors";
import { typography }  from "../src/ui/theme/typography";
import { OnboardingDots }   from "../src/ui/components/OnboardingDots";
import { PrimaryButton }    from "../src/ui/components/PrimaryButton";
import { EyebrowLabel }     from "../src/ui/components/EyebrowLabel";
import { HaloPairingRing }  from "../src/ui/components/HaloPairingRing";
import { QrScanner }        from "../src/ui/components/QrScanner";

const { width: SW } = Dimensions.get("window");
const ACCENT_MAP = {
  memory:    colors.accentMemory,
  attention: colors.accentAttention,
  success:   colors.accentSuccess,
};

export default function Onboarding() {
  const router = useRouter();
  const { stepIndex, step, advance, complete } = useOnboardingStore();
  const { connect, connected } = useHaloStore();
  const pairFromCode = useBrainStore((s) => s.pairFromCode);
  const [scanOpen, setScanOpen] = React.useState(false);
  const fadeAnim  = useRef(new Animated.Value(0)).current;
  const slideAnim = useRef(new Animated.Value(18)).current;

  useEffect(() => {
    fadeAnim.setValue(0); slideAnim.setValue(18);
    Animated.parallel([
      Animated.timing(fadeAnim,  { toValue: 1, duration: 420, easing: Easing.out(Easing.cubic), useNativeDriver: true }),
      Animated.timing(slideAnim, { toValue: 0, duration: 420, easing: Easing.out(Easing.cubic), useNativeDriver: true }),
    ]).start();
  }, [stepIndex]);

  const isPairStep = step.id === "pair";
  const accent = ACCENT_MAP[step.accent] ?? colors.accentMemory;

  const finish = () => { tapSuccess(); complete(); router.replace("/brain"); };

  const handleCta = async () => {
    if (isPairStep) {
      tapMedium();
      try { await connect(); } catch (_) {}
      finish();
    } else { tapMedium(); advance(); }
  };

  const onScanned = (code: string) => {
    setScanOpen(false);
    try {
      const r = pairFromCode(code.trim());
      if (r.brain || r.glasses) { finish(); return; }
      tapWarn();
    } catch { tapWarn(); }
  };

  return (
    <SafeAreaView style={styles.safe}>
      {!isPairStep && (
        <TouchableOpacity style={styles.skip} onPress={() => { complete(); router.replace("/brain"); }}>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>Skip</Text>
        </TouchableOpacity>
      )}
      <View style={styles.content}>
        <View style={styles.hero}>
          {isPairStep
            ? <HaloPairingRing scanning={!connected} />
            : <StepGlyph stepId={step.id} accent={accent} />}
        </View>
        <Animated.View style={[styles.copy, { opacity: fadeAnim, transform: [{ translateY: slideAnim }] }]}>
          {step.eyebrow && <EyebrowLabel label={step.eyebrow} accent={accent} />}
          <Text style={[typography.headline, { color: colors.textPrimary, marginBottom: 14 }]}>{step.title}</Text>
          <Text style={[typography.body, { color: colors.textSecondary, textAlign: "center", maxWidth: 300 }]}>{step.body}</Text>
        </Animated.View>
      </View>
      <View style={styles.bottom}>
        <OnboardingDots total={ONBOARDING_STEPS.length} current={stepIndex} />
        <PrimaryButton label={step.cta} onPress={handleCta} accent={step.accent} style={{ marginTop: 28, width: SW - 64 }} />
        {isPairStep && (
          <TouchableOpacity style={styles.scanLink} onPress={() => { tapMedium(); setScanOpen(true); }}>
            <Text style={[typography.caption, { color: accent }]}>Have a Mac mini? Scan its pairing QR</Text>
          </TouchableOpacity>
        )}
      </View>
      <QrScanner visible={scanOpen} onClose={() => setScanOpen(false)} onScan={onScanned} />
    </SafeAreaView>
  );
}

function StepGlyph({ stepId, accent }: { stepId: string; accent: string }) {
  const GLYPHS: Record<string, string> = { welcome: "\u25C9", how: "\u25CE", recall: "\u2318", privacy: "\u23F8" };
  return (
    <View style={[glyphStyles.shell, { borderColor: accent }]}>
      <Text style={[glyphStyles.symbol, { color: accent }]}>{GLYPHS[stepId] ?? "\u25C9"}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe:    { flex: 1, backgroundColor: colors.background },
  skip:    { position: "absolute", top: 56, right: 24, zIndex: 10 },
  content: { flex: 1, alignItems: "center", justifyContent: "center", gap: 40, paddingHorizontal: 32 },
  hero:    { alignItems: "center", justifyContent: "center", height: 200 },
  copy:    { alignItems: "center", gap: 4 },
  bottom:  { paddingBottom: 48, alignItems: "center", paddingHorizontal: 32 },
  scanLink: { marginTop: 18, paddingVertical: 6 },
});
const glyphStyles = StyleSheet.create({
  shell:  { width: 120, height: 120, borderRadius: 60, borderWidth: 1.5, alignItems: "center", justifyContent: "center" },
  symbol: { fontSize: 48 },
});
