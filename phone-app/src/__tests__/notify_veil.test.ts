/**
 * Veil gate on local notifications (privacy audit 2026-07-17).
 *
 * app/messages.tsx mirrors each new incoming iMessage/email to a local
 * notification via pushLocal(sender, subject/text), and app/now.tsx mirrors the
 * synthesized morning brief via pushLocal(title, brief.text). Those render
 * recalled PERSONAL content onto the lock screen and into the notification log.
 * The only pre-existing guards were the notifyTexts/notifyEmails toggles (which
 * govern glasses pop-ups), NOT the privacy Veil — so a wearer who is incognito
 * or has the Veil up still leaked sender/subject/body/brief to the lock screen.
 *
 * The fix gates CONTENT at the single chokepoint (notify.pushLocal), reusing the
 * EXACT signal the relay enforces: useBrainStore.capturePaused (incognito forces
 * it on) OR useVitalsStore.veiled (a Veil raised on the glasses). While veiled it
 * posts a content-free placeholder (channel name, empty body); un-veiled it is
 * unchanged. Removing the gate makes the "no personal content" assertions fail.
 */

function makeNotifSpy() {
  return {
    requestPermissionsAsync: jest.fn(() => Promise.resolve({ status: "granted" })),
    getPermissionsAsync: jest.fn(() => Promise.resolve({ status: "granted" })),
    setNotificationChannelAsync: jest.fn(() => Promise.resolve()),
    scheduleNotificationAsync: jest.fn(() => Promise.resolve("id")),
    AndroidImportance: { DEFAULT: 3, HIGH: 4 },
    AndroidNotificationVisibility: { PUBLIC: 1, PRIVATE: 2, SECRET: 3 },
  };
}

/** Load notify AND the veil stores from the SAME freshly-reset module graph, so
 *  the store singletons the test drives are the very ones notify.pushLocal reads.
 *  (Mirrors the loader in notify_channels.test.ts.) */
function load(os: "ios" | "android" = "android") {
  jest.resetModules();
  const spy = makeNotifSpy();
  jest.doMock("react-native", () => ({ Platform: { OS: os } }), { virtual: true });
  jest.doMock("expo-notifications", () => spy, { virtual: true });
  jest.doMock("expo-localization", () => ({ getLocales: () => [{ languageCode: "en" }] }), {
    virtual: true,
  });
  const notify = require("../services/notify") as typeof import("../services/notify");
  const { useBrainStore } = require("../state/useBrainStore");
  const { useVitalsStore } = require("../state/useVitalsStore");
  useBrainStore.setState({ capturePaused: false, incognito: false });
  useVitalsStore.getState().reset();
  return { notify, spy, useBrainStore, useVitalsStore };
}

afterEach(() => {
  jest.dontMock("react-native");
  jest.dontMock("expo-notifications");
  jest.dontMock("expo-localization");
  jest.resetModules();
});

/** The content object handed to expo's scheduleNotificationAsync. */
function scheduledContent(spy: ReturnType<typeof makeNotifSpy>): { title?: string; body?: string } {
  expect(spy.scheduleNotificationAsync).toHaveBeenCalledTimes(1);
  const calls = spy.scheduleNotificationAsync.mock.calls as any[];
  return calls[0][0].content;
}

describe("the Veil strips personal content from local notifications", () => {
  it("incognito/capturePaused → a message carries NO sender/subject/body", async () => {
    const { notify, spy, useBrainStore } = load("android");
    // incognito forces capturePaused on synchronously — the phone-side Veil
    useBrainStore.setState({ incognito: true, capturePaused: true });

    await notify.pushLocal("Marcus", "Lease: sign the renewal by Friday", "messages");

    const c = scheduledContent(spy);
    expect(c.body).toBe(""); // no subject, no text
    expect(c.title).not.toBe("Marcus"); // the passed title is the SENDER — never leaked
    // nothing personal survives anywhere in the payload
    const blob = JSON.stringify(c);
    expect(blob).not.toContain("Marcus");
    expect(blob).not.toContain("Lease");
    expect(blob).not.toContain("Friday");
  });

  it("a Veil raised on the GLASSES (vitals.veiled) → the brief carries NO text", async () => {
    const { notify, spy, useBrainStore, useVitalsStore } = load("android");
    // capturePaused stays false; the glasses raised the Veil via telemetry
    useBrainStore.setState({ capturePaused: false });
    useVitalsStore.getState().ingest({ event: "PRIVACY_VEIL" });
    expect(useVitalsStore.getState().veiled).toBe(true);

    await notify.pushLocal("Morning brief", "You owe Dana $40; lunch with Priya at noon", "brief");

    const c = scheduledContent(spy);
    expect(c.body).toBe("");
    const blob = JSON.stringify(c);
    expect(blob).not.toContain("Dana");
    expect(blob).not.toContain("Priya");
    expect(blob).not.toContain("$40");
  });

  it("NOT veiled → the message carries sender + subject/body exactly as before", async () => {
    const { notify, spy, useBrainStore, useVitalsStore } = load("android");
    useBrainStore.setState({ capturePaused: false, incognito: false });
    expect(useVitalsStore.getState().veiled).toBe(false);

    await notify.pushLocal("Marcus", "lunch tomorrow?", "messages");

    const c = scheduledContent(spy);
    expect(c.title).toBe("Marcus");
    expect(c.body).toBe("lunch tomorrow?");
  });

  it("lifting the Veil (PRIVACY_RESUMED) restores full content", async () => {
    const { notify, spy, useVitalsStore } = load("android");
    useVitalsStore.getState().ingest({ event: "PRIVACY_VEIL" });
    useVitalsStore.getState().ingest({ event: "PRIVACY_RESUMED" });
    expect(useVitalsStore.getState().veiled).toBe(false);

    await notify.pushLocal("Priya", "here's the address", "messages");

    const c = scheduledContent(spy);
    expect(c.title).toBe("Priya");
    expect(c.body).toBe("here's the address");
  });
});
