/**
 * notify.ts — mirror a glasses pop-up to an iOS/Android local notification, so
 * you catch a text or event even without the Halo on. Local only (no server
 * push): the app schedules it the moment it sees something new.
 *
 * Permission is requested at the FIRST relevant use (a brief landing, a
 * message arriving) — never at app launch. On Android 8+ every notification
 * needs a channel; ours are named in the product's voice and reuse the
 * localized strings the user already knows from the app (the "Morning brief"
 * card, the Messages tab), so the system settings page reads like DreamLayer.
 * The small icon + teal accent come from app.json (withAndroidNotificationBrand).
 */
import * as Notifications from "expo-notifications";
import { t } from "../i18n";
import { useBrainStore } from "../state/useBrainStore";
import { useVitalsStore } from "../state/useVitalsStore";

let requested = false;

/** Is the Veil up right now? This is the SAME composite signal the relay
 *  chokepoint enforces (lensRelay.captureSuppressed / useBrainStore.veilClosed):
 *  the phone/session paused capture (capturePaused, which local incognito forces
 *  on synchronously) OR the glasses raised the Veil (PRIVACY_VEIL telemetry →
 *  useVitalsStore.veiled). While it's up, recalled personal content must not
 *  reach a local notification (lock screen / notification log). */
function veiled(): boolean {
  const b = useBrainStore.getState();
  // Fail-closed before the persisted state hydrates: at cold start capturePaused
  // defaults false, so a wearer who left incognito/the Veil ON last session would
  // briefly read as un-veiled and leak content to the lock screen. Until hydrate()
  // restores the real flags (sets `hydrated`), treat the session as veiled
  // (refute 2026-07-17).
  if (!b.hydrated) return true;
  return b.capturePaused || useVitalsStore.getState().veiled;
}

export async function ensurePermission(): Promise<boolean> {
  try {
    if (!requested) {
      requested = true;
      const { status } = await Notifications.requestPermissionsAsync();
      return status === "granted";
    }
    const { status } = await Notifications.getPermissionsAsync();
    return status === "granted";
  } catch {
    return false;
  }
}

/** The product's notification channels. brief = the morning paper (default
 * importance, no urgency); messages = a person talking to you (high). */
export type NotifyChannel = "brief" | "messages";

export const CHANNELS: Record<
  NotifyChannel,
  { nameKey: string; importance: "default" | "high" }
> = {
  brief: { nameKey: "now.morningBrief", importance: "default" },
  messages: { nameKey: "tabs.messages", importance: "high" },
};

function isAndroid(): boolean {
  try {
    return require("react-native").Platform?.OS === "android";
  } catch {
    return false;
  }
}

/** Create/refresh the channel (idempotent; re-running updates the localized
 * name after a language change). No-op off Android. */
export async function ensureChannel(channel: NotifyChannel): Promise<void> {
  if (!isAndroid()) return;
  try {
    const spec = CHANNELS[channel];
    const importance =
      spec.importance === "high"
        ? Notifications.AndroidImportance?.HIGH
        : Notifications.AndroidImportance?.DEFAULT;
    await Notifications.setNotificationChannelAsync(channel, {
      name: t(spec.nameKey),
      importance,
      // the brand teal on the notification LED, matching the small-icon accent
      lightColor: "#0B6B52",
      // Defense in depth: these channels carry personal content (a sender/subject,
      // the synthesized brief). PRIVATE keeps the notification on the lock screen
      // but lets the OS redact its content on a SECURE lock screen — the correct
      // posture for personal channels, and identical to today when the phone is
      // unlocked. The veil gate in pushLocal is the actual leak-closer; this
      // narrows the blast radius if content ever slips through.
      lockscreenVisibility: Notifications.AndroidNotificationVisibility?.PRIVATE,
    } as never);
  } catch {
    /* channels unavailable (web/tests) — scheduling will still degrade safely */
  }
}

/** Present a local notification now. Silently no-ops without permission.
 *
 *  Veil gate (single chokepoint — every caller, present and future, is covered
 *  here rather than at each call-site): message/brief notifications render
 *  recalled personal content (sender + subject/body, the synthesized brief). If
 *  they fired while the wearer is incognito or the Veil is up, that content would
 *  land on the Android/iOS lock screen and persist in the notification log during
 *  a session the wearer set to private. So while `veiled()`, we still post a
 *  notification (so the wearer isn't silently cut off from "something arrived"),
 *  but strip it to a content-free placeholder: the channel's own localized name
 *  as the title and an EMPTY body — no sender, no subject, no text, no brief.
 *  Nothing personal reaches the lock screen or log. Normal (non-veiled) posting
 *  is byte-for-byte unchanged. */
export async function pushLocal(
  title: string,
  body: string,
  channel: NotifyChannel = "messages"
): Promise<void> {
  try {
    if (!(await ensurePermission())) return;
    await ensureChannel(channel);
    const content = veiled()
      ? // content-free placeholder: the passed title is the SENDER for messages,
        // so it can't be reused — fall back to the generic, localized channel name.
        { title: t(CHANNELS[channel].nameKey), body: "" }
      : { title, body: (body || "").slice(0, 140) };
    await Notifications.scheduleNotificationAsync({
      content,
      // a channelId-only trigger = "present now, on this channel" on Android;
      // null = "present now" everywhere else
      trigger: isAndroid() ? ({ channelId: channel } as never) : null,
    });
  } catch {
    /* notifications unavailable (e.g. web) — ignore */
  }
}
