import { Platform, type ViewStyle } from "react-native";

/**
 * The Mac OS 8.1 drop shadow, faithful on both platforms.
 *
 * iOS draws it with the shadow* props (shadowRadius 0 = the hard Platinum
 * offset). Android ignores shadow* entirely, and `elevation` can only draw a
 * soft, symmetric Material blob — the wrong look for Platinum chrome. On the
 * new architecture (RN >= 0.76) Android renders the CSS-style `boxShadow`
 * natively, so there we draw the *same* crisp offset instead.
 *
 * hardShadow(2, 3, 0.34) ≡ a black shadow 2 right, 3 down, dead sharp.
 * softShadow(dy, blur, opacity) is the one soft (blurred, centered-x) shadow
 * the app uses, for the HUD mirror's floating glass card.
 */
export function hardShadow(dx: number, dy: number, opacity: number): ViewStyle {
  return Platform.OS === "android"
    ? { boxShadow: `${dx}px ${dy}px 0px rgba(0,0,0,${opacity})` }
    : {
        shadowColor: "#000000",
        shadowOffset: { width: dx, height: dy },
        shadowOpacity: opacity,
        shadowRadius: 0,
      };
}

export function softShadow(dy: number, blur: number, opacity: number): ViewStyle {
  return Platform.OS === "android"
    ? { boxShadow: `0px ${dy}px ${blur}px rgba(0,0,0,${opacity})` }
    : {
        shadowColor: "#000000",
        shadowOffset: { width: 0, height: dy },
        shadowOpacity: opacity,
        shadowRadius: blur,
      };
}
