/** P0-3: "Erase everything — this cannot be undone" must actually be undoable
 * by nothing. purgeAll used to clear in-memory state and tell the Brain, but
 * left the on-disk cache intact, so hydrateCache() resurrected the erased
 * memories on the next launch. These tests pin that the cache is cleared and
 * cannot bring anything back. */
import AsyncStorage from "@react-native-async-storage/async-storage";

import { useMemoryStore } from "../state/useMemoryStore";

const CACHE_KEY = "dreamlayer.memories.cache.v1";

beforeEach(() => {
  (AsyncStorage as unknown as { __reset(): void }).__reset();
  useMemoryStore.setState({ memories: [], fetchedAt: 0 });
});

describe("useMemoryStore.purgeAll", () => {
  it("clears the on-disk cache", async () => {
    await AsyncStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ memories: [{ id: "1", kind: "note", primary: "secret" }], fetchedAt: 123 }),
    );
    useMemoryStore.getState().service.purgeAll();
    await Promise.resolve(); // let the removeItem microtask settle
    expect(await AsyncStorage.getItem(CACHE_KEY)).toBeNull();
    expect(useMemoryStore.getState().memories).toEqual([]);
  });

  it("hydrateCache cannot resurrect what purge erased", async () => {
    await AsyncStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ memories: [{ id: "1", kind: "note", primary: "secret" }], fetchedAt: 123 }),
    );
    useMemoryStore.getState().service.purgeAll();
    await Promise.resolve();
    await useMemoryStore.getState().hydrateCache();
    expect(useMemoryStore.getState().memories).toEqual([]);
  });
});
