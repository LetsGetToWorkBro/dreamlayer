/**
 * Look — the deliberate camera tier.
 *
 * Pulling out the phone IS consent and intent: the sensor is 10x the Halo
 * snapshot and there's no BLE tax. One photo rides the exact pipeline the
 * glasses use (POST /dreamlayer/brain/explain), so Juno's whole vision
 * stack — local model first, cloud only when opted in — is real and
 * testable today, before the glasses' camera path exists.
 *
 * The camera loads lazily (same pattern as QrScanner): no module or no
 * permission degrades to an explanation, never a crash.
 */
import React from "react";
import { ActivityIndicator, Text, View, StyleSheet } from "react-native";
import { useBrainStore, AskResult } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { PrimaryButton } from "../src/ui/components/PrimaryButton";
import { play } from "../src/services/haptics";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";

type CameraKit = {
  CameraView: any;
  useCameraPermissions: any;
} | null;

function loadCamera(): CameraKit {
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const m = require("expo-camera");
    if (m?.CameraView && m?.useCameraPermissions) {
      return { CameraView: m.CameraView, useCameraPermissions: m.useCameraPermissions };
    }
  } catch {
    /* camera module unavailable (web/tests) */
  }
  return null;
}

const kit = loadCamera();

function LiveLook() {
  const explain = useBrainStore((s) => s.explain);
  const [permission, requestPermission] = kit!.useCameraPermissions();
  const camRef = React.useRef<any>(null);
  const [busy, setBusy] = React.useState(false);
  const [answer, setAnswer] = React.useState<AskResult>(null);

  if (!permission?.granted) {
    return (
      <View style={{ gap: space.md }}>
        <EmptyState title="Camera permission" hint="Look needs the camera to see what you see." />
        <PrimaryButton label="Allow camera" onPress={requestPermission} />
      </View>
    );
  }

  const snap = async () => {
    if (busy || !camRef.current) return;
    setBusy(true);
    setAnswer(null);
    play("action");
    try {
      const photo = await camRef.current.takePictureAsync({
        base64: true,
        quality: 0.5,
        skipProcessing: true,
      });
      const res = await explain(photo?.base64 ?? "");
      setAnswer(res);
      play(res && res.text ? "success" : "warn");
    } catch {
      setAnswer({ text: "Couldn't take that picture — try again.", tier: "", sources: [] });
      play("warn");
    } finally {
      setBusy(false);
    }
  };

  const { CameraView } = kit!;
  return (
    <View style={{ flex: 1, gap: space.md }}>
      <View style={s.viewport}>
        <CameraView ref={camRef} style={StyleSheet.absoluteFill} facing="back" />
      </View>
      <PrimaryButton label={busy ? "Looking…" : "Look"} onPress={snap} />
      {busy && <ActivityIndicator color={colors.accentSuccess} />}
      {answer && (
        <Card>
          <Text style={[typography.body, { color: colors.textPrimary }]}>{answer.text}</Text>
          {!!answer.tier && (
            <Text style={[typography.caption, s.tier]}>
              answered by: {answer.tier}
            </Text>
          )}
        </Card>
      )}
    </View>
  );
}

export default function Look() {
  return (
    <Screen>
      <ScreenHeader
        title="Look"
        eyebrow="Juno"
        subtitle="Point the phone at anything — same pipeline as the glasses"
      />
      {kit ? (
        <LiveLook />
      ) : (
        <EmptyState
          title="No camera here"
          hint="Look uses the device camera. On web or in tests this screen stays quiet."
        />
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  viewport: {
    height: 320,
    borderRadius: radius.lg,
    overflow: "hidden",
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.08)",
  },
  tier: { color: colors.textSecondary ?? "#8aa", marginTop: space.sm },
});
