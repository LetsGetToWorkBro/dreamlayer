/**
 * Look — the deliberate camera tier.
 *
 * Pulling out the phone IS consent and intent: the sensor is 10x the Halo
 * snapshot and there's no BLE tax. One photo rides the exact pipeline the
 * glasses use — POST /dreamlayer/brain/look — so the whole World-lens stack
 * (Object Lens / Juno + TasteLens, provider rows and all) runs in the Brain and
 * comes back as the panel the glass would draw. Local model first, cloud only
 * when opted in. Real and testable today, before the glasses' camera path exists.
 *
 * The camera loads lazily (same pattern as QrScanner): no module or no
 * permission degrades to an explanation, never a crash.
 */
import React from "react";
import { ActivityIndicator, Text, View, StyleSheet } from "react-native";
import { useBrainStore, LookPanel } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { PrimaryButton } from "../src/ui/components/PrimaryButton";
import { play } from "../src/services/haptics";
import { t } from "../src/i18n";
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

/** The on-glass panel a look produced — title, subtitle, provider rows, and an
 * honest provenance footer (which providers spoke, how sure the read was). */
export function LensPanel({ panel }: { panel: LookPanel }) {
  if (!panel.ok) {
    const veiled = !!panel.veiled;
    return (
      <Card accent={veiled ? colors.accentAttention : colors.accentMemory}>
        <Text style={[typography.body, { color: veiled ? colors.accentAttention : colors.textSecondary }]}>
          {panel.reason || t("look.nothing")}
        </Text>
      </Card>
    );
  }
  const pct = typeof panel.confidence === "number" ? Math.round(panel.confidence * 100) : null;
  const prov = panel.sources.filter(Boolean).join(", ");
  return (
    <Card>
      {!!panel.title && (
        <Text style={[typography.title, { color: colors.textPrimary }]}>{panel.title}</Text>
      )}
      {!!panel.subtitle && (
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>
          {panel.subtitle}
        </Text>
      )}
      {panel.rows.map((r, i) => (
        <View key={i} style={s.row}>
          <View style={s.rowHead}>
            <Text style={[typography.body, { color: colors.textPrimary, flexShrink: 1 }]}>
              {r.label}
            </Text>
            {!!r.value && (
              <Text style={[typography.body, { color: colors.accentMemory, marginLeft: space.sm }]}>
                {r.value}
              </Text>
            )}
          </View>
          {!!r.detail && (
            <Text style={[typography.caption, { color: colors.textSecondary }]}>{r.detail}</Text>
          )}
        </View>
      ))}
      {(pct !== null || prov) && (
        <Text style={[typography.caption, s.tier]}>
          {pct !== null ? `${pct}%` : ""}{pct !== null && prov ? " · " : ""}{prov}
        </Text>
      )}
    </Card>
  );
}

function LiveLook() {
  const look = useBrainStore((s) => s.look);
  const [permission, requestPermission] = kit!.useCameraPermissions();
  const camRef = React.useRef<any>(null);
  const [busy, setBusy] = React.useState(false);
  const [panel, setPanel] = React.useState<LookPanel | null>(null);

  if (!permission?.granted) {
    return (
      <View style={{ gap: space.md }}>
        <EmptyState title={t("look.permTitle")} hint={t("look.permHint")} />
        <PrimaryButton label={t("look.allowCamera")} onPress={requestPermission} />
      </View>
    );
  }

  const snap = async () => {
    if (busy || !camRef.current) return;
    setBusy(true);
    setPanel(null);
    play("action");
    try {
      const photo = await camRef.current.takePictureAsync({
        base64: true,
        quality: 0.5,
        skipProcessing: true,
      });
      const res = await look(photo?.base64 ?? "");
      setPanel(res);
      play(res.ok ? "success" : "warn");
      // expo-camera ALWAYS writes the JPEG to the app cache; we only ever use the
      // in-memory base64, so delete the on-disk copy — a captured frame must not
      // linger in the cache after the look (refute 2026-07-18). Best-effort:
      // fire-and-forget, cleanup failure must never affect the result.
      if (photo?.uri) {
        // eslint-disable-next-line @typescript-eslint/no-var-requires
        const FileSystem = require("expo-file-system/legacy");
        FileSystem.deleteAsync(photo.uri, { idempotent: true }).catch(() => {});
      }
    } catch {
      setPanel({ ok: false, rows: [], sources: [], reason: t("look.captureFailed") });
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
      <PrimaryButton label={busy ? t("look.looking") : t("look.look")} onPress={snap} />
      {busy && <ActivityIndicator color={colors.accentSuccess} />}
      {panel && <LensPanel panel={panel} />}
    </View>
  );
}

export default function Look() {
  return (
    <Screen>
      <ScreenHeader
        title="Look"
        eyebrow="Juno"
        subtitle={t("look.subtitle")}
      />
      {kit ? (
        <LiveLook />
      ) : (
        <EmptyState
          title={t("look.noCameraTitle")}
          hint={t("look.noCameraHint")}
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
  row: { marginTop: space.sm, gap: 2 },
  rowHead: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between" },
  tier: { color: colors.textSecondary ?? "#8aa", marginTop: space.md },
});
