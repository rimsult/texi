export const LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"] as const;
export type Level = (typeof LEVELS)[number];
/** Word sets: CEFR general vocabulary or technical vocabulary for STEM students. */
export const DECKS = ["general", "tech"] as const;
export type Deck = (typeof DECKS)[number];
/** "hard": distractors come from the same semantic group as the answer. */
export const DIFFICULTIES = ["normal", "hard"] as const;
export type Difficulty = (typeof DIFFICULTIES)[number];
export type Lang = "en" | "ru";
/** "machine": Russian definitions are offline machine translations of the English ones. */
/** "simple": Simple English Wiktionary learner definition, chosen for lower levels. */
export type DefinitionSource = "wordnet" | "simple" | "wiktionary" | "generated" | "machine";
export type PartOfSpeech = "noun" | "verb" | "adjective" | "adverb";

export interface Definition {
  text: string;
  lang: Lang;
  source: DefinitionSource;
  quality: number;
}

export interface Entry {
  id: string;
  lemma: string;
  pos: PartOfSpeech;
  level: Level;
  group: string | null;
  /** Group used by hard mode when it differs from `group` (adjective antonym families). */
  hardGroup?: string;
  /** Technical field (tech deck only), e.g. "it", "physics". */
  domain?: string;
  definitions: Definition[];
  example?: string;
  /** Machine translation of the example (A1–A2 packs). */
  exampleRu?: string;
  /** Short Russian translation (A1–A2 packs), shown after answering a Russian question. */
  translation?: string;
  /** Common synonyms of this sense, shown after answering. */
  synonyms?: string[];
}

/** A pre-validated question template produced by the content pipeline. */
export interface PackQuestion {
  trainer: string;
  entryId: string;
  lang: Lang;
  /** Pool of verified distractor entry ids (≥ 2). Two are drawn per question. */
  distractors: string[];
  /** Same-group distractors for hard mode, most similar first (≥ 2 when present). */
  hard?: string[];
  /** Gap-fill: [start, end) of the word inside the entry's example sentence. */
  span?: [number, number];
  /** Gap-fill: the word forms for the gap, aligned with [entryId, ...distractors] (ate, slept…). */
  forms?: string[];
}

export interface ContentPack {
  schemaVersion: number;
  deck?: Deck;
  level: Level;
  entries: Entry[];
  questions: PackQuestion[];
}

export interface ManifestLevel {
  level: Level;
  file: string;
  words: number;
  bytes: number;
  hash: string;
  questions: Record<string, number>;
  /** Questions that also have hard-mode distractors, by `trainer:lang`. */
  hard?: Record<string, number>;
  /** Tech deck: the same counts per technical field. */
  fields?: Record<string, { questions: Record<string, number>; hard?: Record<string, number> }>;
}

export interface ManifestDeck {
  id: Deck;
  title: string;
  description: string;
  levels: ManifestLevel[];
}

export interface ContentManifest {
  schemaVersion: number;
  version: string;
  decks: ManifestDeck[];
  /** Technical field id -> Russian label. */
  fields?: Record<string, string>;
  sources: { name: string; url: string; license: string }[];
}

export function isDeck(value: unknown): value is Deck {
  return typeof value === "string" && (DECKS as readonly string[]).includes(value);
}

/** Tech-deck entry ids are prefixed, so progress never mixes the two decks. */
export function deckOfEntry(entryId: string): Deck {
  return entryId.startsWith("tech:") ? "tech" : "general";
}

export function isLevel(value: unknown): value is Level {
  return typeof value === "string" && (LEVELS as readonly string[]).includes(value);
}
