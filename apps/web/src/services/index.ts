import { createDefaultRegistry, type TrainerRegistry } from "@lexi/core";
import { ContentService } from "./content";
import { createMemoryDatabase, openDatabase } from "./db";
import { LocalStore } from "./store";
import { SyncManager } from "./sync";

export interface Services {
  content: ContentService;
  store: LocalStore;
  sync: SyncManager;
  registry: TrainerRegistry;
  now: () => number;
  seed: () => number;
}

async function openStore(dbName?: string): Promise<LocalStore> {
  try {
    return new LocalStore(await openDatabase(dbName));
  } catch {
    return new LocalStore(createMemoryDatabase(), false);
  }
}

export async function createServices(overrides: Partial<Services> & { dbName?: string; apiUrl?: string } = {}): Promise<Services> {
  const store = overrides.store ?? (await openStore(overrides.dbName));
  return {
    content: overrides.content ?? new ContentService(),
    store,
    sync: overrides.sync ?? new SyncManager({ apiUrl: overrides.apiUrl ?? import.meta.env.VITE_API_URL, store }),
    registry: overrides.registry ?? createDefaultRegistry(),
    now: overrides.now ?? Date.now,
    seed: overrides.seed ?? (() => Math.floor(Math.random() * 2 ** 31)),
  };
}
