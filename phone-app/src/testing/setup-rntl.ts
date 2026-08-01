/** Component-test setup: native-module shims that don't exist under jest-expo
 * (haptics, camera). RNTL (13+) auto-extends expect, so no matcher import
 * needed. Keeps screen tests from touching real native code. */

// Jest's 5000 ms default is a HANG DETECTOR, and it was never chosen for a
// project whose stated job (see jest.config.js) is to "boot the RN transform
// stack". On a COLD transform cache that boot lands inside the first test of
// whichever component suite jest happens to schedule first: `react-native`'s
// index uses lazy getters, so a chunk of the module tree is pulled in during
// the first `render()` rather than at require time — inside the 5 s window
// rather than before it (#569).
//
// Measured on `4f6f14d` with `npx jest --clearCache`: red 5 runs out of 5, 3-6
// tests each, every failure the FIRST test of a component suite and every one
// the same 5000 ms timeout. Warm, those same tests average ~350 ms. Which suite
// goes red is not even stable — jest orders files by size, so adding a test case
// anywhere reshuffles which one absorbs the cost. That is what made this read as
// flake rather than as a fixed cost charged to an arbitrary victim.
//
// 30 s is ~85x the warm mean, so a genuine hang still fails the run; it just no
// longer fails whichever test drew the short straw. Set here rather than in
// jest.config.js because `testTimeout` is a root-level option that a project
// entry silently rejects — and setting it at the root would slow the hang
// detector for the `logic` project too, which runs no RN runtime and should
// keep failing fast.
jest.setTimeout(30000);

// expo-haptics: no native actuator in a test runtime — make every call a no-op
jest.mock("expo-haptics", () => ({
  impactAsync: jest.fn(),
  notificationAsync: jest.fn(),
  ImpactFeedbackStyle: { Light: "light", Medium: "medium", Heavy: "heavy" },
  NotificationFeedbackType: { Success: "success", Warning: "warning", Error: "error" },
}));

// expo-camera: the Look screen degrades to a "no camera here" state under tests
jest.mock("expo-camera", () => ({}));

// safe-area-context: the official mock (a default export) — provider-less
// rendering with zero insets
jest.mock("react-native-safe-area-context", () =>
  require("react-native-safe-area-context/jest/mock").default
);

// expo-router pulls a native routing/linking stack we don't need for rendering;
// stub the surface the screens use. (require() inside the factory — jest.mock
// factories can't close over module-scope variables.)
jest.mock("expo-router", () => {
  const R = require("react");
  const { Text } = require("react-native");
  const nav = { push: jest.fn(), replace: jest.fn(), back: jest.fn() };
  return {
    Link: ({ children }: any) => R.createElement(Text, null, children),
    router: nav,
    useRouter: () => nav,
    usePathname: () => "/",
    useLocalSearchParams: () => ({}),
    Tabs: Object.assign(({ children }: any) => children, { Screen: () => null }),
    Stack: Object.assign(({ children }: any) => children, { Screen: () => null }),
  };
});
