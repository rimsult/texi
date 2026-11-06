import { neighbourLevels } from "./policy";
import type { ContentPack, Definition, Entry, Lang, Level, PackQuestion } from "./types";

/** In-memory view over one or more loaded content packs. */
export class Lexicon {
  private entries = new Map<string, Entry>();
  private questions = new Map<Level, PackQuestion[]>();

  constructor(packs: ContentPack[] = []) {
    packs.forEach((p) => this.add(p));
  }

  add(pack: ContentPack): void {
    for (const e of pack.entries) this.entries.set(e.id, e);
    this.questions.set(pack.level, pack.questions);
  }

  has(level: Level): boolean {
    return this.questions.has(level);
  }

  /** True when the level and all its distractor neighbours are loaded. */
  isReady(level: Level): boolean {
    return neighbourLevels(level).every((l) => this.questions.has(l));
  }

  entry(id: string): Entry | undefined {
    return this.entries.get(id);
  }

  questionsFor(level: Level, trainer: string): PackQuestion[] {
    return (this.questions.get(level) ?? []).filter((q) => q.trainer === trainer);
  }

  get size(): number {
    return this.entries.size;
  }
}

export function bestDefinition(entry: Entry, lang: Lang): Definition | undefined {
  let best: Definition | undefined;
  for (const d of entry.definitions) {
    if (d.lang === lang && (!best || d.quality > best.quality)) best = d;
  }
  return best;
}
