/**
 * Notifications: permission at first relevant use, and on Android every
 * notification rides a named, localized channel — the brief on its calm
 * default-importance channel, messages on the high one. The channel names
 * REUSE catalog keys the app already ships in 9 locales (now.morningBrief,
 * tabs.messages), so system settings read like DreamLayer with no new
 * strings to drift.
 */

function makeNotifSpy(granted = true) {
  return {
    requestPermissionsAsync: jest.fn(() => Promise.resolve({ status: granted ? "granted" : "denied" })),
    getPermissionsAsync: jest.fn(() => Promise.resolve({ status: granted ? "granted" : "denied" })),
    setNotificationChannelAsync: jest.fn(() => Promise.resolve()),
    scheduleNotificationAsync: jest.fn(() => Promise.resolve("id")),
    AndroidImportance: { DEFAULT: 3, HIGH: 4 },
  };
}

function loadNotify(os: "ios" | "android", spy: ReturnType<typeof makeNotifSpy>) {
  jest.resetModules();
  jest.doMock("react-native", () => ({ Platform: { OS: os } }), { virtual: true });
  jest.doMock("expo-notifications", () => spy, { virtual: true });
  // i18n pulls expo-localization at import time — pin it to English here
  jest.doMock("expo-localization", () => ({ getLocales: () => [{ languageCode: "en" }] }), {
    virtual: true,
  });
  return require("../services/notify") as typeof import("../services/notify");
}

afterEach(() => {
  jest.dontMock("react-native");
  jest.dontMock("expo-notifications");
  jest.dontMock("expo-localization");
  jest.resetModules();
});

describe("channels on Android", () => {
  it("the brief rides its own calm channel, named from the catalog", async () => {
    const spy = makeNotifSpy();
    const notify = loadNotify("android", spy);
    await notify.pushLocal("Morning brief", "3 things today", "brief");
    expect(spy.setNotificationChannelAsync).toHaveBeenCalledWith(
      "brief",
      expect.objectContaining({ name: "Morning brief", importance: 3 })
    );
    expect(spy.scheduleNotificationAsync).toHaveBeenCalledWith(
      expect.objectContaining({ trigger: { channelId: "brief" } })
    );
  });

  it("messages ride the high-importance channel by default", async () => {
    const spy = makeNotifSpy();
    const notify = loadNotify("android", spy);
    await notify.pushLocal("Marcus", "lunch tomorrow?");
    expect(spy.setNotificationChannelAsync).toHaveBeenCalledWith(
      "messages",
      expect.objectContaining({ name: "Messages", importance: 4 })
    );
    expect(spy.scheduleNotificationAsync).toHaveBeenCalledWith(
      expect.objectContaining({ trigger: { channelId: "messages" } })
    );
  });

  it("no permission -> no channel, no notification, no throw", async () => {
    const spy = makeNotifSpy(false);
    const notify = loadNotify("android", spy);
    await expect(notify.pushLocal("x", "y", "brief")).resolves.toBeUndefined();
    expect(spy.setNotificationChannelAsync).not.toHaveBeenCalled();
    expect(spy.scheduleNotificationAsync).not.toHaveBeenCalled();
  });

  it("permission is requested only once — first relevant use, then re-read", async () => {
    const spy = makeNotifSpy();
    const notify = loadNotify("android", spy);
    await notify.pushLocal("a", "b", "brief");
    await notify.pushLocal("c", "d", "messages");
    expect(spy.requestPermissionsAsync).toHaveBeenCalledTimes(1);
    expect(spy.getPermissionsAsync).toHaveBeenCalledTimes(1);
  });
});

describe("iOS stays exactly as shipped", () => {
  it("no channel calls, trigger null", async () => {
    const spy = makeNotifSpy();
    const notify = loadNotify("ios", spy);
    await notify.pushLocal("Morning brief", "3 things today", "brief");
    expect(spy.setNotificationChannelAsync).not.toHaveBeenCalled();
    expect(spy.scheduleNotificationAsync).toHaveBeenCalledWith(
      expect.objectContaining({ trigger: null })
    );
  });
});

describe("the channel table", () => {
  it("every channel points at a real catalog key in every locale", () => {
    const spy = makeNotifSpy();
    const notify = loadNotify("android", spy);
    const { translations } = require("../i18n/translations");
    for (const spec of Object.values(notify.CHANNELS)) {
      const [ns, key] = spec.nameKey.split(".");
      for (const [locale, tree] of Object.entries(translations) as [string, any][]) {
        expect(typeof tree[ns!]?.[key!]).toBe("string");
        expect((tree[ns!][key!] as string).length).toBeGreaterThan(0);
        void locale;
      }
    }
  });
});
