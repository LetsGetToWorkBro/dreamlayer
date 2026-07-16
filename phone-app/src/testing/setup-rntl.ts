/** Component-test setup: native-module shims that don't exist under jest-expo
 * (haptics, camera). RNTL (13+) auto-extends expect, so no matcher import
 * needed. Keeps screen tests from touching real native code. */

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
