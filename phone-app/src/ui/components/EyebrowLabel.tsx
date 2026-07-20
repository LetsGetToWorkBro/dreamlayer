import { Text } from "react-native";
import { useTheme } from "../theme/useTheme";
import { typography } from "../theme/typography";
type Props = { label: string; accent?: string };
export function EyebrowLabel({ label, accent }: Props) {
  const { colors } = useTheme();
  return (
    <Text style={[typography.eyebrow, { color: accent ?? colors.accentMemory, marginBottom: 10 }]}>
      {label}
    </Text>
  );
}
