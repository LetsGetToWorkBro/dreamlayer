import React, { useEffect, useState } from "react";
import { View, Text, TextInput, StyleSheet, Alert, ActivityIndicator } from "react-native";
import { useBrainStore, BrainMessage } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { Tappable } from "../src/ui/components/Tappable";
import { EmptyState } from "../src/ui/components/EmptyState";
import { pushLocal } from "../src/services/notify";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";
import { t } from "../src/i18n";

/**
 * Messages — read your Messages & Mail hands-free and reply. The Mac mini
 * Brain is the bridge (that's where iMessage/Mail live); on the glasses you'd
 * read these as cards and dictate a reply. Here on the phone you tap a thread,
 * type (or dictate) a reply, and approve — nothing is ever sent silently.
 */
export default function Messages() {
  const macConnected = useBrainStore((s) => s.macMini.connected || s.demoMode);
  const fetchMessages = useBrainStore((s) => s.fetchMessages);
  const sendReply = useBrainStore((s) => s.sendReply);
  const getReplies = useBrainStore((s) => s.getReplies);

  const [items, setItems] = useState<BrainMessage[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [replyTo, setReplyTo] = useState<BrainMessage | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const openReply = async (m: BrainMessage) => {
    const open = replyTo === m;
    setReplyTo(open ? null : m);
    setText("");
    setSuggestions([]);
    if (!open && !m.from_me) {
      const s = await getReplies(m.subject ? `${m.subject}: ${m.text}` : m.text);
      setSuggestions(s);
    }
  };

  const notifyTexts = useBrainStore((s) => s.notifyTexts);
  const notifyEmails = useBrainStore((s) => s.notifyEmails);
  const lastSeen = React.useRef(0);
  const firstLoad = React.useRef(true);

  const refresh = async (showLoading = true) => {
    if (showLoading) setLoading(true);
    const r = await fetchMessages();
    const incoming = r.items.filter((m) => !m.from_me);
    const newest = incoming.reduce((mx, m) => Math.max(mx, m.ts || 0), 0);
    // mirror genuinely-new messages to a local notification (not the backlog)
    if (!firstLoad.current) {
      for (const m of incoming.filter((m) => (m.ts || 0) > lastSeen.current)) {
        const on = m.channel === "email" ? notifyEmails : notifyTexts;
        if (on) pushLocal(m.who, m.subject ? `${m.subject} — ${m.text}` : m.text);
      }
    }
    lastSeen.current = Math.max(lastSeen.current, newest);
    firstLoad.current = false;
    setItems(r.items);
    setEnabled(r.enabled);
    setLoading(false);
  };
  useEffect(() => {
    firstLoad.current = true;
    refresh();
    // live: pull the Brain's feed on a timer so new messages appear on their own
    const id = setInterval(() => refresh(false), 12000);
    return () => clearInterval(id);
  }, [macConnected]);

  const send = async () => {
    if (!replyTo || !text.trim()) return;
    setSending(true);
    const r = await sendReply({ channel: replyTo.channel, to: replyTo.who, text: text.trim() });
    setSending(false);
    if (r.ok) {
      Alert.alert("Sent", `Your ${replyTo.channel === "email" ? "email" : "reply"} to ${replyTo.who} was sent.`);
      setReplyTo(null);
      setText("");
      refresh();
    } else {
      Alert.alert(t("messages.notSent"), r.error || t("messages.sendFailed"));
    }
  };

  return (
    <Screen>
      <ScreenHeader title={t("messages.title")} eyebrow={t("messages.eyebrow")} />

      {!macConnected ? (
        <EmptyState
          glyph="✉"
          title={t("messages.connectMacTitle")}
          hint={t("messages.connectMacHint")}
        />
      ) : !enabled ? (
        <EmptyState
          glyph="✉"
          title={t("messages.relayOffTitle")}
          hint={t("messages.relayOffHint")}
        />
      ) : loading ? (
        <ActivityIndicator color={colors.accentMemory} style={{ marginTop: space.huge }} />
      ) : items.length === 0 ? (
        <EmptyState glyph="✉" title={t("messages.noneTitle")} hint={t("messages.noneHint")} />
      ) : (
        <>
          <Text style={[typography.caption, { color: colors.textSecondary, marginBottom: space.md }]}>
            Read on your glasses; tap here to reply. Nothing sends without your approval.
          </Text>
          {items.map((m, i) => {
            const tint = m.channel === "email" ? "#3D63C7" : colors.accentMemory;
            const open = replyTo === m;
            return (
              <Card key={i} delay={i * 40} accent={tint} active={open} onPress={() => openReply(m)}>
                <View style={s.row}>
                  <View style={[s.tag, { backgroundColor: tint }]} />
                  <View style={{ flex: 1 }}>
                    <View style={s.metaRow}>
                      <Text style={[typography.body, { color: colors.textPrimary, fontWeight: "600" }]}>
                        {m.from_me ? "You" : m.who}
                      </Text>
                      <Text style={[typography.eyebrow, { color: tint }]}>{m.channel}</Text>
                    </View>
                    <Text style={[typography.body, { color: colors.textSecondary, marginTop: 2 }]} numberOfLines={open ? undefined : 2}>
                      {m.subject ? m.subject + " — " + m.text : m.text}
                    </Text>
                  </View>
                </View>
                {open && !m.from_me && (
                  <View style={s.reply}>
                    {suggestions.length > 0 && (
                      <View style={s.chips}>
                        {suggestions.map((sug, k) => (
                          <Tappable key={k} onPress={() => setText(sug)} style={s.chip}>
                            <Text style={[typography.caption, { color: colors.accentMemory }]}>{sug}</Text>
                          </Tappable>
                        ))}
                      </View>
                    )}
                    <TextInput
                      value={text}
                      onChangeText={setText}
                      placeholder={`Reply to ${m.who}…  (on the glasses you'd dictate this)`}
                      placeholderTextColor={colors.textSecondary}
                      style={s.input}
                      multiline
                    />
                    <View style={s.replyActions}>
                      {sending ? (
                        <ActivityIndicator color={colors.accentMemory} />
                      ) : (
                        <Tappable onPress={send} style={[s.sendBtn, !text.trim() && { opacity: 0.4 }]} disabled={!text.trim()}>
                          <Text style={[typography.body, { color: "#FFFFFF", fontWeight: "700" }]}>{t("messages.approveSend")}</Text>
                        </Tappable>
                      )}
                    </View>
                  </View>
                )}
              </Card>
            );
          })}
        </>
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "stretch", gap: space.md },
  tag: { width: 3, borderRadius: radius.sm, alignSelf: "stretch" },
  metaRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  reply: { marginTop: space.md, borderTopWidth: 1, borderTopColor: colors.borderSubtle, paddingTop: space.md },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm, marginBottom: space.md },
  chip: {
    borderWidth: 1,
    borderColor: colors.accentMemory,
    borderRadius: radius.pill,
    paddingVertical: space.sm,
    paddingHorizontal: space.md,
  },
  input: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.sm,
    color: colors.textPrimary,
    paddingHorizontal: space.md,
    paddingVertical: space.md,
    minHeight: 60,
    fontSize: 15,
  },
  replyActions: { flexDirection: "row", justifyContent: "flex-end", marginTop: space.md, minHeight: 40, alignItems: "center" },
  sendBtn: { backgroundColor: colors.accentMemory, borderRadius: radius.pill, paddingVertical: space.md, paddingHorizontal: space.xl },
});
