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
      const bits = [r.brain ? "Mac mini" : "", r.glasses ? "glasses" : ""].filter(Boolean);
      if (bits.length) {
        tapSuccess();
        setPairMsg(`Paired ${bits.join(" + ")}.`);
      } else {
        tapWarn();
        setPairMsg("That code carried nothing to pair.");
      }
      setCode("");
      setPairOpen(false);
    } catch {
      tapWarn();
      setPairMsg("That doesn't look like a DreamLayer pairing code.");
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
          {brainKind === "mac_mini"
            ? "Your Mac mini is the brain — bigger local model, your files, richest answers."
            : "The phone is your hub — pair the Halo glasses to capture, and a Mac mini for a bigger brain over your own files."}
          {cloudOn ? "  Cloud is on for the hardest asks." : "  Cloud is off — everything stays with you."}
        </Text>

        {/* pair a device */}
        <View style={s.pairBar}>
          <PillButton label={pairOpen ? "Cancel" : "＋ Pair a device"} onPress={() => setPairOpen(!pairOpen)} ghost={pairOpen} />
          {pairMsg ? <Text style={[typography.caption, { color: colors.accentSuccess, marginTop: 8 }]}>{pairMsg}</Text> : null}
        </View>
        {pairOpen ? (
          <View style={s.pairBox}>
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              Open the Brain panel on your Mac mini → “Pair a phone”, then scan or paste the code. One code brings the Mac
              mini and your glasses together.
            </Text>
            <PillButton label="⃞ Scan QR" onPress={() => setScanOpen(true)} />
            <Text style={[typography.caption, { color: colors.textSecondary, textAlign: "center", marginVertical: 6 }]}>
              — or paste the code —
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
            <PillButton label="Connect" onPress={doPair} />
          </View>
        ) : null}
        <QrScanner visible={scanOpen} onClose={() => setScanOpen(false)} onScan={onScanned} />

        {/* glasses */}
        <Text style={[typography.eyebrow, s.eyebrow]}>Devices</Text>
        <ConnectorCard
          title="Glasses"
          accent={colors.accentMemory}
          on={b.glasses.connected}
          status={b.glasses.connected ? b.glasses.id || "Connected" : "Not connected"}
        >
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            The Halo display — where every lens is drawn. Pair with the code above, or over Bluetooth from onboarding.
          </Text>
          {b.glasses.connected ? (
            <PillButton label="Forget glasses" ghost onPress={b.disconnectGlasses} />
          ) : null}
        </ConnectorCard>

        {/* mac mini */}
        <ConnectorCard
          title="Mac mini brain"
          accent={colors.accentMemory}
          on={b.macMini.connected}
          status={b.macMini.connected ? "Connected" : "Optional upgrade"}
        >
          {b.macMini.connected ? (
            <>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                {b.macMini.url}
              </Text>
              <Bullet>Searches your own files & mail (Lucid Recall)</Bullet>
              <Bullet>Richer object explanations than the phone alone</Bullet>
              <Bullet>Runs on your LAN — no internet required</Bullet>
              <PillButton label="Use phone as brain instead" ghost onPress={() => b.connectMacMini(false)} />
            </>
          ) : (
            <>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                Connect an always-on Mac mini and it becomes the brain: a bigger local model plus everything in your chosen
                folders and mail — smart and private, on your own network.
              </Text>
              <Bullet>Bigger local model, still fully private</Bullet>
              <Bullet>Answers from your files, notes & mail</Bullet>
              <Bullet>Works on your home Wi-Fi with no internet</Bullet>
              {b.macMini.url ? (
                <PillButton label="Reconnect Mac mini" onPress={() => b.connectMacMini(true)} />
              ) : (
                <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 12, fontStyle: "italic" }]}>
                  Pair one with the code above to enable this.
                </Text>
              )}
            </>
          )}
        </ConnectorCard>

        {/* cloud — its own switch */}
        <Text style={[typography.eyebrow, s.eyebrow]}>Reach</Text>
        <ConnectorCard title="Cloud" accent={colors.accentMemory} on={cloudOn} status={cloudOn ? "On" : "Off"}>
          <SwitchRow
            label="Use cloud for hard cases"
            sub={
              b.incognito
                ? "Held off while Incognito is on"
                : "An independent switch — works whether the brain is your phone or your Mac mini"
            }
            value={cloudOn}
            disabled={b.incognito}
            onValueChange={b.setCloud}
          />
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 10, marginBottom: 4 }]}>
            Turning cloud on adds, only for the hardest, non-personal asks:
          </Text>
          <Bullet>Obscure facts that aren’t in your own files</Bullet>
          <Bullet>The richest object explanations (frontier vision)</Bullet>
          <Bullet>Widest translation coverage (Rosetta & Puente)</Bullet>
          <Bullet muted>Needs a connection — off in airplane mode</Bullet>
          <Bullet muted>Anything marked private never leaves, cloud or not</Bullet>
        </ConnectorCard>

        {/* incognito */}
        <Text style={[typography.eyebrow, s.eyebrow]}>Privacy</Text>
        <ConnectorCard title="Incognito" accent={colors.accentAttention} on={b.incognito} status={b.incognito ? "On" : "Off"}>
          <SwitchRow
            label="Incognito mode"
            sub="Forces cloud off and pauses capture for this session"
            value={b.incognito}
            accent={colors.accentAttention}
            onValueChange={b.setIncognito}
          />
        </ConnectorCard>
        <ConnectorCard title="Capture" on={!b.capturePaused} status={b.capturePaused ? "Paused" : "Recording"}>
          <SwitchRow
            label="Pause memory capture"
            sub="Nothing is remembered while paused"
            value={b.capturePaused}
            accent={colors.statusPaused}
            onValueChange={b.setCapturePaused}
          />
        </ConnectorCard>

        {/* recall from the phone */}
        <Text style={[typography.eyebrow, s.eyebrow]}>Ask your brain</Text>
        <View style={s.askCard}>
          <Text style={[typography.caption, { color: colors.textSecondary, marginBottom: 8 }]}>
            The same brain your glasses use — ask it from your pocket.
          </Text>
          <TextInput
            value={q}
            onChangeText={setQ}
            placeholder="where’s the lease? what does Marcus owe me?"
            placeholderTextColor={colors.textSecondary}
            style={s.input}
            onSubmitEditing={doAsk}
            returnKeyType="search"
          />
          <PillButton label="Ask" onPress={doAsk} />
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
              <Text style={[typography.eyebrow, s.eyebrow]}>Upcoming</Text>
              <PillButton label={syncing ? "Syncing…" : "Sync calendar"} ghost onPress={syncCalendar} />
            </View>
            <View style={s.card}>
              {events.length === 0 ? (
                <Text style={[typography.caption, { color: colors.textSecondary }]}>No events yet — add one or sync your Mac Calendar.</Text>
              ) : (
                events.map((e, i) => (
                  <View key={i} style={s.evRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={[typography.body, { color: colors.textPrimary }]}>
                        {e.title}
                        {e.source === "calendar" ? <Text style={{ color: colors.textSecondary }}>{"  · " + (e.calendar || "Calendar")}</Text> : null}
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
                  placeholder="add an event…"
                  placeholderTextColor={colors.textSecondary}
                  style={s.input}
                  onSubmitEditing={addEvent}
                />
                <PillButton label="Add" onPress={addEvent} />
              </View>
            </View>

            <Text style={[typography.eyebrow, s.eyebrow]}>Recent activity</Text>
            <View style={s.card}>
              {activity.length === 0 ? (
                <Text style={[typography.caption, { color: colors.textSecondary }]}>Nothing yet.</Text>
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
        <Text style={[typography.eyebrow, s.eyebrow]}>What your brain can do</Text>
        <View style={s.lensGrid}>
          {LENSES.map((l) => (
            <View key={l.name} style={s.lens}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>{l.name}</Text>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>{l.blurb}</Text>
            </View>
          ))}
        </View>
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const LENSES = [
  { name: "Lucid Recall", blurb: "Your memory, files & mail — ask anything" },
  { name: "Juno", blurb: "Look at a thing, know what it is" },
  { name: "People", blurb: "Names, faces you chose to remember, what you owe" },
  { name: "Waypath", blurb: "Where you left it, how to get back" },
  { name: "Rosetta & Puente", blurb: "Read and hear the world in your language" },
  { name: "Prism", blurb: "Turn the ordinary luminous" },
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
