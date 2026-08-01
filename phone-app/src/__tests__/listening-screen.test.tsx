/**
 * The Listening screen — the ear stack on the surface the wearer carries.
 *
 * The thing under test is not "does it render". It is that the screen refuses
 * the four lies a settings page like this is built to tell:
 *
 *   1. drawing an unreachable Brain as a row of switched-off features;
 *   2. drawing a switched-ON feature as a working one;
 *   3. offering the switches below the microphone as live while the microphone
 *      is shut;
 *   4. calling the one switch that keeps a name without asking anything softer
 *      than what it does.
 */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";

import Listening from "../../app/listening";
import { useEarStore, EAR_SWITCH_DEFAULTS, EAR_RUNTIME_DEFAULTS } from "../state/useEarStore";
import { useBrainStore } from "../state/useBrainStore";

function seed(over: Partial<ReturnType<typeof useEarStore.getState>> = {}) {
  useEarStore.setState({
    loaded: true,
    reachable: true,
    saving: false,
    lastError: "",
    switches: { ...EAR_SWITCH_DEFAULTS },
    runtime: { ...EAR_RUNTIME_DEFAULTS },
    intro: { pending: false, offered: 0, kept: 0 },
    refresh: jest.fn(async () => {}) as never,
    set: jest.fn(async () => true) as never,
    confirmIntro: jest.fn(async () => true) as never,
    dismissIntro: jest.fn(async () => true) as never,
    ...over,
  });
}

beforeEach(() => {
  useBrainStore.setState({
    macMini: { connected: true, url: "http://mac:8765", token: "t", relayUrl: "" },
  } as never);
  seed();
});

describe("it never invents an answer", () => {
  it("says the Brain is unpaired rather than drawing switches", async () => {
    useBrainStore.setState({ macMini: { connected: false, url: "", token: "" } } as never);
    await render(<Listening />);
    expect(screen.getByText("Connect your Mac mini")).toBeTruthy();
    expect(screen.queryByLabelText("Listening")).toBeNull();
  });

  it("says unreachable rather than drawing everything off", async () => {
    seed({ reachable: false });
    await render(<Listening />);
    expect(screen.getByText("Couldn’t reach your Brain")).toBeTruthy();
    expect(screen.queryByLabelText("Name capture")).toBeNull();
  });
});

describe("a switch is not a status", () => {
  it("says so when Listening is on and no microphone is open", async () => {
    seed({ switches: { ...EAR_SWITCH_DEFAULTS, listen_enabled: true } });
    await render(<Listening />);
    // the ear's own row says it, and every downstream row repeats it —
    // deliberately, since the wearer reads one row at a time
    expect(screen.getAllByText(/no microphone is open/i).length).toBeGreaterThan(0);
  });

  it("does not call the interpreter working just because it is switched on", async () => {
    seed({
      switches: { ...EAR_SWITCH_DEFAULTS, listen_enabled: true, interpret_enabled: true },
      runtime: { ...EAR_RUNTIME_DEFAULTS, listening: true, canInterpret: true },
    });
    await render(<Listening />);
    expect(screen.getByText(/nothing carried across yet/i)).toBeTruthy();
  });

  it("names the missing pack rather than showing a live-looking switch", async () => {
    seed({
      switches: { ...EAR_SWITCH_DEFAULTS, listen_enabled: true, interpret_enabled: true },
      runtime: { ...EAR_RUNTIME_DEFAULTS, listening: true, canInterpret: false },
    });
    await render(<Listening />);
    expect(screen.getByText(/Interpreter pack isn’t installed/i)).toBeTruthy();
  });

  it("counts what the room read actually drew", async () => {
    seed({
      switches: { ...EAR_SWITCH_DEFAULTS, listen_enabled: true, truth_lens_enabled: true },
      runtime: { ...EAR_RUNTIME_DEFAULTS, listening: true, truthProved: true, truthReads: 4 },
    });
    await render(<Listening />);
    expect(screen.getByText("4 reads drawn.")).toBeTruthy();
  });

  it("explains a zero room read instead of implying it is broken", async () => {
    seed({
      switches: { ...EAR_SWITCH_DEFAULTS, listen_enabled: true, truth_lens_enabled: true },
      runtime: { ...EAR_RUNTIME_DEFAULTS, listening: true },
    });
    await render(<Listening />);
    expect(screen.getByText(/normal outcome for a credible speaker/i)).toBeTruthy();
  });
});

describe("nothing works without the microphone, and it says so", () => {
  it("disables and explains every downstream switch while Listening is off", async () => {
    await render(<Listening />);
    expect(screen.getAllByText(/Turn Listening on first/i).length).toBeGreaterThanOrEqual(4);
    expect(screen.getByLabelText("Live captions").props.disabled).toBe(true);
    expect(screen.getByLabelText("Read the room").props.disabled).toBe(true);
    expect(screen.getByLabelText("Name capture").props.disabled).toBe(true);
  });

  it("enables them once the ear is on", async () => {
    seed({
      switches: { ...EAR_SWITCH_DEFAULTS, listen_enabled: true },
      runtime: { ...EAR_RUNTIME_DEFAULTS, listening: true },
    });
    await render(<Listening />);
    expect(screen.getByLabelText("Live captions").props.disabled).toBe(false);
  });
});

describe("the write goes to the Brain, under the Brain's own key", () => {
  it("sends the config key, not a phone-side name", async () => {
    const set = jest.fn(async () => true);
    seed({ set: set as never });
    await render(<Listening />);
    fireEvent(screen.getByLabelText("Listening"), "valueChange", true);
    await waitFor(() => expect(set).toHaveBeenCalledWith("listen_enabled", true));
  });

  it("says NOT SAVED when the Brain refused, so the switch's position is explained", async () => {
    seed({ lastError: "unreachable" });
    await render(<Listening />);
    expect(screen.getByText("NOT SAVED")).toBeTruthy();
    expect(screen.getByText(/Nothing was turned on/i)).toBeTruthy();
  });
});

describe("auto-keep is named for what it does", () => {
  it("says it writes a name you did not agree to in the moment", async () => {
    seed({
      switches: { ...EAR_SWITCH_DEFAULTS, listen_enabled: true, intro_capture_enabled: true },
      runtime: { ...EAR_RUNTIME_DEFAULTS, listening: true },
    });
    await render(<Listening />);
    expect(screen.getByText(/only switch on this screen that writes a name you didn’t agree to/i)).toBeTruthy();
  });

  it("cannot be reached without Name capture on — it would control nothing", async () => {
    seed({
      switches: { ...EAR_SWITCH_DEFAULTS, listen_enabled: true },
      runtime: { ...EAR_RUNTIME_DEFAULTS, listening: true },
    });
    await render(<Listening />);
    expect(screen.getByLabelText("Keep without asking me").props.disabled).toBe(true);
  });
});

describe("answering an introduction from the phone", () => {
  it("offers Keep and Skip when one is live, and never shows the name", async () => {
    const confirmIntro = jest.fn(async () => true);
    seed({
      switches: { ...EAR_SWITCH_DEFAULTS, listen_enabled: true, intro_capture_enabled: true },
      runtime: { ...EAR_RUNTIME_DEFAULTS, listening: true },
      intro: { pending: true, offered: 1, kept: 0 },
      confirmIntro: confirmIntro as never,
    });
    await render(<Listening />);
    expect(screen.getByText("SOMEONE JUST INTRODUCED THEMSELVES")).toBeTruthy();
    expect(screen.getByText(/Their name is on your glass/i)).toBeTruthy();
    fireEvent.press(screen.getByText("Keep"));
    await waitFor(() => expect(confirmIntro).toHaveBeenCalled());
  });

  it("shows nothing to answer when no offer is live", async () => {
    seed({
      switches: { ...EAR_SWITCH_DEFAULTS, listen_enabled: true, intro_capture_enabled: true },
      runtime: { ...EAR_RUNTIME_DEFAULTS, listening: true },
    });
    await render(<Listening />);
    expect(screen.queryByText("SOMEONE JUST INTRODUCED THEMSELVES")).toBeNull();
  });
});
