import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { acquireStorageFence, prepareStoragePath } from "./fence.mjs";

/** @param {string} storagePath */
export async function openDurableStorage(storagePath) {
  await prepareStoragePath(storagePath);
  const releaseFence = acquireStorageFence(storagePath);
  try {
    const storage = await openNodeSqliteStorage(storagePath);
    let closed = false;
    const closeStorage = async () => {
      if (closed) return;
      closed = true;
      await storage.close(BACKGROUND_CONTEXT);
    };
    const sharedStorage = new Proxy(storage, {
      get(target, property, receiver) {
        return property === "close" ? closeStorage : Reflect.get(target, property, receiver);
      },
    });
    return {
      storage: sharedStorage,
      async close() {
        try {
          await closeStorage();
        } finally {
          releaseFence();
        }
      },
    };
  } catch (error) {
    releaseFence();
    throw error;
  }
}
