import React, { useEffect, useState } from "react";
import { View, Text, TextInput, StyleSheet, Alert, ActivityIndicator } from "react-native";
import { useBrainStore, BrainMessage } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { Tappable } from "../src/ui/components/Tappable";
import { EmptyState } from "../src/ui/components/EmptyState";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";

/**
 * Messages — read your Messages & Mail hands-free and reply. The Mac mini
 * Brain is the bridge (that's where iMessage/Mail live); on the glasses you'd
 * read these as cards and dictate a reply. Here on the phone you tap a thread,
 * type (or dictate) a reply, and approve — nothing is ever sent silently.
 */
export default function Messages() {
  const macConnected = useBrainStore((s) => s.macMini.connected);
  const fetchMessages = useBrainStore((s) => s.fetchMessages);
  const sendReply = useBrainStore((s) => s.sendReply);

  const [items, setItems] = useState<BrainMessage[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [replyTo, setReplyTo] = useState<BrainMessage | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);

  const refresh = async (showLoading = true) => {
    if (showLoading) setLoading(true);
    const r = await fetchMessages();
    setItems(r.items);
    setEnabled(r.enabled);
    setLoading(false);
  };
  useEffect(() => {
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
      Alert.alert("Not sent", r.error || "Something went wrong.");
    }
  };

  return (
    <Screen>
      <ScreenHeader title="Messages" eyebrow="Hands-free" />

      {!macConnected ? (
        <EmptyState
          glyph="✉"
          title="Connect your Mac mini"
          hint="Your Messages & Mail live on your Mac. Pair it (Brain tab) so the Brain can relay them to your glasses and phone."
        />
      ) : !enabled ? (
        <EmptyState
          glyph="✉"
          title="Turn on message relay"
          hint="In the Brain panel on your Mac mini, enable “Read email & iMessage”. Then they show up here and on your glasses."
        />
      ) : loading ? (
        <ActivityIndicator color={colors.accentMemory} style={{ marginTop: space.huge }} />
      ) : items.length === 0 ? (
        <EmptyState glyph="✉" title="No recent messages" hint="Nothing to relay right now — new messages will appear here and on your glasses." />
      ) : (
        <>
          <Text style={[typography.caption, { color: colors.textSecondary, marginBottom: space.md }]}>
            Read on your glasses; tap here to reply. Nothing sends without your approval.
          </Text>
          {items.map((m, i) => {
            const tint = m.channel === "email" ? "#8FB8FF" : colors.accentMemory;
            const open = replyTo === m;
            return (
              <Card key={i} delay={i * 40} accent={tint} active={open} onPress={() => { setReplyTo(open ? null : m); setText(""); }}>
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
                          <Text style={[typography.body, { color: colors.background, fontWeight: "700" }]}>Approve &amp; send</Text>
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
