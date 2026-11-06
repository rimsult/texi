import type { Lexicon } from "./lexicon";
import type { Rng } from "./random";
import type { Deck, Definition, Difficulty, Lang, Level, PartOfSpeech } from "./types";

/** Every question type shares this envelope; `kind` selects the UI renderer. */
export interface BaseQuestion {
  id: string;
  kind: string;
  trainerId: string;
  entryId: string;
  level: Level;
  lang: Lang;
  /** "hard" when the options come from the answer's own semantic group. */
  difficulty?: Difficulty;
}

export interface AnswerResult {
  correct: boolean;
  correctAnswerId: string;
}

export interface TrainerContext {
  lexicon: Lexicon;
  level: Level;
  rng: Rng;
  /** Preferred definition language (only honoured where the level allows it). */
  preferredLang: Lang;
  /** Word set the lexicon was loaded from (recorded on attempt events). Default "general". */
  deck?: Deck;
  /** "hard": distractors from the same semantic group. Default "normal". */
  difficulty?: Difficulty;
  /** Tech deck: only words of these fields (empty/undefined = all). */
  domains?: string[];
}

/**
 * Contract for a trainer plugin. New exercise types (listening, gap-fill,
 * grammar…) implement this interface and register themselves — the session
 * engine, scheduler, storage and sync never change.
 */
export interface TrainerPlugin<Q extends BaseQuestion = BaseQuestion, A = string> {
  readonly id: string;
  readonly title: string;
  readonly subtitle: string;
  readonly icon: string;
  readonly availability: "ready" | "soon";
  /** Renderer key used by the UI layer. */
  readonly kind: string;
  /** "extra": an optional trainer listed after the main ones (gap-fill). Default "main". */
  readonly tier?: "main" | "extra";
  /** Questions are always in this language (gap-fill sentences are English). */
  readonly questionLang?: Lang;
  /** False when the trainer has a single difficulty (hard mode does not apply). */
  readonly supportsHard?: boolean;
  /** Entry ids that can produce a valid question at this level. */
  items(ctx: TrainerContext): string[];
  /** Build a concrete, display-ready question; null if it fails validation. */
  build(entryId: string, ctx: TrainerContext): Q | null;
  check(question: Q, answer: A): AnswerResult;
}

export interface McqOption {
  id: string;
  text: string;
  lang: Lang;
  /** What the option stands for, shown after answering: why it is (not) the answer. */
  explain: {
    lemma: string;
    /** The option's own definition (definition → word, gap-fill) in the explanation language. */
    definition?: string;
    /** Short Russian translation (Russian questions only). */
    translation?: string;
  };
}

/** Gap-fill prompt: the sentence around the gap (original article, before "a/an" masking). */
export interface GapPrompt {
  before: string;
  after: string;
  /** The word as written in the sentence. */
  answer: string;
}

export interface McqQuestion extends BaseQuestion {
  kind: "mcq";
  prompt: {
    text: string;
    lang: Lang;
    style: "word" | "definition" | "sentence";
    pos: PartOfSpeech;
    /** style "sentence": the parts of the sentence around the "___" gap. */
    gap?: GapPrompt;
  };
  instruction: string;
  options: McqOption[];
  correctOptionId: string;
  reveal: {
    lemma: string;
    pos: PartOfSpeech;
    definition: Definition;
    english?: Definition;
    /** Short Russian translation of the word (Russian questions only). */
    translation?: string;
    example?: string;
    /** Russian translation of the example (Russian questions only). */
    exampleRu?: string;
    synonyms?: string[];
    /** Technical field id (tech deck), e.g. "it", "physics". */
    domain?: string;
  };
}
