import { Platform } from "react-native";

/**
 * Space Grotesk — the brand display face, shared with the landing page and the
 * Mac Brain panel. Loaded in app/_layout.tsx via @expo-google-fonts. Because
 * custom fonts don't respond to fontWeight in RN, we map each weight to its own
 * family and set fontFamily explicitly in typography.
 */
export const fonts = {
  regular: "SpaceGrotesk_400Regular",
  medium: "SpaceGrotesk_500Medium",
  bold: "SpaceGrotesk_700Bold",
  mono: Platform.select({ ios: "Menlo", android: "monospace", default: "ui-monospace" }) as string,
};
