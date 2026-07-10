/**
 * Demo Mode fixtures — a coherent "day in the life" so the whole app is alive
 * with no glasses and no Mac Brain paired. These are clearly-labeled SAMPLE
 * data (a persistent "Sample data · Demo Mode" banner rides above them), used
 * only when the user taps "Explore with sample data". Nothing here touches the
 * network. The cast matches the seed memories (Marcus, Priya, the bike on 4th
 * & Alder, the café on Pine) so the surfaces tell one consistent story.
 *
 * Kept deliberately static (no Date.now()) so the demo reads the same every
 * launch and screenshots are stable for the store listing.
 */
import type {
  AskResult,
  CalendarEvent,
  RewindBlock,
  SagaSnapshot,
  JunoProfile,
  ActivityItem,
  LongBrief,
  BrainMessage,
} from "../state/useBrainStore";
import type { Person } from "../state/usePeopleStore";
import type { Memory } from "../state/useMemoryStore";

// A fixed "today, 10:00 AM" anchor so relative labels stay put across launches.
const T0 = 1_720_000_000_000; // arbitrary fixed epoch ms
const H = 3_600_000;

export const demoMemories: Memory[] = [
  { id: "m1", kind: "Promise", summary: "Send Marcus the signed lease by Friday", createdAt: "9:42 AM", ts: T0 - 2 * H },
  { id: "m2", kind: "Object", summary: "Snake plant on the sill — water every 2 weeks", createdAt: "9:10 AM", ts: T0 - 3 * H },
  { id: "m3", kind: "Person", summary: "Priya — you met at the Overpass show, she teaches ceramics", createdAt: "Yesterday, 7:20 PM", ts: T0 - 26 * H },
  { id: "m4", kind: "Place", summary: "Left the bike locked on 4th & Alder, north rack", createdAt: "Yesterday, 5:03 PM", ts: T0 - 28 * H },
  { id: "m5", kind: "Note", summary: "Café on Pine takes cash only — bring some next time", createdAt: "Mon, 1:15 PM", ts: T0 - 74 * H },
];

export const demoPeople: Person[] = [
  {
    contact_id: "p_marcus",
    name: "Marcus Reyes",
    relation: "Landlord",
    company: "Alder Property Co.",
    role: "Owner",
    last_met: "This morning",
    last_seen: "Coffee on Pine",
    notes: ["Wants the signed lease by Friday", "Prefers email over text"],
    debts: ["You owe Marcus: the signed lease"],
    topics: ["lease", "the unit on 4th"],
  },
  {
    contact_id: "p_priya",
    name: "Priya Anand",
    relation: "Met recently",
    company: "Overpass Studio",
    role: "Ceramics teacher",
    last_met: "Yesterday",
    last_seen: "The Overpass show",
    notes: ["Teaches a Thursday wheel-throwing class", "Offered you a studio guest pass"],
    debts: [],
    topics: ["ceramics", "the Overpass show"],
  },
  {
    contact_id: "p_dana",
    name: "Dana Osei",
    relation: "Coworker",
    company: "Northlight",
    role: "Design lead",
    last_met: "Monday",
    last_seen: "Standup",
    notes: ["Owes you the Q3 mockups", "Coffee, oat milk"],
    debts: ["Dana owes you: the Q3 mockups"],
    topics: ["Northlight redesign"],
  },
];

export const demoMessages: { items: BrainMessage[]; enabled: boolean } = {
  enabled: true,
  items: [
    { channel: "imessage", who: "Marcus Reyes", from_me: false, text: "Any chance you can get that lease over today?", ts: T0 - 40 * 60_000 },
    { channel: "imessage", who: "Priya Anand", from_me: false, text: "Loved meeting you! Class is Thursday 6pm if you want to come.", ts: T0 - 3 * H },
    { channel: "email", who: "Dana Osei", from_me: false, subject: "Q3 mockups", text: "Sending the first pass tonight — want your eyes before standup.", ts: T0 - 5 * H },
    { channel: "imessage", who: "You", from_me: true, text: "Sounds good — I'll bring cash for the café this time.", ts: T0 - 6 * H },
  ],
};

export const demoAsk = (query: string): AskResult => ({
  text:
    "From your memory: you promised Marcus the signed lease by Friday, and he texted this morning asking for it today. " +
    "The unsigned copy is in your Mail from Alder Property Co. (subject “Lease — 4th St”).",
  tier: "demo",
  sources: ["Promise · 9:42 AM", "Mail · Alder Property Co."],
});

export const demoVoice = (text: string): { intent: string; answer?: string; say?: string } => ({
  intent: "ask",
  answer:
    "You owe Marcus the signed lease by Friday. Want me to open the thread so you can send it?",
});

export const demoBrief = {
  text:
    "Good morning. Three things today: send Marcus the signed lease (he asked again this morning), " +
    "Priya’s ceramics class is tonight at 6, and Dana owes you the Q3 mockups before standup. " +
    "You left the bike on 4th & Alder.",
  missed: { texts: 2, emails: 1 },
};

export const demoLongBrief: LongBrief = {
  text: demoBrief.text,
  missed: demoBrief.missed,
  ts: T0,
  sections: [
    { title: "Promises", items: ["Send Marcus the signed lease — due Friday", "Return Dana’s book"] },
    { title: "Today", items: ["Priya’s ceramics class — 6:00 PM, Overpass Studio", "Standup — 10:00 AM"] },
    { title: "People", items: ["Marcus texted this morning", "Dana owes you the Q3 mockups"] },
    { title: "Left behind", items: ["Bike — 4th & Alder, north rack"] },
  ],
};

export const demoCalendar: CalendarEvent[] = [
  { title: "Standup", ts: T0, place: "Northlight", calendar: "Work", source: "demo" },
  { title: "Ceramics class with Priya", ts: T0 + 8 * H, place: "Overpass Studio", calendar: "Personal", source: "demo" },
  { title: "Lease due to Marcus", ts: T0 + 2 * 24 * H, calendar: "Personal", source: "demo" },
];

export const demoRewind: RewindBlock[] = [
  {
    hour: 9,
    label: "This morning",
    count: 3,
    items: [
      { ts: T0 - 2 * H, kind: "Promise", text: "Told Marcus you’d send the signed lease by Friday" },
      { ts: T0 - 3 * H, kind: "Object", text: "Noted the snake plant needs water every 2 weeks" },
      { ts: T0 - 40 * 60_000, kind: "Message", text: "Marcus: “Any chance you can get that lease over today?”" },
    ],
  },
  {
    hour: 19,
    label: "Yesterday evening",
    count: 2,
    items: [
      { ts: T0 - 26 * H, kind: "Person", text: "Met Priya at the Overpass show — she teaches ceramics" },
      { ts: T0 - 28 * H, kind: "Place", text: "Locked the bike on 4th & Alder, north rack" },
    ],
  },
];

export const demoProfile: JunoProfile = {
  name: "You",
  interests: ["Ceramics", "Cycling", "Specialty coffee", "Design"],
  people: ["Marcus Reyes", "Priya Anand", "Dana Osei"],
  preferences: ["Email over text for anything formal", "Cash for the café on Pine", "Oat milk"],
  observations: 42,
};

export const demoActivity: ActivityItem[] = [
  { ts: T0 - 30 * 60_000, kind: "ask", query: "what did Marcus need?", tier: "demo" },
  { ts: T0 - 2 * H, kind: "memory", text: "Saved a promise — lease to Marcus" },
  { ts: T0 - 26 * H, kind: "memory", text: "Met Priya at the Overpass show" },
];

export const demoReplies = (_text: string): string[] => [
  "On its way today — sending the signed lease now.",
  "Yes! I’ll have it to you before Friday.",
  "Can I get it to you tomorrow morning?",
];

export const demoSaga: SagaSnapshot = {
  xp: 1280,
  level: 7,
  max_level: 30,
  rank: "Cartographer",
  next_rank: { level: 10, title: "Wayfinder" },
  xp_to_next: 220,
  level_floor: 1200,
  level_ceil: 1500,
  unlocked_count: 9,
  total_count: 24,
  achievements: [
    { id: "first_memory", name: "First Light", what: "Kept your first memory", how: "Save anything worth keeping", category: "milestone", unlocked: true, progress: 1, target: 1, xp: 50 },
    { id: "ten_people", name: "People Person", what: "Remembered 10 people", how: "Meet and keep 10 introductions", category: "quest", unlocked: false, progress: 3, target: 10, xp: 150 },
    { id: "kept_promise", name: "True to Your Word", what: "Kept a promise on time", how: "Follow through before it slips", category: "milestone", unlocked: true, progress: 1, target: 1, xp: 100 },
    { id: "explorer", name: "Cartographer", what: "Saved 5 places", how: "Mark 5 spots worth remembering", category: "explore", unlocked: true, progress: 5, target: 5, xp: 120 },
  ],
};
