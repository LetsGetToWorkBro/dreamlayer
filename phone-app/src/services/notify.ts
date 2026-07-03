/**
 * notify.ts — mirror a glasses pop-up to an iOS/Android local notification, so
 * you catch a text or event even without the Halo on. Local only (no server
 * push): the app schedules it the moment it sees something new.
 */
import * as Notifications from "expo-notifications";

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

/** Present a local notification now. Silently no-ops without permission. */
export async function pushLocal(title: string, body: string): Promise<void> {
  try {
    if (!(await ensurePermission())) return;
    await Notifications.scheduleNotificationAsync({
      content: { title, body: (body || "").slice(0, 140) },
      trigger: null,
    });
  } catch {
    /* notifications unavailable (e.g. web) — ignore */
  }
}
