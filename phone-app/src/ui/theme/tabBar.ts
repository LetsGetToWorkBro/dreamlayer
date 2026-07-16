import { Platform } from "react-native";

/**
 * The control strip's box. iOS keeps the shipped numbers (90 tall, 30 under
 * the labels for the home indicator). Android is edge-to-edge on SDK 57+, so
 * the system bar under the strip varies — gesture nav insets ~16–24dp,
 * 3-button nav ~48dp: the strip grows with the reported inset while the
 * 62dp icon+label block stays constant. With the minimum inset (16) this is
 * exactly the 78/16 the app shipped with, so nothing moves on devices that
 * report no inset.
 */
export function tabBarMetrics(bottomInset: number): { height: number; paddingBottom: number } {
  if (Platform.OS === "ios") return { height: 90, paddingBottom: 30 };
  const inset = Math.max(Math.round(bottomInset), 16);
  return { height: 62 + inset, paddingBottom: inset };
}
