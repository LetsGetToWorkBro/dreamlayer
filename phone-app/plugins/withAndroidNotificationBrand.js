/**
 * withAndroidNotificationBrand — the Android half of the expo-notifications
 * config plugin, and only that half.
 *
 * The stock ["expo-notifications", {...}] plugin also runs an iOS mod that
 * writes the `aps-environment` push entitlement into the app. DreamLayer's
 * shipped iOS app has NO capabilities on its App ID (see SUBMIT.md §2) and
 * no push server — adding that entitlement would change iOS provisioning for
 * a purely Android feature. So we apply the packaged Android sub-plugin
 * directly: it renders the status-bar small icon (white-on-transparent
 * drawable at every dpi) and the brand accent color used to tint it.
 *
 * Channels themselves are created at runtime in src/services/notify.ts.
 */
const {
  withNotificationsAndroid,
} = require("expo-notifications/plugin/build/withNotificationsAndroid");

module.exports = (config, props) => withNotificationsAndroid(config, props ?? {});
