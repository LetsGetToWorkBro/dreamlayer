import React from "react";
import { Animated, View, Text, TextInput, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { useHaloStore } from "../src/state/useHaloStore";
import { useBrainStore } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { HaloMirror } from "../src/ui/components/HaloMirror";
import { StatusPill } from "../src/ui/components/StatusPill";
import { Tappable } from "../src/ui/components/Tappable";
import { useEntrance } from "../src/ui/anim";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";
import { pushLocal } from "../src/services/notify";
import { playListen } from "../src/services/sound";

export default function Now() {
  const router = useRouter();
  const { paused, connected, togglePause, connect, service } = useHaloStore();
  const macConnected = useBrainStore((s) => s.macMini.connected);
  const brainKind = macConnected ? "Mac mini" : "phone";
  const getBrief = useBrainStore((s) => s.getBrief);
  const getLatestBrief = useBrainStore((s) => s.getLatestBrief);
  const sendVoice = useBrainStore((s) => s.sendVoice);
  const mirror = useEntrance(60);
  const [brief, setBrief] = React.useState<string | null>(null);
  const [briefing, setBriefing] = React.useState(false);
  const [cmd, setCmd] = React.useState("");
  const [voiceOut, setVoiceOut] = React.useState<string | null>(null);
  const briefSeen = React.useRef(0);

  // Surface the brief the Brain's scheduler delivered on its own at brief_hour,
  // and mirror a fresh one to a local notification so it reaches you off-Halo.
  React.useEffect(() => {
    if (!macConnected) return;
    let alive = true;
    const pull = async () => {
      const b = await getLatestBrief();
      if (!alive || !b || b.ts <= briefSeen.current) return;
      const first = briefSeen.current === 0;
      briefSeen.current = b.ts;
      setBrief(b.text);
      if (!first) {
        playListen(); // Oracle: "Listen!" — a fresh brief just landed
        pushLocal("Morning brief", b.text);
      }
    };
    pull();
    const id = setInterval(pull, 90_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [macConnected, getLatestBrief]);

  const doBrief = async () => {
    setBriefing(true);
    const r = await getBrief();
    setBrief(r?.text ?? "Connect your Mac mini for a brief from your messages & mail.");
    setBriefing(false);
  };

  const doVoice = async () => {
    if (!cmd.trim()) return;
    const r = await sendVoice(cmd.trim());
    setCmd("");
    if (r.intent === "brief") setBrief(r.text ?? "");
    else if (r.answer) setVoiceOut(r.answer);
    else if (r.say) setVoiceOut(r.say); // timers, notes, debts, meet — Oracle's confirmation
    else if (r.intent === "reply") setVoiceOut(`Reply to ${r.to}: “${r.text}” — open Messages to send.`);
    else setVoiceOut(`(${r.intent})`);
  };

  return (
    <Screen scroll={false}>
      <ScreenHeader title="Now" eyebrow="DreamLayer" right={<StatusPill paused={paused} />} />

      <Animated.View style={[s.stage, mirror]}>
        <HaloMirror card={paused ? null : service.lastCard} />
        {!connected ? (
          <Tappable onPress={connect} style={s.pairChip}>
            <Text style={[typography.caption, { color: colors.accentMemory }]}>Halo not connected · tap to pair</Text>
          </Tappable>
        ) : (
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.lg }]}>
            Brain: {brainKind}{paused ? " · capture paused" : " · listening for what matters"}
          </Text>
        )}
      </Animated.View>

      {brief ? (
        <View style={s.briefCard}>
          <Text style={[typography.eyebrow, { color: colors.accentMemory, marginBottom: space.xs }]}>Morning brief</Text>
          <Text style={[typography.body, { color: colors.textPrimary }]}>{brief}</Text>
          <Tappable onPress={() => router.push("/brief")} style={{ marginTop: space.md }}>
            <Text style={[typography.caption, { color: colors.accentMemory }]}>Read the full brief →</Text>
          </Tappable>
        </View>
      ) : null}

      <View style={s.voiceRow}>
        <TextInput
          value={cmd}
          onChangeText={setCmd}
          placeholder="Say a command… “what did Marcus need?”"
          placeholderTextColor={colors.textSecondary}
          style={s.voiceInput}
          onSubmitEditing={doVoice}
          returnKeyType="send"
        />
        <Tappable onPress={doVoice} style={s.voiceBtn}>
          <Text style={[typography.body, { color: colors.background, fontWeight: "700" }]}>↳</Text>
        </Tappable>
      </View>
      {voiceOut ? (
        <Text style={[typography.caption, { color: colors.textSecondary, marginBottom: space.md }]}>{voiceOut}</Text>
      ) : null}

      <View style={s.actions}>
        <Tappable onPress={doBrief} style={[s.wide, s.actionGhost, { borderColor: colors.borderSubtle }]}>
          <Text style={[typography.body, { color: colors.accentMemory, fontWeight: "600" }]}>
            {briefing ? "Thinking…" : brief ? "Refresh brief" : "Morning brief"}
          </Text>
        </Tappable>
        <View style={s.actionRow}>
          <Tappable onPress={() => router.push("/brain")} style={[s.action, { backgroundColor: colors.accentMemory }]}>
            <Text style={[typography.body, { color: colors.background, fontWeight: "700" }]}>Ask your brain</Text>
          </Tappable>
          <Tappable
            onPress={togglePause}
            style={[s.action, s.actionGhost, { borderColor: paused ? colors.statusPaused : colors.borderSubtle }]}
          >
            <Text style={[typography.body, { color: paused ? colors.statusPaused : colors.textSecondary, fontWeight: "600" }]}>
              {paused ? "Resume memory" : "Pause capture"}
            </Text>
          </Tappable>
        </View>
      </View>
    </Screen>
  );
}

const s = StyleSheet.create({
  stage: { flex: 1, alignItems: "center", justifyContent: "center" },
  pairChip: {
    marginTop: space.xl,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.pill,
    paddingVertical: space.sm,
    paddingHorizontal: space.lg,
  },
  actions: { gap: space.md, paddingBottom: space.xl },
  actionRow: { flexDirection: "row", gap: space.md },
  action: { flex: 1, borderRadius: radius.pill, paddingVertical: space.lg, alignItems: "center" },
  wide: { borderRadius: radius.pill, paddingVertical: space.lg, alignItems: "center" },
  actionGhost: { backgroundColor: "transparent", borderWidth: 1 },
  briefCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: space.lg,
    marginBottom: space.md,
  },
  voiceRow: { flexDirection: "row", gap: space.sm, marginBottom: space.sm },
  voiceInput: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.pill,
    color: colors.textPrimary,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    fontSize: 15,
  },
  voiceBtn: {
    backgroundColor: colors.accentMemory,
    borderRadius: radius.pill,
    width: 48,
    alignItems: "center",
    justifyContent: "center",
  },
});
