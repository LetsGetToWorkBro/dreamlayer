import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  SafeAreaView,
  TextInput,
  StyleSheet,
  ActivityIndicator,
} from "react-native";
import { useBrainStore } from "../src/state/useBrainStore";
import { ConnectorCard, SwitchRow, Bullet, PillButton } from "../src/ui/components/Connector";
import { QrScanner } from "../src/ui/components/QrScanner";
import { DemoBanner } from "../src/ui/components/DemoBanner";
import { tapSuccess, tapWarn } from "../src/services/haptics";
import { t } from "../src/i18n";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";

export default function Brain() {
  const b = useBrainStore();
  useEffect(() => {
    if (!b.hydrated) b.hydrate();
  }, [b.hydrated]);

  const [pairOpen, setPairOpen] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);
  const [code, setCode] = useState("");
  const [pairMsg, setPairMsg] = useState("");
  const [q, setQ] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<{ text: string; tier: string } | null>(null);

  const [events, setEvents] = useState<{ title: string; ts: number; place?: string; source?: string; calendar?: string }[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [activity, setActivity] = useState<{ ts: number; kind: string; text?: string; query?: string }[]>([]);
  const [evTitle, setEvTitle] = useState("");
  useEffect(() => {
    if (b.macMini.connected || b.demoMode) {
      b.getCalendar().then(setEvents);
      b.getActivity().then(setActivity);
    }
  }, [b.macMini.connected, b.demoMode]);

  const addEvent = async () => {
    if (!evTitle.trim()) return;
    // default: one hour from now (a fuller time picker is a later polish)
    const items = await b.addEvent({ title: evTitle.trim(), ts: Date.now() / 1000 + 3600 });
    setEvents(items);
    setEvTitle("");
  };

  const syncCalendar = async () => {
    setSyncing(true);
    const items = await b.syncCalendar();
    setEvents(items);
    setSyncing(false);
  };

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

  const doAsk = async () => {
    if (!q.trim()) return;
    setAsking(true);
    setAnswer(null);
    const res = await b.ask(q.trim());
    setAnswer(res ? { text: res.text, tier: res.tier } : null);
    setAsking(false);
  };

  return (
    <SafeAreaView style={s.safe}>
      <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
        <DemoBanner />
        {/* header */}
        <Text style={[typography.eyebrow, { color: colors.accentMemory }]}>DreamLayer</Text>
        <Text style={[typography.display, { color: colors.textPrimary }]}>{t("brain.title")}</Text>
        <Text style={[typography.body, { color: colors.textSecondary, marginTop: 4 }]}>
          {brainKind === "mac_mini" ? t("brain.descMac") : t("brain.descPhone")}
          {cloudOn ? t("brain.cloudOnSuffix") : t("brain.cloudOffSuffix")}
        </Text>

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
            sub={
              b.incognito
                ? t("brain.cloudHeld")
                : t("brain.cloudSub")
            }
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

        {/* incognito */}
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

        {/* recall from the phone */}
        <Text style={[typography.eyebrow, s.eyebrow]}>{t("brain.askEyebrow")}</Text>
        <View style={s.askCard}>
          <Text style={[typography.caption, { color: colors.textSecondary, marginBottom: 8 }]}>
            {t("brain.askDesc")}
          </Text>
          <TextInput
            value={q}
            onChangeText={setQ}
            placeholder={t("brain.askPlaceholder")}
            placeholderTextColor={colors.textSecondary}
            style={s.input}
            onSubmitEditing={doAsk}
            returnKeyType="search"
          />
          <PillButton label={t("brain.ask")} onPress={doAsk} />
          {asking ? <ActivityIndicator color={colors.accentMemory} style={{ marginTop: 14 }} /> : null}
          {answer ? (
            <View style={s.answer}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>{answer.text}</Text>
              {answer.tier ? (
                <Text style={[typography.mono, { color: colors.textSecondary, marginTop: 6 }]}>{answer.tier}</Text>
              ) : null}
            </View>
          ) : null}
        </View>

        {/* agenda + activity — surfaced from the engines */}
        {b.macMini.connected ? (
          <>
            <View style={s.evHead}>
              <Text style={[typography.eyebrow, s.eyebrow]}>{t("brain.upcoming")}</Text>
              <PillButton label={syncing ? t("brain.syncing") : t("brain.syncCalendar")} ghost onPress={syncCalendar} />
            </View>
            <View style={s.card}>
              {events.length === 0 ? (
                <Text style={[typography.caption, { color: colors.textSecondary }]}>{t("brain.noEvents")}</Text>
              ) : (
                events.map((e, i) => (
                  <View key={i} style={s.evRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={[typography.body, { color: colors.textPrimary }]}>
                        {e.title}
                        {e.source === "calendar" ? <Text style={{ color: colors.textSecondary }}>{"  · " + (e.calendar || t("brain.calendar"))}</Text> : null}
                      </Text>
                    </View>
                    <Text style={[typography.caption, { color: colors.textSecondary }]}>
                      {new Date(e.ts * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}
                    </Text>
                  </View>
                ))
              )}
              <View style={s.evAdd}>
                <TextInput
                  value={evTitle}
                  onChangeText={setEvTitle}
                  placeholder={t("brain.addEventPlaceholder")}
                  placeholderTextColor={colors.textSecondary}
                  style={s.input}
                  onSubmitEditing={addEvent}
                />
                <PillButton label={t("brain.add")} onPress={addEvent} />
              </View>
            </View>

            <Text style={[typography.eyebrow, s.eyebrow]}>{t("brain.recentActivity")}</Text>
            <View style={s.card}>
              {activity.length === 0 ? (
                <Text style={[typography.caption, { color: colors.textSecondary }]}>{t("brain.nothingYet")}</Text>
              ) : (
                activity.slice(0, 8).map((a, i) => (
                  <View key={i} style={s.actRow}>
                    <Text style={[typography.caption, { color: colors.accentMemory, width: 78 }]} numberOfLines={1}>
                      {a.kind}
                    </Text>
                    <Text style={[typography.caption, { color: colors.textSecondary, flex: 1 }]} numberOfLines={1}>
                      {a.query || a.text}
                    </Text>
                  </View>
                ))
              )}
            </View>
          </>
        ) : null}

        {/* what your brain can do */}
        <Text style={[typography.eyebrow, s.eyebrow]}>{t("brain.canDo")}</Text>
        <View style={s.lensGrid}>
          {LENSES.map((l) => (
            <View key={l.name} style={s.lens}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>{l.name}</Text>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>{t(l.blurbKey)}</Text>
            </View>
          ))}
        </View>
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const LENSES = [
  { name: "Lucid Recall", blurbKey: "brain.lucidRecallBlurb" },
  { name: "Juno", blurbKey: "brain.junoBlurb" },
  { name: "People", blurbKey: "brain.peopleBlurb" },
  { name: "Waypath", blurbKey: "brain.waypathBlurb" },
  { name: "Rosetta & Puente", blurbKey: "brain.rosettaBlurb" },
  { name: "Prism", blurbKey: "brain.prismBlurb" },
];

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { paddingHorizontal: 20, paddingTop: 20 },
  eyebrow: { color: colors.accentMemory, marginTop: 22, marginBottom: 10 },
  pairBar: { marginTop: 18, marginBottom: 4 },
  pairBox: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: 16,
    marginTop: 10,
    marginBottom: 6,
  },
  input: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: 12,
    color: colors.textPrimary,
    paddingHorizontal: 14,
    paddingVertical: 12,
    marginTop: 12,
    fontSize: 15,
  },
  askCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: 18,
  },
  answer: {
    marginTop: 14,
    borderLeftWidth: 2,
    borderLeftColor: colors.accentMemory,
    paddingLeft: 12,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: 16,
  },
  evHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  evRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 8, gap: 8 },
  evAdd: { flexDirection: "row", gap: 8, alignItems: "center", marginTop: 8 },
  actRow: { flexDirection: "row", gap: 10, paddingVertical: 6 },
  lensGrid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  lens: {
    width: "47%",
    backgroundColor: colors.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: 14,
  },
});
