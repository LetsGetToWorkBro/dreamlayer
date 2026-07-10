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
import { useGlassesStore } from "./useGlassesStore";

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
      // A dev build attaches a real BLE transport to useGlassesStore; when one
      // exists we scan + handshake over it and record the real device id.
      // Without a transport (Expo Go / tests) we mark the demo Halo paired, so
      // every existing flow is unchanged.
      const gs = useGlassesStore.getState();
      const id = gs.bridge ? await gs.connect() : null;
      connectGlasses(id || glasses.id || "HALO-DEMO");
    },
  };
}
