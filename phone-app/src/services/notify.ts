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

let requested = false;

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
    } as never);
  } catch {
    /* channels unavailable (web/tests) — scheduling will still degrade safely */
  }
}

/** Present a local notification now. Silently no-ops without permission. */
export async function pushLocal(
  title: string,
  body: string,
  channel: NotifyChannel = "messages"
): Promise<void> {
  try {
    if (!(await ensurePermission())) return;
    await ensureChannel(channel);
    await Notifications.scheduleNotificationAsync({
      content: { title, body: (body || "").slice(0, 140) },
      // a channelId-only trigger = "present now, on this channel" on Android;
      // null = "present now" everywhere else
      trigger: isAndroid() ? ({ channelId: channel } as never) : null,
    });
  } catch {
    /* notifications unavailable (e.g. web) — ignore */
  }
}
