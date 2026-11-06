import {
  type AttemptEvent,
  type Deck,
  type Difficulty,
  DIFFICULTIES,
  type ItemProgress,
  isDeck,
  isLevel,
  type Level,
  uuid,
} from "@lexi/core";
import type { Database } from "./db";

export interface Settings {
  trainerId: string;
  level: Level;
  lang: "ru" | "en";
  sessionSize: number;
  /** Word set: CEFR general vocabulary or technical vocabulary. */
  deck: Deck;
  /** "hard": options from the same semantic group. */
  difficulty: Difficulty;
  /** Interface language. */
  uiLang: "ru" | "en";
  /** Tech deck fields to train (empty = all). */
  fields: string[];
}

export const DEFAULT_SETTINGS: Settings = {
  trainerId: "word-to-definition",
  level: "A1",
  lang: "ru",
  sessionSize: 10,
  deck: "general",
  difficulty: "normal",
  uiLang: "ru",
  fields: [],
};

/** Saved settings may come from an older version: keep only valid values. */
export function sanitizeSettings(saved: Partial<Settings> | undefined): Settings {
  const s = { ...DEFAULT_SETTINGS, ...saved };
  return {
    trainerId: typeof s.trainerId === "string" ? s.trainerId : DEFAULT_SETTINGS.trainerId,
    level: isLevel(s.level) ? s.level : DEFAULT_SETTINGS.level,
    lang: s.lang === "en" ? "en" : "ru",
    sessionSize: s.sessionSize === 20 ? 20 : 10,
    deck: isDeck(s.deck) ? s.deck : DEFAULT_SETTINGS.deck,
    difficulty: (DIFFICULTIES as readonly string[]).includes(s.difficulty) ? s.difficulty : "normal",
    uiLang: s.uiLang === "en" ? "en" : "ru",
    fields: Array.isArray(s.fields) ? [...new Set(s.fields.filter((f): f is string => typeof f === "string"))] : [],
  };
}

/** Local-first persistence: progress + an outbox of immutable attempt events. */
export class LocalStore {
  constructor(
    private db: Database,
    /** false when the browser refused IndexedDB and data lives in memory only. */
    readonly persistent = true,
  ) {}

  async deviceId(): Promise<string> {
    const existing = (await this.db.get("meta", "deviceId")) as string | undefined;
    if (existing) return existing;
    const id = uuid();
    await this.db.put("meta", id, "deviceId");
    return id;
  }

  async settings(): Promise<Settings> {
    return sanitizeSettings((await this.db.get("meta", "settings")) as Partial<Settings> | undefined);
  }

  async saveSettings(settings: Settings): Promise<void> {
    await this.db.put("meta", settings, "settings");
  }

  /** Progress for one trainer, keyed by entry id (both decks; tech ids are prefixed). */
  async progressFor(trainerId: string): Promise<Map<string, ItemProgress>> {
    const rows = await this.db.getAllFromIndex("progress", "byTrainer", trainerId);
    return new Map(rows.map((p) => [p.entryId, p]));
  }

  /** Atomically store the new progress state and queue the event for sync. */
  async recordAttempt(event: AttemptEvent, progress: ItemProgress): Promise<void> {
    const tx = this.db.transaction(["progress", "outbox"], "readwrite");
    await Promise.all([
      tx.objectStore("progress").put(progress),
      tx.objectStore("outbox").put({ ...event, queuedAt: Date.now() }),
      tx.done,
    ]);
  }

  async pendingEvents(limit: number): Promise<AttemptEvent[]> {
    const rows = await this.db.getAll("outbox", undefined, limit);
    return rows.map(({ queuedAt: _q, ...e }) => e);
  }

  async pendingCount(): Promise<number> {
    return this.db.count("outbox");
  }

  async acknowledge(ids: string[]): Promise<void> {
    const tx = this.db.transaction("outbox", "readwrite");
    await Promise.all([...ids.map((id) => tx.store.delete(id)), tx.done]);
  }

  async setMeta(key: string, value: unknown): Promise<void> {
    await this.db.put("meta", value, key);
  }

  async getMeta<T>(key: string): Promise<T | undefined> {
    return (await this.db.get("meta", key)) as T | undefined;
  }
}
