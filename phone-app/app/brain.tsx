import React, { useEffect, useState } from "react";
import { View, Text, ScrollView, TextInput, StyleSheet } from "react-native";
// safe-area-context: RN's SafeAreaView is deprecated and a no-op on Android
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { useBrainStore } from "../src/state/useBrainStore";
import { ConnectorCard, SwitchRow, Bullet, PillButton } from "../src/ui/components/Connector";
import { QrScanner } from "../src/ui/components/QrScanner";
import { DemoBanner } from "../src/ui/components/DemoBanner";
import { CineBackdrop } from "../src/ui/components/CineBackdrop";
import { MenuBar } from "../src/ui/components/MenuBar";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Tappable } from "../src/ui/components/Tappable";
import { tapSuccess, tapWarn } from "../src/services/haptics";
import { t } from "../src/i18n";
import { useTheme, makeThemedStyles } from "../src/ui/theme/useTheme";
import { typography } from "../src/ui/theme/typography";

/** A drill-in row: a label + subtitle and a chevron, the iOS way into a
 * sub-screen (Preferences, Labs). */
function NavRow({ label, sub, onPress, last }: { label: string; sub?: string; onPress: () => void; last?: boolean }) {
  const s = useS();
  const { colors } = useTheme();
  return (
    <Tappable onPress={onPress} style={[s.navRow, last ? s.navRowLast : null]} accessibilityHint="Opens a sub-screen">
      <View style={{ flex: 1 }}>
        <Text style={[typography.body, { color: colors.textPrimary }]}>{label}</Text>
        {sub ? <Text style={[typography.caption, { color: colors.textSecondary }]}>{sub}</Text> : null}
      </View>
      <Text style={s.chev}>›</Text>
    </Tappable>
  );
}

export default function Brain() {
  const s = useS();
  const { colors } = useTheme();
  const router = useRouter();
  const b = useBrainStore();
  useEffect(() => {
    if (!b.hydrated) b.hydrate();
  }, [b.hydrated]);

  const [pairOpen, setPairOpen] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);
  const [code, setCode] = useState("");
  const [pairMsg, setPairMsg] = useState("");

  const brainKind = b.brainKind();
  const cloudOn = b.effectiveCloud();

  const applyCode = (raw: string) => {
    try {
      const r = b.pairFromCode(raw.trim());
      const bits = [r.brain ? "Mac mini" : "", r.glasses ? t("brain.glassesWord") : ""].filter(Boolean);
      if (bits.length) {
        tapSuccess();
        setPairMsg(t("brain.paired", { what: bits.join(" + ") }));
      } else {
        tapWarn();
        setPairMsg(t("brain.pairEmpty"));
      }
      setCode("");
      setPairOpen(false);
    } catch {
      tapWarn();
      setPairMsg(t("brain.pairBad"));
    }
  };

  const doPair = () => applyCode(code);
  const onScanned = (scanned: string) => {
    setScanOpen(false);
    applyCode(scanned);
  };

  return (
    <View style={s.root}>
      <CineBackdrop />
      <SafeAreaView style={s.safe}>
      <MenuBar />
      <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
        <DemoBanner />
        <ScreenHeader
          eyebrow="DreamLayer"
          title={t("brain.title")}
          subtitle={
            (brainKind === "mac_mini" ? t("brain.descMac") : t("brain.descPhone")) +
            (cloudOn ? t("brain.cloudOnSuffix") : t("brain.cloudOffSuffix"))
          }
        />

        {/* pair a device */}
        <View style={s.pairBar}>
          <PillButton label={pairOpen ? t("brain.cancel") : "＋ " + t("brain.pairDevice")} onPress={() => setPairOpen(!pairOpen)} ghost={pairOpen} />
          {pairMsg ? <Text style={[typography.caption, { color: colors.accentSuccess, marginTop: 8 }]}>{pairMsg}</Text> : null}
        </View>
        {pairOpen ? (
          <View style={s.pairBox}>
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              {t("brain.pairInstructions")}
            </Text>
            <PillButton label={"⃞ " + t("brain.scanQr")} onPress={() => setScanOpen(true)} />
            <Text style={[typography.caption, { color: colors.textSecondary, textAlign: "center", marginVertical: 6 }]}>
              {t("brain.orPaste")}
            </Text>
            <TextInput
              value={code}
              onChangeText={setCode}
              placeholder="dreamlayer:…"
              placeholderTextColor={colors.textSecondary}
              autoCapitalize="none"
              autoCorrect={false}
              style={s.input}
            />
            <PillButton label={t("brain.connect")} onPress={doPair} />
          </View>
        ) : null}
        <QrScanner visible={scanOpen} onClose={() => setScanOpen(false)} onScan={onScanned} />

        {/* glasses */}
        <Text style={[typography.eyebrow, s.eyebrow]}>{t("brain.devices")}</Text>
        <ConnectorCard
          title={t("brain.glasses")}
          accent={colors.accentMemory}
          on={b.glasses.connected}
          status={b.glasses.connected ? b.glasses.id || t("brain.connected") : t("brain.notConnected")}
        >
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {t("brain.glassesDesc")}
          </Text>
          {b.glasses.connected ? (
            <PillButton label={t("brain.forgetGlasses")} ghost onPress={b.disconnectGlasses} />
          ) : null}
        </ConnectorCard>

        {/* mac mini */}
        <ConnectorCard
          title={t("brain.macTitle")}
          accent={colors.accentMemory}
          on={b.macMini.connected}
          status={b.macMini.connected ? t("brain.connected") : t("brain.optionalUpgrade")}
        >
          {b.macMini.connected ? (
            <>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                {b.macMini.url}
              </Text>
              <Bullet>{t("brain.macBullet1")}</Bullet>
              <Bullet>{t("brain.macBullet2")}</Bullet>
              <Bullet>{t("brain.macBullet3")}</Bullet>
              <PillButton label={t("brain.usePhone")} ghost onPress={() => b.connectMacMini(false)} />
            </>
          ) : (
            <>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                {t("brain.macDesc")}
              </Text>
              <Bullet>{t("brain.macOffBullet1")}</Bullet>
              <Bullet>{t("brain.macOffBullet2")}</Bullet>
              <Bullet>{t("brain.macOffBullet3")}</Bullet>
              {b.macMini.url ? (
                <PillButton label={t("brain.reconnectMac")} onPress={() => b.connectMacMini(true)} />
              ) : (
                <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 12, fontStyle: "italic" }]}>
                  {t("brain.pairToEnable")}
                </Text>
              )}
            </>
          )}
        </ConnectorCard>

        {/* cloud — its own switch */}
        <Text style={[typography.eyebrow, s.eyebrow]}>{t("brain.reach")}</Text>
        <ConnectorCard title={t("brain.cloud")} accent={colors.accentMemory} on={cloudOn} status={cloudOn ? t("brain.on") : t("brain.off")}>
          <SwitchRow
            label={t("brain.cloudLabel")}
            sub={b.incognito ? t("brain.cloudHeld") : t("brain.cloudSub")}
            value={cloudOn}
            disabled={b.incognito}
            onValueChange={b.setCloud}
          />
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 10, marginBottom: 4 }]}>
            {t("brain.cloudAdds")}
          </Text>
          <Bullet>{t("brain.cloudBullet1")}</Bullet>
          <Bullet>{t("brain.cloudBullet2")}</Bullet>
          <Bullet>{t("brain.cloudBullet3")}</Bullet>
          <Bullet muted>{t("brain.cloudBullet4")}</Bullet>
          <Bullet muted>{t("brain.cloudBullet5")}</Bullet>
        </ConnectorCard>

        {/* incognito + capture */}
        <Text style={[typography.eyebrow, s.eyebrow]}>{t("brain.privacy")}</Text>
        <ConnectorCard title={t("brain.incognito")} accent={colors.accentAttention} on={b.incognito} status={b.incognito ? t("brain.on") : t("brain.off")}>
          <SwitchRow
            label={t("brain.incognitoLabel")}
            sub={t("brain.incognitoSub")}
            value={b.incognito}
            accent={colors.accentAttention}
            onValueChange={b.setIncognito}
          />
        </ConnectorCard>
        <ConnectorCard title={t("brain.capture")} on={!b.capturePaused} status={b.capturePaused ? t("brain.paused") : t("brain.recording")}>
          <SwitchRow
            label={t("brain.pauseLabel")}
            sub={t("brain.pauseSub")}
            value={b.capturePaused}
            accent={colors.statusPaused}
            onValueChange={b.setCapturePaused}
          />
        </ConnectorCard>

        {/* the rest of the control center, one tap in */}
        <Text style={[typography.eyebrow, s.eyebrow]}>More</Text>
        <View style={s.navPanel}>
          <NavRow
            label="Preferences"
            sub="Appearance, Juno, privacy & data"
            onPress={() => router.push("/settings")}
          />
          <NavRow
            label="Labs"
            sub="Experiments and deeper tools"
            onPress={() => router.push("/labs")}
            last
          />
        </View>

        <View style={{ height: 40 }} />
      </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const useS = makeThemedStyles(({ colors, platinum }) => {
  const panel = {
    backgroundColor: platinum.face,
    borderRadius: 10,
    borderTopColor: platinum.hi,
    borderLeftColor: platinum.hi,
    borderBottomColor: platinum.sh,
    borderRightColor: platinum.sh,
    borderWidth: 1.5,
  } as const;
  return StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  safe: { flex: 1, backgroundColor: "transparent" },
  scroll: { paddingHorizontal: 20, paddingTop: 20 },
  eyebrow: { color: colors.accentMemory, marginTop: 22, marginBottom: 10 },
  pairBar: { marginTop: 18, marginBottom: 4 },
  pairBox: { ...panel, padding: 16, marginTop: 10, marginBottom: 6 },
  // a white inset field — the Platinum text well
  input: {
    backgroundColor: platinum.well,
    borderWidth: 1,
    borderColor: platinum.frame,
    borderRadius: 6,
    color: colors.textPrimary,
    paddingHorizontal: 14,
    paddingVertical: 12,
    marginTop: 12,
    fontSize: 15,
  },
  navPanel: { ...panel, paddingHorizontal: 16 },
  navRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: platinum.line,
  },
  navRowLast: { borderBottomWidth: 0 },
  chev: { ...typography.title, fontSize: 18, color: platinum.sh, marginLeft: 8 },
  });
});
