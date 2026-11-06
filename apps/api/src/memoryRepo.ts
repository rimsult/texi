import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { DeviceSummary, Repository, ReviewItem, SyncResult } from "./repo";
import type { AttemptEventInput } from "./schemas";

/** In-memory events + file-based content. Used for local dev, tests and e2e. */
export class MemoryRepository implements Repository {
  private events = new Map<string, AttemptEventInput & { deviceId: string }>();

  constructor(private packsDir?: string, private reviewFile?: string) {}

  async health() {
    return true;
  }

  async saveEvents(deviceId: string, events: AttemptEventInput[]): Promise<SyncResult> {
    const out: SyncResult = { accepted: [], duplicates: [] };
    for (const e of events) {
      if (this.events.has(e.id)) out.duplicates.push(e.id);
      else {
        this.events.set(e.id, { ...e, deviceId });
        out.accepted.push(e.id);
      }
    }
    return out;
  }

  async deviceSummary(deviceId: string): Promise<DeviceSummary | null> {
    const mine = [...this.events.values()].filter((e) => e.deviceId === deviceId);
    if (!mine.length) return null;
    return {
      events: mine.length,
      correct: mine.filter((e) => e.correct).length,
      words: new Set(mine.map((e) => `${e.trainerId}:${e.entryId}`)).size,
      lastAnsweredAt: mine.map((e) => e.answeredAt).sort().at(-1) ?? null,
    };
  }

  private readJson(file: string): unknown | null {
    if (!this.packsDir) return null;
    const path = join(this.packsDir, file);
    return existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : null;
  }

  async manifest() {
    return this.readJson("manifest.json");
  }

  async pack(level: string, deck = "general") {
    const manifest = (await this.manifest()) as { decks?: { id: string; levels: { level: string; file: string }[] }[] } | null;
    const file = manifest?.decks?.find((d) => d.id === deck)?.levels.find((l) => l.level === level)?.file;
    return file ? this.readJson(file) : null;
  }

  async reviewQueue(level: string | undefined, limit: number): Promise<ReviewItem[]> {
    if (!this.reviewFile || !existsSync(this.reviewFile)) return [];
    const items = JSON.parse(readFileSync(this.reviewFile, "utf8")) as ReviewItem[];
    return items
      .filter((i) => !level || i.level === level)
      .slice(0, limit)
      .map(({ id, trainer, entryId, lemma, level, deck, lang, reasons }) => ({ id, trainer, entryId, lemma, level, deck: deck ?? "general", lang, reasons }));
  }

  async close() {}
}
