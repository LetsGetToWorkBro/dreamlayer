import { Platform } from "react-native";

/**
 * Type families. Two faces, exactly as the landing page and the Mac Brain panel
 * pair them:
 *   • ChicagoFLF — the Mac OS 8.1 system face. Titles, window/menu chrome, the
 *     display voice. Public-domain ChicagoFLF, loaded from assets/fonts in
 *     app/_layout.tsx. One weight only (bitmap heritage), so we never lean on
 *     fontWeight for it.
 *   • Space Grotesk — the reading face. Body, captions, the tracked eyebrow.
 *     Loaded via @expo-google-fonts. Because custom fonts don't respond to
 *     fontWeight in RN, each weight maps to its own family.
 */
export const fonts = {
  regular: "SpaceGrotesk_400Regular",
  medium: "SpaceGrotesk_500Medium",
  bold: "SpaceGrotesk_700Bold",
  chicago: "ChicagoFLF",
  mono: Platform.select({ ios: "Menlo", android: "monospace", default: "ui-monospace" }) as string,
};
