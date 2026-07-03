import React from "react";
import { View, Text, StyleSheet, Modal } from "react-native";
import { colors } from "../theme/colors";
import { typography } from "../theme/typography";
import { radius, space } from "../theme/spacing";
import { Tappable } from "./Tappable";

/**
 * QrScanner — point the phone at the QR the Mac mini panel shows and you're
 * paired. The whole camera stack is loaded lazily: if expo-camera isn't present
 * (web, a bare test runtime), the scanner degrades to a friendly "paste instead"
 * card rather than crashing the bundle.
 */
let CameraMod: any = null;
try {
  CameraMod = require("expo-camera");
} catch {
  CameraMod = null;
}

export function QrScanner({
  visible,
  onClose,
  onScan,
}: {
  visible: boolean;
  onClose: () => void;
  onScan: (code: string) => void;
}) {
  const CameraView = CameraMod?.CameraView;
  const usePermissions = CameraMod?.useCameraPermissions;
  const [permission, requestPermission] = usePermissions ? usePermissions() : [null, async () => {}];
  const handled = React.useRef(false);

  React.useEffect(() => {
    if (visible) handled.current = false;
    if (visible && permission && !permission.granted && permission.canAskAgain) {
      requestPermission();
    }
  }, [visible, permission]);

  const onBarcode = ({ data }: { data: string }) => {
    if (handled.current) return;
    handled.current = true;
    onScan(data);
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} transparent={false}>
      <View style={s.shell}>
        <View style={s.header}>
          <Text style={[typography.eyebrow, { color: colors.accentMemory }]}>Pair by QR</Text>
          <Tappable onPress={onClose} style={s.close}>
            <Text style={[typography.body, { color: colors.textSecondary }]}>Close</Text>
          </Tappable>
        </View>

        {CameraView && permission?.granted ? (
          <View style={s.stage}>
            <CameraView
              style={StyleSheet.absoluteFill}
              facing="back"
              barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
              onBarcodeScanned={onBarcode}
            />
            <View style={s.reticle} pointerEvents="none" />
            <Text style={[typography.caption, s.hint]}>
              Point at the QR in the Mac mini Brain panel → “Pair a phone”.
            </Text>
          </View>
        ) : (
          <View style={s.fallback}>
            <Text style={[typography.title, { color: colors.textPrimary, textAlign: "center" }]}>
              {CameraView ? "Camera access needed" : "Scanner unavailable here"}
            </Text>
            <Text style={[typography.body, { color: colors.textSecondary, textAlign: "center", marginTop: space.sm }]}>
              {CameraView
                ? "Allow the camera to scan the pairing QR, or close this and paste the code instead."
                : "Close this and paste the dreamlayer: code from the Mac mini panel instead."}
            </Text>
            {CameraView && permission && !permission.granted ? (
              <Tappable onPress={requestPermission} style={s.grant}>
                <Text style={[typography.body, { color: colors.background, fontWeight: "700" }]}>Allow camera</Text>
              </Tappable>
            ) : null}
          </View>
        )}
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  shell: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: space.lg,
    paddingTop: space.huge,
    paddingBottom: space.md,
  },
  close: { paddingVertical: space.xs, paddingHorizontal: space.sm },
  stage: { flex: 1, margin: space.lg, borderRadius: radius.lg, overflow: "hidden", backgroundColor: "#000" },
  reticle: {
    position: "absolute",
    top: "28%",
    left: "18%",
    width: "64%",
    height: "44%",
    borderWidth: 2,
    borderColor: colors.accentMemory,
    borderRadius: radius.lg,
  },
  hint: {
    position: "absolute",
    bottom: space.lg,
    left: space.lg,
    right: space.lg,
    color: "#fff",
    textAlign: "center",
  },
  fallback: { flex: 1, alignItems: "center", justifyContent: "center", padding: space.huge, gap: space.md },
  grant: {
    marginTop: space.lg,
    backgroundColor: colors.accentMemory,
    borderRadius: radius.pill,
    paddingVertical: space.md,
    paddingHorizontal: space.huge,
  },
});
