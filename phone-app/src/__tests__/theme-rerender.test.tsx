/** Midnight Platinum, live: the whole point of the theme system is that a
 * module-level StyleSheet CANNOT go stale — flipping the store re-renders
 * every consumer with the other world's tokens, no remount, no reload. Pinned
 * here through a real primitive (Card, whose window face comes from a
 * makeThemedStyles sheet) and the useTheme() hook itself. */
import React from "react";
import { Text, View } from "react-native";
import { act, render, screen } from "@testing-library/react-native";

import { Card } from "../ui/components/Card";
import { useTheme } from "../ui/theme/useTheme";
import { useThemeStore } from "../state/useThemeStore";
import { platinum } from "../ui/theme/colors";
import { midnightTheme, platinumTheme } from "../ui/theme/themes";

jest.mock("../services/haptics", () => ({
  tapLight: jest.fn(),
  tapMedium: jest.fn(),
  play: jest.fn(),
}));

/** flatten a (possibly nested) RN style prop into one object */
function flat(style: unknown): Record<string, unknown> {
  if (Array.isArray(style)) return Object.assign({}, ...style.map(flat));
  return (style as Record<string, unknown>) ?? {};
}

beforeEach(() => {
  useThemeStore.setState({ mode: "platinum", hydrated: true });
});

afterAll(() => {
  useThemeStore.setState({ mode: "auto" });
});

describe("theme switching re-renders live", () => {
  it("Card's window face crosses from Platinum to Midnight without a remount", async () => {
    await render(
      <Card title="Window" shade={false}>
        <Text>body</Text>
      </Card>
    );
    const face = () => {
      // the framed window root is the ancestor View that carries the face color
      let node: any = screen.getByText("Window").parent;
      while (node) {
        const st = flat(node.props?.style);
        if (st.backgroundColor) return st.backgroundColor;
        node = node.parent;
      }
      return undefined;
    };
    expect(face()).toBe(platinum.face); // "#DDDDDD"

    await act(async () => {
      useThemeStore.getState().setMode("midnight");
    });
    expect(face()).toBe(midnightTheme.platinum.face); // "#3E4044"

    await act(async () => {
      useThemeStore.getState().setMode("platinum");
    });
    expect(face()).toBe(platinum.face);
  });

  it("useTheme() consumers flip with the store", async () => {
    function Probe() {
      const t = useTheme();
      return (
        <View>
          <Text testID="probe">{t.name}:{t.colors.textPrimary}</Text>
        </View>
      );
    }
    await render(<Probe />);
    expect(screen.getByTestId("probe").props.children.join("")).toBe(
      `platinum:${platinumTheme.colors.textPrimary}`
    );
    await act(async () => {
      useThemeStore.getState().setMode("midnight");
    });
    expect(screen.getByTestId("probe").props.children.join("")).toBe(
      `midnight:${midnightTheme.colors.textPrimary}`
    );
  });
});
