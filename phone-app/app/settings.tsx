import React from "react";
import { View, Text, Switch, SafeAreaView, StyleSheet, TouchableOpacity, Alert } from "react-native";
import { useRouter } from "expo-router";
import { useHaloStore } from "../src/state/useHaloStore";
import { useMemoryStore } from "../src/state/useMemoryStore";
import { useBrainStore } from "../src/state/useBrainStore";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";

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

  const confirmPurge = () =>
    Alert.alert("Erase all memories?", "This cannot be undone.", [
      { text: "Cancel", style: "cancel" },
      { text: "Erase", style: "destructive", onPress: () => service.purgeAll() },
    ]);

  return (
    <SafeAreaView style={s.safe}>
      <Text style={[typography.title, s.heading]}>Settings</Text>

      <View style={s.section}>
        <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: 14 }]}>Privacy</Text>
        <Row
          label="Proactive cards"
          sub="Let the glasses surface the right card unasked — events, arrivals, people"
          right={
            <Switch
              value={proactiveCards}
              onValueChange={setProactiveCards}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={colors.textPrimary}
            />
          }
        />
        {proactiveCards ? (
          <View style={s.subGroup}>
            {(
              [
                ["event", "Events — “leave in 8 min”"],
                ["person", "People — who’s in front of you"],
                ["place", "Places — what you left here"],
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
                    thumbColor={colors.textPrimary}
                  />
                }
              />
            ))}
          </View>
        ) : null}
        <Row
          label="Focus mode"
          sub="Turn the interruptions down — cards, captions, and pop-ups hush; capture keeps running (unlike incognito)"
          right={
            <Switch
              value={focus}
              onValueChange={setFocus}
              trackColor={{ true: "#8FB8FF", false: colors.borderSubtle }}
              thumbColor={colors.textPrimary}
            />
          }
        />
        <Row
          label="Incognito mode"
          sub="Cloud off + capture paused for this session"
          right={
            <Switch
              value={incognito}
              onValueChange={setIncognito}
              trackColor={{ true: colors.accentAttention, false: colors.borderSubtle }}
              thumbColor={colors.textPrimary}
            />
          }
        />
        <Row
          label="Text pop-ups on glasses"
          sub="New texts flash on the Halo (silenced by the Privacy Veil)"
          right={
            <Switch
              value={notifyTexts}
              onValueChange={setNotifyTexts}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={colors.textPrimary}
            />
          }
        />
        <Row
          label="Email pop-ups on glasses"
          sub="New emails flash too — separate from texts"
          right={
            <Switch
              value={notifyEmails}
              onValueChange={setNotifyEmails}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={colors.textPrimary}
            />
          }
        />
        <Row
          label="Summarize long emails"
          sub="The Brain shortens long emails to a one-line glance"
          right={
            <Switch
              value={summarizeEmails}
              onValueChange={setSummarizeEmails}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={colors.textPrimary}
            />
          }
        />
        <Row
          label="Pause memory capture"
          sub="Nothing is captured while paused"
          right={
            <Switch
              value={paused}
              onValueChange={togglePause}
              trackColor={{ true: colors.statusPaused, false: colors.borderSubtle }}
              thumbColor={colors.textPrimary}
            />
          }
        />
      </View>

      <View style={s.section}>
        <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: 14 }]}>Oracle</Text>
        <Row
          label="Wake word"
          sub="Say “Hey Oracle” to wake your assistant, then just keep talking — follow-ups need no wake word"
          right={<Text style={[typography.caption, { color: colors.accentMemory }]}>“Hey Oracle”</Text>}
        />
        <Row
          label="Proactive alerts"
          sub="Let Oracle speak up when it matters — “Listen!” for a slipping promise or someone you owe, “Watch out!” when you need to leave now"
          right={
            <Switch
              value={proactiveAlerts}
              onValueChange={setProactiveAlerts}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={colors.textPrimary}
            />
          }
        />
        <Row
          label="Live fact-checker"
          sub="As people talk, Oracle quietly checks what’s said — flagging when someone contradicts what they told you before, or when a claim doesn’t hold up. On-device first; reaches the cloud only if you’ve allowed it"
          right={
            <Switch
              value={factCheck}
              onValueChange={setFactCheck}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={colors.textPrimary}
            />
          }
        />
        <Row
          label="Answer-ahead"
          sub="When someone asks you something, Oracle pulls the answer from what you know and shows it in time to say it yourself — no wake word"
          right={
            <Switch
              value={answerAhead}
              onValueChange={setAnswerAhead}
              trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
              thumbColor={colors.textPrimary}
            />
          }
        />
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 14, marginBottom: 2 }]}>
          Also wake it by
        </Text>
        {(
          [
            ["voice", "Voice — “Hey Oracle”"],
            ["tap", "Tap the temple"],
            ["gaze", "Look & hold (gaze)"],
            ["raise", "Raise to speak"],
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
                thumbColor={colors.textPrimary}
              />
            }
          />
        ))}
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 14, marginBottom: 2 }]}>
          Show it’s listening with
        </Text>
        {(
          [
            ["visual", "A ring in the glasses"],
            ["audio", "A soft chime"],
            ["haptic", "A haptic tick"],
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
                thumbColor={colors.textPrimary}
              />
            }
          />
        ))}
      </View>

      <View style={s.section}>
        <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: 14 }]}>Devices & brain</Text>
        <Row
          label="Glasses"
          sub={connected ? "Connected" : "Not connected"}
          right={
            <Text style={[typography.caption, { color: connected ? colors.accentSuccess : colors.textSecondary }]}>
              {connected ? "●" : "○"}
            </Text>
          }
        />
        <TouchableOpacity onPress={() => router.push("/brain")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>Pair devices, connect your Mac mini, cloud →</Text>
        </TouchableOpacity>
      </View>

      <View style={s.section}>
        <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: 14 }]}>Labs</Text>
        <TouchableOpacity onPress={() => router.push("/saga")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>Saga — your rank, level & badges →</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/rewind")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>Rewind your day — one timeline →</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/rehearsal")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>Rehearsal — the Reality Compiler →</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => router.push("/confluence")} style={s.linkRow}>
          <Text style={[typography.body, { color: colors.accentMemory }]}>Confluence — two wearers, one sky →</Text>
        </TouchableOpacity>
      </View>

      <View style={s.section}>
        <Text style={[typography.eyebrow, { color: colors.accentError, marginBottom: 14 }]}>Danger zone</Text>
        <TouchableOpacity onPress={confirmPurge} style={s.danger}>
          <Text style={[typography.body, { color: colors.accentError }]}>Erase all memories</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  heading: { color: colors.textPrimary, paddingHorizontal: 24, paddingTop: 24, paddingBottom: 8 },
  section: { marginHorizontal: 24, marginTop: 32 },
  row: { flexDirection: "row", alignItems: "center", paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: colors.borderSubtle },
  linkRow: { paddingVertical: 14 },
  subGroup: { paddingLeft: 16, borderLeftWidth: 2, borderLeftColor: colors.borderSubtle, marginLeft: 2 },
  danger: { paddingVertical: 16, alignItems: "center", borderRadius: 12, borderWidth: 1, borderColor: colors.accentError },
});
