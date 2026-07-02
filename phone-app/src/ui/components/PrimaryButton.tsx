import { Text, ViewStyle } from "react-native";
import { colors } from "../theme/colors";
import { typography } from "../theme/typography";
import { radius, space } from "../theme/spacing";
import { Tappable } from "./Tappable";

type Props = { label: string; onPress: () => void; accent?: string; style?: ViewStyle };

export function PrimaryButton({ label, onPress, accent, style }: Props) {
  const bg = accent === "attention" ? colors.accentAttention : colors.accentMemory;
  return (
    <Tappable
      onPress={onPress}
      scaleTo={0.97}
      style={[
        {
          backgroundColor: bg,
          borderRadius: radius.pill,
          paddingVertical: space.lg,
          paddingHorizontal: space.huge,
          alignItems: "center",
        },
        style,
      ]}
    >
      <Text style={[typography.title, { color: colors.background }]}>{label}</Text>
    </Tappable>
  );
}
