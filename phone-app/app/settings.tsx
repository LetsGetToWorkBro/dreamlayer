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
  danger: { paddingVertical: 16, alignItems: "center", borderRadius: 12, borderWidth: 1, borderColor: colors.accentError },
});
