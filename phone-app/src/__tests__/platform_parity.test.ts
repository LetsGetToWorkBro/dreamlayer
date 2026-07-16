/**
 * Android/iOS parity — the platform branches are tiny, so pin each one:
 *  - hardShadow/softShadow render the SAME geometry per platform (iOS via
 *    shadow*, Android via boxShadow — never the soft elevation blob).
 *  - the tab strip keeps iOS's shipped box and grows with Android's system
 *    inset (gesture pill vs 3-button nav) without moving the icon block.
 * Platform.OS is swapped per test via jest.doMock + isolated requires.
 */

function withPlatform<T>(os: "ios" | "android", load: () => T): T {
  let out!: T;
  jest.isolateModules(() => {
    jest.doMock("react-native", () => ({
      Platform: { OS: os, select: (o: any) => (os in o ? o[os] : o.default) },
    }));
    out = load();
  });
  jest.dontMock("react-native");
  return out;
}

describe("hardShadow — the Platinum drop shadow", () => {
  it("iOS keeps the exact shadow* the app shipped with", () => {
    const { hardShadow } = withPlatform("ios", () => require("../ui/theme/shadow"));
    expect(hardShadow(2, 3, 0.34)).toEqual({
      shadowColor: "#000000",
      shadowOffset: { width: 2, height: 3 },
      shadowOpacity: 0.34,
      shadowRadius: 0,
    });
  });

  it("Android draws the same crisp offset with boxShadow — no elevation blob", () => {
    const { hardShadow } = withPlatform("android", () => require("../ui/theme/shadow"));
    const style = hardShadow(2, 3, 0.34);
    expect(style).toEqual({ boxShadow: "2px 3px 0px rgba(0,0,0,0.34)" });
    expect(style).not.toHaveProperty("elevation");
  });

  it("softShadow mirrors the glass-card blur on both platforms", () => {
    const ios = withPlatform("ios", () => require("../ui/theme/shadow")).softShadow(10, 22, 0.35);
    expect(ios).toEqual({
      shadowColor: "#000000",
      shadowOffset: { width: 0, height: 10 },
      shadowOpacity: 0.35,
      shadowRadius: 22,
    });
    const android = withPlatform("android", () => require("../ui/theme/shadow")).softShadow(10, 22, 0.35);
    expect(android).toEqual({ boxShadow: "0px 10px 22px rgba(0,0,0,0.35)" });
  });
});

describe("tabBarMetrics — the control strip vs the system bars", () => {
  it("iOS keeps the shipped 90/30 regardless of insets", () => {
    const { tabBarMetrics } = withPlatform("ios", () => require("../ui/theme/tabBar"));
    expect(tabBarMetrics(0)).toEqual({ height: 90, paddingBottom: 30 });
    expect(tabBarMetrics(48)).toEqual({ height: 90, paddingBottom: 30 });
  });

  it("Android with no reported inset is exactly the shipped 78/16", () => {
    const { tabBarMetrics } = withPlatform("android", () => require("../ui/theme/tabBar"));
    expect(tabBarMetrics(0)).toEqual({ height: 78, paddingBottom: 16 });
  });

  it("Android grows with the inset, icon block constant at 62", () => {
    const { tabBarMetrics } = withPlatform("android", () => require("../ui/theme/tabBar"));
    const gesture = tabBarMetrics(24);   // gesture-nav pill
    const buttons = tabBarMetrics(48);   // 3-button nav
    expect(gesture).toEqual({ height: 86, paddingBottom: 24 });
    expect(buttons).toEqual({ height: 110, paddingBottom: 48 });
    expect(gesture.height - gesture.paddingBottom).toBe(62);
    expect(buttons.height - buttons.paddingBottom).toBe(62);
  });
});
