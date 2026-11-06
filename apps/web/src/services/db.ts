import { type DBSchema, type IDBPDatabase, openDB } from "idb";
import type { AttemptEvent, ItemProgress } from "@lexi/core";

interface LexiDB extends DBSchema {
  progress: { key: string; value: ItemProgress; indexes: { byTrainer: string } };
  outbox: { key: string; value: AttemptEvent & { queuedAt: number } };
  meta: { key: string; value: unknown };
}

export type Database = IDBPDatabase<LexiDB>;

export function openDatabase(name = "lexi"): Promise<Database> {
  return openDB<LexiDB>(name, 1, {
    upgrade(db) {
      const progress = db.createObjectStore("progress", { keyPath: "key" });
      progress.createIndex("byTrainer", "trainerId");
      db.createObjectStore("outbox", { keyPath: "id" });
      db.createObjectStore("meta");
    },
  });
}

/**
 * In-memory stand-in with the small subset of the idb API that LocalStore uses.
 * Used only when the browser refuses IndexedDB (e.g. some browsers for pages
 * opened from disk): the app keeps working, progress lasts until the tab closes.
 */
export function createMemoryDatabase(): Database {
  const stores: Record<string, Map<string, unknown>> = { progress: new Map(), outbox: new Map(), meta: new Map() };
  const keyOf = (store: string, value: unknown, key?: string): string =>
    key ?? (store === "progress" ? (value as ItemProgress).key : (value as { id: string }).id);
  const storeApi = (name: string) => ({
    put: async (value: unknown, key?: string) => void stores[name]!.set(keyOf(name, value, key), value),
    delete: async (key: string) => void stores[name]!.delete(key),
  });
  const db = {
    get: async (store: string, key: string) => stores[store]!.get(key),
    put: async (store: string, value: unknown, key?: string) => void stores[store]!.set(keyOf(store, value, key), value),
    getAll: async (store: string, _q?: unknown, limit?: number) => [...stores[store]!.values()].slice(0, limit),
    getAllFromIndex: async (store: string, _index: string, trainerId: string) =>
      [...stores[store]!.values()].filter((v) => (v as ItemProgress).trainerId === trainerId),
    count: async (store: string) => stores[store]!.size,
    transaction: (names: string | string[]) => {
      const first = Array.isArray(names) ? names[0]! : names;
      return { objectStore: storeApi, store: storeApi(first), done: Promise.resolve() };
    },
  };
  return db as unknown as Database;
}
