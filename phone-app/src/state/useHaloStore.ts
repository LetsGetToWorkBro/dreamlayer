/**
 * useHaloStore — the device/capture facet, as a thin hook over the single
 * source of truth (useBrainStore) plus the memory service.
 *
 * "Connected" here means the Halo glasses are paired; "paused" is memory
 * capture. Both live in useBrainStore so the Brain tab and the Now/Settings/
 * onboarding screens never disagree. `connect()` is async so onboarding can
 * await it; on a real build this drives the BLE bridge.
 */
import { useBrainStore } from "./useBrainStore";
import { useMemoryStore } from "./useMemoryStore";

export function useHaloStore() {
  const glasses = useBrainStore((s) => s.glasses);
  const capturePaused = useBrainStore((s) => s.capturePaused);
  const setCapturePaused = useBrainStore((s) => s.setCapturePaused);
  const connectGlasses = useBrainStore((s) => s.connectGlasses);
  const service = useMemoryStore((s) => s.service);

  return {
    paused: capturePaused,
    connected: glasses.connected,
    service,
    togglePause: () => setCapturePaused(!capturePaused),
    connect: async () => {
      // real build: scan + BLE handshake. Here we mark the demo Halo paired.
      connectGlasses(glasses.id || "HALO-DEMO");
    },
  };
}
