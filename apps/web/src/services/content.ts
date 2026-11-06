import {
  type ContentManifest,
  type ContentPack,
  type Deck,
  type Level,
  Lexicon,
  type ManifestDeck,
  neighbourLevels,
} from "@lexi/core";

export class ContentError extends Error {}

/** Pack/manifest format this build understands (see data-pipeline SCHEMA_VERSION). */
export const SCHEMA_VERSION = 2;

/**
 * Loads static content packs: one Lexicon per word set (deck). The service worker
 * precaches every pack, so this works offline after the first visit; the
 * standalone build serves the same files from data embedded in the page.
 */
export class ContentService {
  private lexicons = new Map<Deck, Lexicon>();
  private manifestPromise?: Promise<ContentManifest>;
  private inflight = new Map<string, Promise<void>>();

  constructor(
    private baseUrl: string = import.meta.env.BASE_URL + "packs/",
    private fetchImpl: typeof fetch = (...a) => fetch(...a),
  ) {}

  manifest(): Promise<ContentManifest> {
    this.manifestPromise ??= this.getJson<ContentManifest>("manifest.json")
      .then((m) => {
        if (m.schemaVersion !== SCHEMA_VERSION || !Array.isArray(m.decks))
          throw new ContentError("Словарь обновился — перезагрузите страницу.");
        return m;
      })
      .catch((e) => {
        this.manifestPromise = undefined;
        throw e;
      });
    return this.manifestPromise;
  }

  lexicon(deck: Deck = "general"): Lexicon {
    let lex = this.lexicons.get(deck);
    if (!lex) this.lexicons.set(deck, (lex = new Lexicon()));
    return lex;
  }

  /** Load a level and its ±1 neighbours (where distractors live) for one deck. */
  async ensureLevel(level: Level, deck: Deck = "general"): Promise<Lexicon> {
    const info = await this.deckInfo(deck);
    await Promise.all(neighbourLevels(level).map((l) => this.loadPack(info, l)));
    return this.lexicon(deck);
  }

  private async deckInfo(deck: Deck): Promise<ManifestDeck> {
    const info = (await this.manifest()).decks.find((d) => d.id === deck);
    if (!info) throw new ContentError(`Набор слов «${deck}» не найден.`);
    return info;
  }

  private loadPack(deck: ManifestDeck, level: Level): Promise<void> {
    const lexicon = this.lexicon(deck.id);
    if (lexicon.has(level)) return Promise.resolve();
    const file = deck.levels.find((l) => l.level === level)?.file;
    if (!file) return Promise.resolve(); // a deck may not cover every level
    let p = this.inflight.get(file);
    if (!p) {
      p = this.getJson<ContentPack>(file)
        .then((pack) => {
          if (pack.schemaVersion !== SCHEMA_VERSION || pack.level !== level || (pack.deck ?? "general") !== deck.id)
            throw new ContentError(`Unexpected pack ${file}`);
          lexicon.add(pack);
        })
        .finally(() => this.inflight.delete(file));
      this.inflight.set(file, p);
    }
    return p;
  }

  private async getJson<T>(file: string): Promise<T> {
    let res: Response;
    try {
      res = await this.fetchImpl(this.baseUrl + file);
    } catch {
      throw new ContentError("Нет соединения, а материалы ещё не сохранены на устройстве.");
    }
    if (!res.ok) throw new ContentError(`Не удалось загрузить ${file} (${res.status})`);
    return (await res.json()) as T;
  }
}
