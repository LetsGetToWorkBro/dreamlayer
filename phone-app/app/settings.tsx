import React from "react";
import { View, Text, Switch, SafeAreaView, ScrollView, StyleSheet, TouchableOpacity, Alert, Linking } from "react-native";
import { useRouter } from "expo-router";
import { useHaloStore } from "../src/state/useHaloStore";
import { useMemoryStore } from "../src/state/useMemoryStore";
import { useBrainStore } from "../src/state/useBrainStore";
import { colors, platinum } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { DemoBanner } from "../src/ui/components/DemoBanner";
import { CineBackdrop } from "../src/ui/components/CineBackdrop";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { t } from "../src/i18n";

function Row({ label, sub, right }: { label: string; sub?: string; right: React.ReactNode }) {
  return (
    <View style={s.row}>
      <View style={{ flex: 1, paddingRight: 12 }}>
        <Text style={[typography.body, { color: colors.textPrimary }]}>{label}</Text>
        {sub && <Text style={[typography.caption, { color: colors.textSecondary }]}>{sub}</Text>}
      </View>
      {right}
    </View>
  );
}

export default function Settings() {
  const router = useRouter();
  const { paused, togglePause, connected } = useHaloStore();
  const { service } = useMemoryStore();
  const incognito = useBrainStore((s) => s.incognito);
  const setIncognito = useBrainStore((s) => s.setIncognito);
  const notifyTexts = useBrainStore((s) => s.notifyTexts);
  const setNotifyTexts = useBrainStore((s) => s.setNotifyTexts);
  const notifyEmails = useBrainStore((s) => s.notifyEmails);
  const setNotifyEmails = useBrainStore((s) => s.setNotifyEmails);
  const summarizeEmails = useBrainStore((s) => s.summarizeEmails);
  const setSummarizeEmails = useBrainStore((s) => s.setSummarizeEmails);
  const proactiveCards = useBrainStore((s) => s.proactiveCards);
  const setProactiveCards = useBrainStore((s) => s.setProactiveCards);
  const focus = useBrainStore((s) => s.focus);
  const setFocus = useBrainStore((s) => s.setFocus);
  const cues = useBrainStore((s) => s.cues);
  const setCue = useBrainStore((s) => s.setCue);
  const wakeSources = useBrainStore((s) => s.wakeSources);
  const setWakeSource = useBrainStore((s) => s.setWakeSource);
  const wakeFeedback = useBrainStore((s) => s.wakeFeedback);
  const setWakeFeedback = useBrainStore((s) => s.setWakeFeedback);
  const proactiveAlerts = useBrainStore((s) => s.proactiveAlerts);
  const setProactiveAlerts = useBrainStore((s) => s.setProactiveAlerts);
  const factCheck = useBrainStore((s) => s.factCheck);
  const setFactCheck = useBrainStore((s) => s.setFactCheck);
  const answerAhead = useBrainStore((s) => s.answerAhead);
  const setAnswerAhead = useBrainStore((s) => s.setAnswerAhead);
  const demoMode = useBrainStore((s) => s.demoMode);
  const enableDemo = useBrainStore((s) => s.enableDemo);
  const disableDemo = useBrainStore((s) => s.disableDemo);

  const confirmPurge = () =>
    Alert.alert(t("settings.erasePrompt"), t("settings.erasePromptBody"), [
      { text: t("settings.cancel"), style: "cancel" },
      { text: t("settings.erase"), style: "destructive", onPress: () => service.purgeAll() },
    ]);

  return (
    <View style={s.root}>
      <CineBackdrop />
      <SafeAreaView style={s.safe}>
      <ScrollView contentContainerStyle={s.scrollBody} showsVerticalScrollIndicator={false}>
      <View style={s.headWrap}>
        <ScreenHeader title={t("settings.title")} />
        <DemoBanner />
      </View>

      <View style={s.section}>
        <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: 14 }]}>{t("settings.privacy")}</Text>
        <Row
          label={t("settings.proactiveCards")}
          sub={t("settings.proactiveCardsSub")}
          right={
            <Switch
              value={proactiveCards}
              onValueChange={setProactiveCards}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={platinum.well}
            />
          }
        />
        {proactiveCards ? (
          <View style={s.subGroup}>
            {(
              [
                ["event", t("settings.cueEvent")],
                ["person", t("settings.cuePerson")],
                ["place", t("settings.cuePlace")],
              ] as const
            ).map(([kind, label]) => (
              <Row
                key={kind}
                label={label}
                right={
                  <Switch
                    value={cues[kind]}
                    onValueChange={(v) => setCue(kind, v)}
                    trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
                    thumbColor={platinum.well}
                  />
                }
              />
            ))}
          </View>
        ) : null}
        <Row
          label={t("settings.focus")}
          sub={t("settings.focusSub")}
          right={
            <Switch
              value={focus}
              onValueChange={setFocus}
              trackColor={{ true: "#3D63C7", false: colors.borderSubtle }}
              thumbColor={platinum.well}
            />
          }
        />
        <Row
          label={t("settings.incognito")}
          sub={t("settings.incognitoSub")}
          right={
            <Switch
              value={incognito}
              onValueChange={setIncognito}
              trackColor={{ true: colors.accentAttention, false: colors.borderSubtle }}
              thumbColor={platinum.well}
            />
          }
        />
        <Row
          label={t("settings.textPopups")}
          sub={t("settings.textPopupsSub")}
          right={
            <Switch
              value={notifyTexts}
              onValueChange={setNotifyTexts}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={platinum.well}
            />
          }
        />
        <Row
          label={t("settings.emailPopups")}
          sub={t("settings.emailPopupsSub")}
          right={
            <Switch
              value={notifyEmails}
              onValueChange={setNotifyEmails}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={platinum.well}
            />
          }
        />
        <Row
          label={t("settings.summarize")}
          sub={t("settings.summarizeSub")}
          right={
            <Switch
              value={summarizeEmails}
              onValueChange={setSummarizeEmails}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={platinum.well}
            />
          }
        />
        <Row
          label={t("settings.pauseCapture")}
          sub={t("settings.pauseCaptureSub")}
          right={
            <Switch
              value={paused}
              onValueChange={togglePause}
              trackColor={{ true: colors.statusPaused, false: colors.borderSubtle }}
              thumbColor={platinum.well}
            />
          }
        />
      </View>

      <View style={s.section}>
        <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: 14 }]}>{t("settings.juno")}</Text>
        <Row
          label={t("settings.wakeWord")}
          sub={t("settings.wakeWordSub")}
          right={<Text style={[typography.caption, { color: colors.accentMemory }]}>{t("settings.wakeWordValue")}</Text>}
        />
        <Row
          label={t("settings.proactiveAlerts")}
          sub={t("settings.proactiveAlertsSub")}
          right={
            <Switch
              value={proactiveAlerts}
              onValueChange={setProactiveAlerts}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={platinum.well}
            />
          }
        />
        <Row
          label={t("settings.factCheck")}
          sub={t("settings.factCheckSub")}
          right={
            <Switch
              value={factCheck}
              onValueChange={setFactCheck}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={platinum.well}
            />
          }
        />
        <Row
          label={t("settings.answerAhead")}
          sub={t("settings.answerAheadSub")}
          right={
            <Switch
              value={answerAhead}
              onValueChange={setAnswerAhead}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={platinum.well}
            />
          }
        />
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 14, marginBottom: 2 }]}>
          {t("settings.alsoWakeBy")}
        </Text>
        {(
          [
            ["voice", t("settings.wakeVoice")],
            ["tap", t("settings.wakeTap")],
            ["gaze", t("settings.wakeGaze")],
            ["raise", t("settings.wakeRaise")],
          ] as const
        ).map(([src, label]) => (
          <Row
            key={src}
            label={label}
            right={
              <Switch
                value={wakeSources[src]}
                onValueChange={(v) => setWakeSource(src, v)}
                trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
                thumbColor={platinum.well}
              />
            }
          />
        ))}
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 14, marginBottom: 2 }]}>
          {t("settings.showListening")}
        </Text>
        {(
          [
            ["visual", t("settings.fbVisual")],
            ["audio", t("settings.fbAudio")],
            ["haptic", t("settings.fbHaptic")],
          ] as const
        ).map(([kind, label]) => (
          <Row
            key={kind}
            label={label}
            right={
              <Switch
                value={wakeFeedback[kind]}
                onValueChange={(v) => setWakeFeedback(kind, v)}
                trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
                thumbColor={platinum.well}
              />
            }
          />
        ))}
      </View>

      <View style={s.section}>
        <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: 14 }]}>{t("settings.devicesBrain")}</Text>
        <Row
          label={t("settings.glasses")}
          sub={connected ? t("settings.connected") : t("settings.notConnected")}
          right={
            <Text style={[typography.caption, { color: connected ? colors.accentSuccess : colors.textSecondary }]}>
              {connected ? "●" : "○"}
            </Text>
          }
        />
        <TouchableOpacity onPress={() => router.push("/brain")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.pairLink")}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/brain-tiers")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.brainTierLink")}</Text>
        </TouchableOpacity>
      </View>

      <View style={s.section}>
        <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: 14 }]}>{t("settings.tryIt")}</Text>
        <Row
          label={t("settings.demoMode")}
          sub={t("settings.demoModeSub")}
          right={
            <Switch
              value={demoMode}
              onValueChange={(v) => (v ? enableDemo() : disableDemo())}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={platinum.well}
            />
          }
        />
        <TouchableOpacity onPress={() => router.push("/onboarding")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.tourAgain")}</Text>
        </TouchableOpacity>
      </View>

      <View style={s.section}>
        <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: 14 }]}>{t("settings.labs")}</Text>
        <TouchableOpacity onPress={() => router.push("/saga")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.sagaLink")}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/profile")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.profileLink")}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/rewind")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.rewindLink")}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/ember")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.emberLink")}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/plugins")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.pluginsLink")}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/capabilities")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.capabilitiesLink")}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/vitals")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.vitalsLink")}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/cloud")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.cloudLink")}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/waypath")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.waypathLink")}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/packs")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.feelLink")}</Text>
        </TouchableOpacity>
      </View>

      <View style={s.section}>
        <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: 14 }]}>{t("settings.privacyLegal")}</Text>
        <Text style={[typography.caption, { color: colors.textSecondary, marginBottom: 8 }]}>
          {t("settings.privacyBlurb")}
        </Text>
        <TouchableOpacity onPress={() => Linking.openURL("https://dreamlayer.app/privacy.html")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>{t("settings.privacyPolicy")}</Text>
        </TouchableOpacity>
      </View>

      <View style={s.section}>
        <Text style={[typography.eyebrow, { color: colors.accentError, marginBottom: 14 }]}>{t("settings.dangerZone")}</Text>
        <TouchableOpacity onPress={confirmPurge} style={s.danger}>
          <Text style={[typography.body, { color: colors.accentError }]}>{t("settings.eraseAll")}</Text>
        </TouchableOpacity>
      </View>
      </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  safe: { flex: 1, backgroundColor: "transparent" },
  // room so the last row clears the floating tab bar
  scrollBody: { paddingBottom: 120, paddingTop: 20 },
  headWrap: { paddingHorizontal: 24 },
  // each group is a raised platinum panel on the desktop
  section: {
    marginHorizontal: 24,
    marginTop: 22,
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 6,
    backgroundColor: platinum.face,
    borderRadius: 10,
    borderTopColor: platinum.hi,
    borderLeftColor: platinum.hi,
    borderBottomColor: platinum.sh,
    borderRightColor: platinum.sh,
    borderWidth: 1.5,
  },
  row: { flexDirection: "row", alignItems: "center", paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: "#C4C4C4" },
  linkRow: { paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: "#C4C4C4" },
  subGroup: { paddingLeft: 16, borderLeftWidth: 2, borderLeftColor: platinum.sh, marginLeft: 2 },
  danger: { paddingVertical: 16, alignItems: "center", borderRadius: 8, borderWidth: 1.5, borderColor: colors.accentError, marginTop: 8, marginBottom: 6, backgroundColor: platinum.well },
});
