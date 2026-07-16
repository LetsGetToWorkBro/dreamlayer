import React from "react";
import { Animated, View, Text, TextInput, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { useHaloStore } from "../src/state/useHaloStore";
import { useBrainStore } from "../src/state/useBrainStore";
import { useMemoryStore } from "../src/state/useMemoryStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { HaloMirror } from "../src/ui/components/HaloMirror";
import { StatusPill } from "../src/ui/components/StatusPill";
import { Card } from "../src/ui/components/Card";
import { Tappable } from "../src/ui/components/Tappable";
import { useEntrance } from "../src/ui/anim";
import { colors, platinum } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";
import { pushLocal } from "../src/services/notify";
import { playListen } from "../src/services/sound";
import { t } from "../src/i18n";

/** A beveled platinum quick-action tile for the dashboard. */
function QuickAction({ label, onPress, tint }: { label: string; onPress: () => void; tint?: string }) {
  return (
    <Tappable onPress={onPress} style={s.quickBtn}>
      <Text
        style={[typography.body, { fontSize: 12.5, color: tint ?? colors.textPrimary, fontWeight: "600" }]}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.8}
      >
        {label}
      </Text>
    </Tappable>
  );
}

export default function Now() {
  const router = useRouter();
  const { paused, connected, togglePause, connect, service } = useHaloStore();
  const macConnected = useBrainStore((s) => s.macMini.connected || s.demoMode);
  const brainKind = macConnected ? "Mac mini" : t("now.phone");
  const getBrief = useBrainStore((s) => s.getBrief);
  const getLatestBrief = useBrainStore((s) => s.getLatestBrief);
  const sendVoice = useBrainStore((s) => s.sendVoice);
  const getCalendar = useBrainStore((s) => s.getCalendar);
  const addEventFn = useBrainStore((s) => s.addEvent);
  const syncCalendarFn = useBrainStore((s) => s.syncCalendar);
  const memories = useMemoryStore((s) => s.memories);
  const mirror = useEntrance(60);
  const [brief, setBrief] = React.useState<string | null>(null);
  const [briefing, setBriefing] = React.useState(false);
  const [cmd, setCmd] = React.useState("");
  const [voiceOut, setVoiceOut] = React.useState<string | null>(null);
  const briefSeen = React.useRef(0);

  const [events, setEvents] = React.useState<{ title: string; ts: number; place?: string; source?: string; calendar?: string }[]>([]);
  const [syncing, setSyncing] = React.useState(false);
  const [evTitle, setEvTitle] = React.useState("");

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
        playListen(); // Juno: "Listen!" — a fresh brief just landed
        pushLocal(t("now.morningBrief"), b.text);
      }
    };
    pull();
    const id = setInterval(pull, 90_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [macConnected, getLatestBrief]);

  // the day's agenda, when a Mac mini brain (or demo) can serve it
  React.useEffect(() => {
    if (macConnected) getCalendar().then(setEvents);
  }, [macConnected, getCalendar]);

  const doBrief = async () => {
    setBriefing(true);
    const r = await getBrief();
    setBrief(r?.text ?? t("now.briefFallback"));
    setBriefing(false);
  };

  const doVoice = async () => {
    if (!cmd.trim()) return;
    const r = await sendVoice(cmd.trim());
    setCmd("");
    if (r.intent === "brief") setBrief(r.text ?? "");
    else if (r.answer) setVoiceOut(r.answer);
    else if (r.say) setVoiceOut(r.say); // timers, notes, debts, meet — Juno's confirmation
    else if (r.intent === "reply") setVoiceOut(t("now.replyPreview", { to: r.to, text: r.text }));
    else setVoiceOut(`(${r.intent})`);
  };

  const addEvent = async () => {
    if (!evTitle.trim()) return;
    const items = await addEventFn({ title: evTitle.trim(), ts: Date.now() / 1000 + 3600 });
    setEvents(items);
    setEvTitle("");
  };
  const syncCalendar = async () => {
    setSyncing(true);
    const items = await syncCalendarFn();
    setEvents(items);
    setSyncing(false);
  };

  const recent = memories.slice(0, 3);

  return (
    <Screen>
      <ScreenHeader title={t("now.title")} eyebrow="DreamLayer" right={<StatusPill paused={paused} />} />

      <Animated.View style={[s.stage, mirror]}>
        <HaloMirror card={paused ? null : service.lastCard} />
        {!connected ? (
          <Tappable onPress={connect} style={s.pairChip}>
            <Text style={[typography.caption, { color: colors.accentMemory }]}>{t("now.notConnected")}</Text>
          </Tappable>
        ) : (
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.lg }]}>
            {t("now.brainLabel", { kind: brainKind })}{paused ? t("now.capturePaused") : t("now.listening")}
          </Text>
        )}
      </Animated.View>

      {/* ask Juno */}
      <View style={s.voiceRow}>
        <TextInput
          value={cmd}
          onChangeText={setCmd}
          placeholder={t("now.commandPlaceholder")}
          placeholderTextColor={colors.textSecondary}
          style={s.voiceInput}
          onSubmitEditing={doVoice}
          returnKeyType="send"
        />
        <Tappable onPress={doVoice} style={s.voiceBtn} accessibilityLabel={t("now.ask")}>
          <Text style={[typography.body, { color: "#FFFFFF", fontWeight: "700" }]}>↳</Text>
        </Tappable>
      </View>
      {voiceOut ? (
        <Text style={[typography.caption, { color: colors.textSecondary, marginBottom: space.md }]}>{voiceOut}</Text>
      ) : null}

      {/* quick actions */}
      <View style={s.quick}>
        <QuickAction label="Look" onPress={() => router.push("/look")} />
        <QuickAction label={briefing ? "…" : brief ? t("now.refreshBrief") : t("now.morningBrief")} onPress={doBrief} />
        <QuickAction
          label={paused ? t("now.resume") : t("now.pause")}
          onPress={togglePause}
          tint={paused ? colors.statusPaused : colors.textSecondary}
        />
      </View>

      {brief ? (
        <Card title={t("now.morningBrief")}>
          <Text style={[typography.body, { color: colors.textPrimary }]}>{brief}</Text>
          <Tappable onPress={() => router.push("/brief")} style={{ marginTop: space.md }}>
            <Text style={[typography.caption, { color: colors.accentMemory }]}>{t("now.readFull")}</Text>
          </Tappable>
        </Card>
      ) : null}

      {/* the day's agenda — a real Platinum window (tap the bar to WindowShade) */}
      {macConnected ? (
        <Card
          title={t("brain.upcoming")}
          titleRight={
            <Tappable onPress={syncCalendar} haptic={false} style={s.barChip}>
              <Text style={[typography.caption, { color: colors.accentMemory, opacity: 1 }]}>
                {syncing ? "…" : "Sync"}
              </Text>
            </Tappable>
          }
        >
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
              style={s.voiceInput}
              onSubmitEditing={addEvent}
            />
            <Tappable onPress={addEvent} style={s.voiceBtn} accessibilityLabel={t("brain.add")}>
              <Text style={[typography.body, { color: "#FFFFFF", fontWeight: "700" }]}>＋</Text>
            </Tappable>
          </View>
        </Card>
      ) : null}

      {/* recent memories — a peek into the Memories tab, in its own window */}
      {recent.length ? (
        <Card
          title="Recent memories"
          titleRight={
            <Tappable onPress={() => router.push("/memories")} haptic={false} style={s.barChip}>
              <Text style={[typography.caption, { color: colors.accentMemory, opacity: 1 }]}>See all</Text>
            </Tappable>
          }
        >
          {recent.map((m, i) => (
            <View key={m.id} style={[s.memRow, i === recent.length - 1 ? s.memRowLast : null]}>
              <View style={s.memTag} />
              <View style={{ flex: 1 }}>
                <Text style={[typography.body, { color: colors.textPrimary }]} numberOfLines={2}>{m.summary}</Text>
                <Text style={[typography.caption, { color: colors.textSecondary }]}>{m.kind}{m.createdAt ? "  ·  " + m.createdAt : ""}</Text>
              </View>
            </View>
          ))}
        </Card>
      ) : null}

      <View style={{ height: space.xl }} />
    </Screen>
  );
}

const s = StyleSheet.create({
  stage: { minHeight: 260, alignItems: "center", justifyContent: "center", marginBottom: space.lg },
  pairChip: {
    marginTop: space.xl,
    backgroundColor: platinum.face,
    borderWidth: 1,
    borderColor: platinum.frame,
    borderRadius: 6,
    paddingVertical: space.sm,
    paddingHorizontal: space.lg,
  },
  // quick-action tile row
  quick: { flexDirection: "row", gap: space.sm, marginBottom: space.lg },
  quickBtn: {
    flex: 1,
    borderRadius: 8,
    paddingVertical: space.md,
    alignItems: "center",
    backgroundColor: platinum.face,
    borderWidth: 1.5,
    borderTopColor: platinum.hi,
    borderLeftColor: platinum.hi,
    borderBottomColor: platinum.sh,
    borderRightColor: platinum.sh,
  },
  // a small platinum chip so a title-bar action stays legible over pinstripes
  barChip: {
    backgroundColor: platinum.face,
    borderRadius: 3,
    borderWidth: 1,
    borderColor: platinum.sh,
    paddingHorizontal: 6,
    paddingVertical: 1,
  },
  voiceRow: { flexDirection: "row", gap: space.sm, marginBottom: space.sm },
  voiceInput: {
    flex: 1,
    backgroundColor: platinum.well,
    borderWidth: 1,
    borderColor: platinum.frame,
    borderRadius: 6,
    color: colors.textPrimary,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    fontSize: 15,
  },
  voiceBtn: {
    backgroundColor: colors.accentMemory,
    borderRadius: 6,
    borderWidth: 1.5,
    borderColor: platinum.frame,
    width: 48,
    alignItems: "center",
    justifyContent: "center",
  },
  evRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 8, gap: 8 },
  evAdd: { flexDirection: "row", gap: space.sm, alignItems: "center", marginTop: space.sm },
  memRow: { flexDirection: "row", alignItems: "flex-start", gap: space.md, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#C4C4C4" },
  memRowLast: { borderBottomWidth: 0 },
  memTag: { width: 8, height: 8, borderRadius: 4, marginTop: 6, backgroundColor: colors.accentMemory, borderWidth: 0.5, borderColor: "rgba(0,0,0,0.35)" },
});
