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
import { useBrainStore, LookPanel, ScholarMode, ScholarRead, ScholarField } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { PrimaryButton } from "../src/ui/components/PrimaryButton";
import { Tappable } from "../src/ui/components/Tappable";
import { play } from "../src/services/haptics";
import { t } from "../src/i18n";
import { useTheme, makeThemedStyles } from "../src/ui/theme/useTheme";
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
  const s = useS();
  const { colors } = useTheme();
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
  const lines = panel.lines ?? [];
  return (
    <Card>
      {lines.length > 0 && (
        <View style={s.glass}>
          <Text style={[typography.caption, s.glassEyebrow]}>
            {t("look.onGlass")}{panel.localOnly ? ` · ${t("look.localOnly")}` : ""}
          </Text>
          {lines.map((ln, i) => (
            <Text key={i} style={[typography.mono, s.glassLine]}>{ln}</Text>
          ))}
        </View>
      )}
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

/** What one photo is FOR. Recognising a thing and reading a thing are
 *  different questions of the same frame, and Scholar answers the second —
 *  until now it was outside the Brain's import closure entirely, so this strip
 *  had nowhere to send you. `look` is the World lens; the other three are
 *  Scholar's three faces. */
type ReadMode = "look" | ScholarMode;
const MODES: { key: ReadMode; label: string; hint: string }[] = [
  { key: "look", label: "Look", hint: "what is this?" },
  { key: "answer", label: "Answer", hint: "a question in view" },
  { key: "form", label: "Form", hint: "what to write in each field" },
  { key: "explain", label: "Explain", hint: "dense text, plain words" },
];

function ScholarPanel({ read }: { read: ScholarRead }) {
  const s = useS();
  const { colors } = useTheme();
  if (!read.ok) {
    // Scholar's own words for why it could not read — no vision tier, an
    // unreadable frame, the Veil. Never replaced with a generic failure.
    return (
      <Card accent={colors.accentAttention}>
        <Text style={[typography.body, { color: colors.textPrimary }]}>
          {read.detail || "Couldn't read this."}
        </Text>
      </Card>
    );
  }
  const fields = read.items as ScholarField[];
  const isForm = read.mode === "form" && fields.length > 0 && typeof fields[0] === "object";
  return (
    <Card>
      <Text style={[typography.eyebrow, { color: colors.accentMemory }]}>
        {read.mode.toUpperCase()}
      </Text>
      <Text style={[typography.title, { color: colors.textPrimary, marginTop: space.xs }]}>
        {read.primary}
      </Text>
      {read.detail ? (
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.xs }]}>
          {read.detail}
        </Text>
      ) : null}
      {isForm
        ? fields.map((f, i) => (
            <View key={i} style={s.field}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>{f.label}</Text>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>{f.guidance}</Text>
            </View>
          ))
        : (read.items as string[]).map((it, i) => (
            <Text key={i} style={[typography.body, { color: colors.textPrimary, marginTop: space.xs }]}>
              · {String(it)}
            </Text>
          ))}
    </Card>
  );
}

function LiveLook() {
  const s = useS();
  const { colors } = useTheme();
  const look = useBrainStore((s) => s.look);
  const readScholar = useBrainStore((s) => s.readScholar);
  const [mode, setMode] = React.useState<ReadMode>("look");
  const [read, setRead] = React.useState<ScholarRead | null>(null);
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
    setRead(null);
    play("action");
    try {
      const photo = await camRef.current.takePictureAsync({
        base64: true,
        quality: 0.5,
        skipProcessing: true,
      });
      if (mode === "look") {
        const res = await look(photo?.base64 ?? "");
        setPanel(res);
        play(res.ok ? "success" : "warn");
      } else {
        const res = await readScholar(photo?.base64 ?? "", mode);
        setRead(res);
        play(res.ok ? "success" : "warn");
      }
      // expo-camera ALWAYS writes the JPEG to the app cache; we only ever use the
      // in-memory base64, so delete the on-disk copy — a captured frame must not
      // linger in the cache after the look (refute 2026-07-18). Best-effort, and
      // fully isolated: the .catch swallows the ASYNC rejection, and this inner
      // try/catch swallows a SYNCHRONOUS throw (native module absent / wrong API
      // surface) so cleanup can never fall through to the outer catch and
      // overwrite the successful panel we just set (refute 2026-07-18).
      if (photo?.uri) {
        try {
          // eslint-disable-next-line @typescript-eslint/no-var-requires
          const FileSystem = require("expo-file-system/legacy");
          FileSystem.deleteAsync(photo.uri, { idempotent: true }).catch(() => {});
        } catch {
          /* cleanup is best-effort; a successful look must still report success */
        }
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
      <View style={s.modes}>
        {MODES.map((m) => (
          <Tappable
            key={m.key}
            onPress={() => { setMode(m.key); setPanel(null); setRead(null); }}
            style={[s.mode, mode === m.key ? s.modeOn : null]}
            accessibilityLabel={`${m.label} — ${m.hint}`}
          >
            <Text style={[typography.caption, {
              color: mode === m.key ? colors.textPrimary : colors.textSecondary,
            }]}>{m.label}</Text>
          </Tappable>
        ))}
      </View>
      <PrimaryButton label={busy ? t("look.looking") : t("look.look")} onPress={snap} />
      {busy && <ActivityIndicator color={colors.accentSuccess} />}
      {panel && <LensPanel panel={panel} />}
      {read && <ScholarPanel read={read} />}
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

const useS = makeThemedStyles(({ colors, platinum }) => StyleSheet.create({
  viewport: {
    height: 320,
    borderRadius: radius.lg,
    overflow: "hidden",
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.08)",
  },
  /* the one-photo, four-questions strip: Look recognises, the other three read */
  modes: { flexDirection: "row", gap: space.sm },
  mode: {
    flex: 1,
    alignItems: "center",
    paddingVertical: space.sm,
    borderRadius: radius.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderSubtle,
  },
  modeOn: { backgroundColor: colors.surfaceElevated, borderColor: colors.accentMemory },
  field: { marginTop: space.sm, gap: 2 },
  row: { marginTop: space.sm, gap: 2 },
  rowHead: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between" },
  tier: { color: colors.textSecondary ?? "#8aa", marginTop: space.md },
  /* the on-glass preview: the exact budget-clamped lines the glass would draw,
     on a dark disc-like well — one shared server formatter feeds this and the
     browser Live Lens, so every surface shows the same look */
  glass: {
    backgroundColor: "#050807",
    borderRadius: radius.lg,
    paddingVertical: space.md,
    paddingHorizontal: space.md,
    marginBottom: space.md,
    alignItems: "center",
    borderWidth: 1,
    borderColor: "rgba(125,255,168,0.35)",
  },
  glassEyebrow: { color: "#3F8F5C", letterSpacing: 1.2, textTransform: "uppercase", marginBottom: 4 },
  glassLine: { color: "#7DFFA8", lineHeight: 20 },
}));
