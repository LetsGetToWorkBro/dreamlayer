/**
 * Two jest projects:
 *
 *  - "logic": pure TS (stores, services, the BLE framing/bridge, pairing codec)
 *    under ts-jest / node. Fast, no RN runtime. Files: src/__tests__/*.test.ts.
 *  - "component": React Native screens under jest-expo + @testing-library/
 *    react-native. Files: src/__tests__/*.test.tsx.
 *
 * Keeping them separate means the logic layer stays instant and the component
 * layer (which boots the RN transform stack) only runs when a .tsx test exists.
 */
module.exports = {
  projects: [
    {
      displayName: "logic",
      preset: "ts-jest",
      testEnvironment: "node",
      roots: ["<rootDir>/src"],
      testMatch: ["**/__tests__/**/*.test.ts"],
      moduleNameMapper: {
        "^@react-native-async-storage/async-storage$":
          "<rootDir>/src/testing/mocks/async-storage.ts",
      },
      transform: {
        "^.+\\.tsx?$": ["ts-jest", { tsconfig: { jsx: "react", esModuleInterop: true } }],
      },
    },
    {
      displayName: "component",
      preset: "jest-expo",
      roots: ["<rootDir>/src", "<rootDir>/app"],
      testMatch: ["**/__tests__/**/*.test.tsx"],
      setupFilesAfterEnv: ["<rootDir>/src/testing/setup-rntl.ts"],
      moduleNameMapper: {
        "^@react-native-async-storage/async-storage$":
          "<rootDir>/src/testing/mocks/async-storage.ts",
      },
      transformIgnorePatterns: [
        "node_modules/(?!((jest-)?react-native|@react-native(-community)?|expo(nent)?|@expo(nent)?/.*|@expo-google-fonts/.*|react-navigation|@react-navigation/.*|@unimodules/.*|unimodules|sentry-expo|native-base|react-native-svg|zustand))",
      ],
    },
  ],
};
