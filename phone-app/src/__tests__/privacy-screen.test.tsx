/**
 * The Privacy screen. What is under test is the refusals, not the layout:
 * no coordinates on screen, no consent the wearer did not read, no missing
 * recogniser dressed up as a switched-off one, and no unreachable Brain drawn
 * as a set of lowered shields.
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react-native";

import Privacy from "../../app/privacy";
import { usePrivacyStore, NO_BIOMETRIC, Biometric } from "../state/usePrivacyStore";
import { useBrainStore } from "../state/useBrainStore";

jest.mock("../services/location", () => ({ markHere: jest.fn(async () => true) }));

const FACES: Biometric = {
  enabled: true, model: true, consented: true, consentVersion: "2026-07-01",
  consentText: "Face recall stores a mathematical template of a face.",
  autoEnrol: false, enrolled: 4, unnamed: 1, ambient: true, available: true,
};
const VOICES: Biometric = {
  enabled: false, model: true, consented: false, consentVersion: "2026-06-02",
  consentText: "A voiceprint is the biometric itself.",
  autoEnrol: false, enrolled: 0, unnamed: 0, ambient: true, available: true,
};

function seed(over: Partial<ReturnType<typeof usePrivacyStore.getState>> = {}) {
  usePrivacyStore.setState({
    loaded: true, reachable: true, lastError: "",
    zones: [{ name: "the flat", radiusM: 150, inside: true }],
    maxZones: 8, hasFix: true, insideZone: "the flat", veiled: true,
    quietHours: "22:00-07:00", retentionDays: 30,
    faces: { ...FACES }, voices: { ...VOICES },
    refresh: jest.fn(async () => {}) as never,
    addZoneHere: jest.fn(async () => ({ ok: true, error: "" })) as never,
    removeZone: jest.fn(async () => true) as never,
    setQuietHours: jest.fn(async () => true) as never,
    setRetentionDays: jest.fn(async () => true) as never,
    setBiometric: jest.fn(async () => true) as never,
    setConsent: jest.fn(async () => true) as never,
    ...over,
  });
}

// `seed` is called ONCE per test, by the test itself. Seeding in `beforeEach`
// AND again in the body left the store written twice before a mount, and the
// second write raced the subscription: the screen came back empty. One write,
// one mount.
beforeEach(() => {
  useBrainStore.setState({
    macMini: { connected: true, url: "http://mac:8765", token: "t", relayUrl: "" },
  } as never);
});

describe("it never invents an answer", () => {
  it("says unpaired rather than drawing shields", async () => {
    seed();
    useBrainStore.setState({ macMini: { connected: false, url: "", token: "" } } as never);
    await render(<Privacy />);
    expect(screen.getByText("Connect your Mac mini")).toBeTruthy();
  });

  it("says unreachable, and that the Brain keeps doing what it was", async () => {
    seed({ reachable: false });
    await render(<Privacy />);
    expect(screen.getByText("Couldn’t reach your Brain")).toBeTruthy();
    expect(screen.getByText(/keeps whatever it was already doing/i)).toBeTruthy();
  });
});

describe("zones", () => {
  it("shows the zone by name, and that you are inside it", async () => {
    seed();
    await render(<Privacy />);
    expect(screen.getByText("the flat")).toBeTruthy();
    expect(screen.getByText(/You’re inside — capture suspended/)).toBeTruthy();
    expect(screen.getByText(/Capture suspended — you’re inside the flat/)).toBeTruthy();
  });

  it("puts no coordinate on screen", async () => {
    seed();
    /* Only the TEXT the wearer reads — the tree is full of unrelated decimals
       (dash arrays, gradient stops), and asserting over the whole serialised
       tree would pass or fail on the backdrop rather than on the zones. */
    const { toJSON } = await render(<Privacy />);
    const words: string[] = [];
    const walk = (n: any) => {
      if (typeof n === "string") { words.push(n); return; }
      if (Array.isArray(n)) { n.forEach(walk); return; }
      if (n && n.children) walk(n.children);
    };
    walk(toJSON() as never);
    const said = words.join(" ");
    expect(said).toContain("the flat");
    expect(said).not.toMatch(/-?\d{1,3}\.\d{4,}/);
  });



  it("explains the cap rather than failing silently at it", async () => {
    seed({
      maxZones: 2,
      zones: [
        { name: "a", radiusM: 100, inside: false },
        { name: "b", radiusM: 100, inside: false },
      ],
    });
    const r = await render(<Privacy />);
    expect(r.getByText(/2 zones is the limit/)).toBeTruthy();
  });
});

describe("biometrics", () => {
  it("renders the Brain's own consent words, not a paraphrase", async () => {
    seed();
    await render(<Privacy />);
    expect(screen.getByText(FACES.consentText)).toBeTruthy();
    expect(screen.getByText(VOICES.consentText)).toBeTruthy();
  });

  it("shows the accepted version alongside the words it belongs to", async () => {
    seed();
    await render(<Privacy />);
    expect(screen.getByText("AGREED · 2026-07-01")).toBeTruthy();
    expect(screen.getByText("READ THIS FIRST")).toBeTruthy();
  });

  it("will not let recognition be switched on before agreement", async () => {
    seed();
    await render(<Privacy />);
    expect(screen.getByLabelText("Recognise voices").props.disabled).toBe(true);
    expect(screen.getByText("Needs your agreement above.")).toBeTruthy();
  });

  it("says a missing recogniser is missing, not off", async () => {
    seed({ voices: { ...NO_BIOMETRIC } });
    await render(<Privacy />);
    expect(screen.getByText(/isn’t installed. This is not the same as it being/i)).toBeTruthy();
  });

  it("names what enrol-on-sight actually does", async () => {
    seed();
    await render(<Privacy />);
    // faces and voices both say it — they are the same bargain
    expect(screen.getAllByText(/You get the recall you wanted; they were never asked/).length).toBe(2);
  });

  it("cannot enrol on sight while recognition is off", async () => {
    seed();
    await render(<Privacy />);
    expect(screen.getByLabelText("Enrol voices on sight").props.disabled).toBe(true);
  });

  it("counts what is held, including who never gave a name", async () => {
    seed();
    await render(<Privacy />);
    const r = await render(<Privacy />);
    expect(r.getByText(/4 held, 1 of them unnamed/)).toBeTruthy();
  });

  it("explains a refused switch instead of leaving it looking broken", async () => {
    seed({ lastError: "consent-required" });
    await render(<Privacy />);
    expect(screen.getByText("NOT TURNED ON")).toBeTruthy();
  });
});

/* Last in the file, on purpose. The handler behind this button is async and
   settles three pieces of state across two awaits; the updates after the first
   await land outside RNTL's `act` wrapper, and a mount left in that state makes
   every LATER `render` in the same module come back empty. Wrapping the press
   keeps this test honest, and putting it last means a future regression in the
   wrapper cannot silently blank the tests below it — there are none. The logic
   itself (fresh fix, refusal without one, no nameless zone) is proved in
   privacy-store.test.ts, which needs no renderer at all. */
describe("the button is wired to the store", () => {
  it("asks the store to make a zone here, with the name that was typed", async () => {
    const addZoneHere = jest.fn(async () => ({ ok: true, error: "" }));
    seed({ addZoneHere: addZoneHere as never });
    await render(<Privacy />);
    await act(async () => {
      fireEvent.changeText(screen.getByLabelText("Zone name"), "the studio");
    });
    await act(async () => {
      fireEvent.press(screen.getByLabelText("Make here a private zone"));
    });
    expect(addZoneHere).toHaveBeenCalledWith("the studio");
  });
});
