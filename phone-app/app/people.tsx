/**
 * People — your social memory, on the phone.
 *
 * Everyone you've met through the glasses (Social Lens): how you know them,
 * when you last saw them, your notes, and any open debts. Read here; edit a
 * note, fix a relationship, or mark a debt settled — or just talk to Oracle
 * ("remember Maya's a climber", "Marcus paid me back") and it shows up here.
 *
 * On your device only. Mirrors host-python via usePeopleStore.
 */
import React from "react";
import { View, Text, StyleSheet, TextInput, Pressable } from "react-native";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { Tappable } from "../src/ui/components/Tappable";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";
import { useBrainStore } from "../src/state/useBrainStore";
import { usePeopleStore, Person } from "../src/state/usePeopleStore";

export default function People() {
  const macConnected = useBrainStore((s) => s.macMini.connected);
  const people = usePeopleStore((s) => s.people);
  const loading = usePeopleStore((s) => s.loading);
  const loaded = usePeopleStore((s) => s.loaded);
  const fetchPeople = usePeopleStore((s) => s.fetchPeople);

  const [query, setQuery] = React.useState("");
  const [openId, setOpenId] = React.useState<string | null>(null);

  React.useEffect(() => {
    fetchPeople();
  }, [macConnected, fetchPeople]);

  const q = query.trim().toLowerCase();
  const list = people.filter(
    (p) => !q || `${p.name} ${p.relation} ${p.notes.join(" ")}`.toLowerCase().includes(q),
  );

  return (
    <Screen>
      <ScreenHeader
        title="People"
        eyebrow="Who you've met"
        subtitle="Your own contacts — names, notes, and debts, on your device."
      />

      {!macConnected ? (
        <Card>
          <Text style={[typography.body, { color: colors.textPrimary }]}>Connect your Brain to see your people.</Text>
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.xs }]}>
            The names you're told and the notes you jot on the glasses sync here.
          </Text>
        </Card>
      ) : (
        <TextInput
          style={s.search}
          placeholder="Search people…"
          placeholderTextColor={colors.statusPaused}
          value={query}
          onChangeText={setQuery}
          autoCapitalize="none"
        />
      )}

      {macConnected &&
        (list.length === 0 ? (
          <EmptyState
            title={loading || !loaded ? "Loading…" : "No one yet"}
            hint={
              loading || !loaded
                ? "Fetching your people."
                : "Meet someone and their card shows up here."
            }
          />
        ) : (
          list.map((p, i) => (
            <PersonCard
              key={p.contact_id || p.name}
              person={p}
              delay={i * 40}
              open={openId === p.contact_id}
              onToggle={() => setOpenId(openId === p.contact_id ? null : p.contact_id)}
            />
          ))
        ))}

      <Text style={[typography.caption, s.hint]}>
        Private by architecture — your own contacts only, never a stranger lookup.
      </Text>
    </Screen>
  );
}

function PersonCard({
  person, open, onToggle, delay,
}: {
  person: Person;
  open: boolean;
  onToggle: () => void;
  delay: number;
}) {
  const addNote = usePeopleStore((s) => s.addNote);
  const removeNote = usePeopleStore((s) => s.removeNote);
  const settle = usePeopleStore((s) => s.settle);
  const [draft, setDraft] = React.useState("");

  const sub = [person.relation, person.company || person.role, person.last_seen && `last seen ${person.last_seen}`]
    .filter(Boolean)
    .join("  ·  ");

  const submit = () => {
    const t = draft.trim();
    if (!t) return;
    setDraft("");
    addNote(person.contact_id, t);
  };

  return (
    <Card delay={delay}>
      <Tappable onPress={onToggle}>
        <View style={s.rowTop}>
          <View style={s.avatar}>
            <Text style={s.avatarText}>{(person.name[0] || "?").toUpperCase()}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={[typography.body, { color: colors.textPrimary, fontWeight: "700" }]}>{person.name}</Text>
            {sub ? <Text style={s.sub}>{sub}</Text> : null}
          </View>
          {person.debts.length ? (
            <View style={s.debtPill}>
              <Text style={s.debtPillText}>{person.debts.length}</Text>
            </View>
          ) : null}
        </View>
      </Tappable>

      {/* debts always visible — they matter */}
      {person.debts.length ? (
        <View style={s.debtBox}>
          {person.debts.map((d, i) => (
            <Text key={i} style={s.debtLine}>
              • {d}
            </Text>
          ))}
          <Tappable onPress={() => settle(person.contact_id)} style={s.settleBtn}>
            <Text style={s.settleText}>Settle up</Text>
          </Tappable>
        </View>
      ) : null}

      {open && (
        <View style={s.expand}>
          {person.notes.length ? (
            person.notes.map((n, i) => (
              <View key={i} style={s.noteRow}>
                <Text style={[typography.body, { color: colors.textSecondary, flex: 1 }]}>“{n}”</Text>
                <Tappable onPress={() => removeNote(person.contact_id, n)} hitSlop={8}>
                  <Text style={s.remove}>✕</Text>
                </Tappable>
              </View>
            ))
          ) : (
            <Text style={[typography.caption, { color: colors.statusPaused }]}>No notes yet.</Text>
          )}
          {person.topics.length ? (
            <Text style={[typography.caption, { color: colors.statusPaused, marginTop: space.xs }]}>
              talked about {person.topics.slice(0, 3).join(", ")}
            </Text>
          ) : null}
          <View style={s.addRow}>
            <TextInput
              style={s.noteInput}
              placeholder="Add a note…"
              placeholderTextColor={colors.statusPaused}
              value={draft}
              onChangeText={setDraft}
              onSubmitEditing={submit}
              returnKeyType="done"
            />
            <Tappable style={[s.addBtn, !draft.trim() && { opacity: 0.4 }]} onPress={submit} disabled={!draft.trim()}>
              <Text style={s.addBtnText}>Add</Text>
            </Tappable>
          </View>
        </View>
      )}
    </Card>
  );
}

const s = StyleSheet.create({
  search: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: radius.pill,
    color: colors.textPrimary,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    marginBottom: space.md,
  },
  rowTop: { flexDirection: "row", alignItems: "center", gap: space.md },
  avatar: {
    width: 42, height: 42, borderRadius: 21, alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(47,212,196,0.12)", borderWidth: 1, borderColor: "rgba(47,212,196,0.3)",
  },
  avatarText: { color: colors.accentMemory, fontWeight: "800", fontSize: 18 },
  sub: { color: colors.textSecondary, fontSize: 13, marginTop: 2 },
  debtPill: {
    minWidth: 24, height: 24, borderRadius: 12, paddingHorizontal: 6,
    alignItems: "center", justifyContent: "center", backgroundColor: "rgba(224,107,82,0.18)",
    borderWidth: 1, borderColor: "rgba(224,107,82,0.5)",
  },
  debtPillText: { color: colors.accentAttention, fontSize: 12, fontWeight: "700" },
  debtBox: {
    marginTop: space.md, padding: space.md, borderRadius: radius.md,
    backgroundColor: "rgba(224,107,82,0.08)", borderWidth: 1, borderColor: "rgba(224,107,82,0.25)",
  },
  debtLine: { color: colors.accentAttention, fontSize: 14, marginBottom: 2 },
  settleBtn: { alignSelf: "flex-start", marginTop: space.sm },
  settleText: { color: colors.accentMemory, fontWeight: "600", fontSize: 13 },
  expand: { marginTop: space.md, borderTopWidth: 1, borderTopColor: colors.borderSubtle, paddingTop: space.md },
  noteRow: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingVertical: 3 },
  remove: { color: colors.statusPaused, fontSize: 15, paddingHorizontal: 4 },
  addRow: { flexDirection: "row", gap: space.sm, marginTop: space.md, alignItems: "center" },
  noteInput: {
    flex: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.borderSubtle,
    borderRadius: radius.pill, color: colors.textPrimary, paddingHorizontal: space.lg, paddingVertical: space.sm,
  },
  addBtn: { backgroundColor: colors.accentMemory, borderRadius: radius.pill, paddingHorizontal: space.lg, paddingVertical: space.sm },
  addBtnText: { color: "#00201C", fontWeight: "700" },
  hint: { color: colors.statusPaused, marginTop: space.md, textAlign: "center" },
});
