import { bestDefinition } from "../lexicon";
import { allowedLangs } from "../policy";
import { sample, shuffle } from "../random";
import type { McqQuestion, TrainerContext, TrainerPlugin } from "../trainer";
import type { Lang, PackQuestion } from "../types";
import { checkPackQuestion } from "../validation";

export type Direction = "word-to-definition" | "definition-to-word";

const POS_RU: Record<string, string> = {
  noun: "сущ.",
  verb: "глагол",
  adjective: "прил.",
  adverb: "нареч.",
};
export const posLabel = (pos: string): string => POS_RU[pos] ?? pos;

const hasHardPool = (q: PackQuestion): boolean => (q.hard?.length ?? 0) >= 2;

/** Field filter of the tech deck: undefined = every field. */
const domainFilter = (ctx: TrainerContext): Set<string> | undefined =>
  ctx.domains && ctx.domains.length ? new Set(ctx.domains) : undefined;

/**
 * Pick the pack question in the preferred language, falling back to any allowed one.
 * In hard mode only questions with a same-group distractor pool qualify.
 */
export function pickPackQuestion(ctx: TrainerContext, trainerId: string, entryId: string): PackQuestion | undefined {
  const hard = ctx.difficulty === "hard";
  const candidates = ctx.lexicon
    .questionsFor(ctx.level, trainerId)
    .filter((q) => q.entryId === entryId && (!hard || hasHardPool(q)));
  const langs: Lang[] = allowedLangs(ctx.level);
  const order = [ctx.preferredLang, ...langs.filter((l) => l !== ctx.preferredLang)].filter((l) => langs.includes(l));
  for (const lang of order) {
    const q = candidates.find((c) => c.lang === lang);
    if (q) return q;
  }
  return undefined;
}

/** The definition language of a session: the preferred one when the level allows it, otherwise English. */
export function sessionLang(ctx: Pick<TrainerContext, "level" | "preferredLang">): Lang {
  const langs = allowedLangs(ctx.level);
  return langs.includes(ctx.preferredLang) ? ctx.preferredLang : langs[0]!;
}

/** Hard mode draws from the closest valid options (pools are ordered by similarity). */
const HARD_TOP = 3;

export function createMeaningChoiceTrainer(direction: Direction): TrainerPlugin<McqQuestion> {
  const isWordPrompt = direction === "word-to-definition";
  // Cache per (lexicon, level, trainer) — the list is requested often by the UI.
  const itemCache = new WeakMap<object, Map<string, string[]>>();

  return {
    id: direction,
    title: isWordPrompt ? "Слово → определение" : "Определение → слово",
    subtitle: isWordPrompt
      ? "Видите английское слово — выберите верное определение из трёх."
      : "Видите определение — выберите подходящее слово из трёх.",
    icon: isWordPrompt ? "🔤" : "📖",
    availability: "ready",
    kind: "mcq",

    items(ctx) {
      let byLevel = itemCache.get(ctx.lexicon);
      if (!byLevel) itemCache.set(ctx.lexicon, (byLevel = new Map()));
      const hard = ctx.difficulty === "hard";
      // A session stays in one language: words without a definition in it are left out.
      const lang = sessionLang(ctx);
      const domains = domainFilter(ctx);
      const key = `${ctx.level}:${lang}:${hard ? "hard" : "normal"}:${domains ? [...domains].sort().join(",") : "*"}`;
      const cached = byLevel.get(key);
      if (cached) return cached;
      const ids = new Set<string>();
      for (const q of ctx.lexicon.questionsFor(ctx.level, direction)) {
        if (q.lang !== lang || (hard && !hasHardPool(q))) continue;
        if (domains && !domains.has(ctx.lexicon.entry(q.entryId)?.domain ?? "")) continue;
        ids.add(q.entryId);
      }
      const list = [...ids];
      byLevel.set(key, list);
      return list;
    },

    build(entryId, ctx) {
      const packQ = pickPackQuestion(ctx, direction, entryId);
      if (!packQ) return null;
      const difficulty = ctx.difficulty ?? "normal";
      const check = checkPackQuestion(packQ, ctx.lexicon, 2, difficulty);
      if (!check.ok) return null; // never show a question that fails validation
      const target = ctx.lexicon.entry(entryId)!;
      const lang = packQ.lang;
      const targetDef = bestDefinition(target, lang)!;
      let valid = check.validDistractors;
      const domains = domainFilter(ctx);
      if (domains) {
        // Options from the chosen fields only, when the pool allows it.
        const own = valid.filter((e) => domains.has(e.domain ?? ""));
        if (own.length >= 2) valid = own;
      }
      const pool = difficulty === "hard" ? valid.slice(0, HARD_TOP) : valid;
      const distractors = sample(pool, 2, ctx.rng);
      const options = shuffle([target, ...distractors], ctx.rng);
      const english = lang === "en" ? undefined : bestDefinition(target, "en");
      return {
        id: `${direction}:${entryId}:${lang}${difficulty === "hard" ? ":hard" : ""}`,
        kind: "mcq",
        trainerId: direction,
        entryId,
        level: target.level,
        lang,
        difficulty,
        instruction: isWordPrompt ? "Выберите верное определение" : "Выберите слово по определению",
        prompt: isWordPrompt
          ? { text: target.lemma, lang: "en", style: "word", pos: target.pos }
          : { text: targetDef.text, lang, style: "definition", pos: target.pos },
        options: options.map((e) => ({
          id: e.id,
          text: isWordPrompt ? bestDefinition(e, lang)!.text : e.lemma,
          lang: isWordPrompt ? lang : "en",
          explain: {
            lemma: e.lemma,
            ...(isWordPrompt ? {} : { definition: bestDefinition(e, lang)!.text }),
            ...(lang === "ru" && e.translation ? { translation: e.translation } : {}),
          },
        })),
        correctOptionId: target.id,
        reveal: {
          lemma: target.lemma,
          pos: target.pos,
          definition: targetDef,
          ...(english ? { english } : {}),
          ...(lang === "ru" && target.translation ? { translation: target.translation } : {}),
          ...(target.example ? { example: target.example } : {}),
          ...(lang === "ru" && target.example && target.exampleRu ? { exampleRu: target.exampleRu } : {}),
          ...(target.synonyms?.length ? { synonyms: target.synonyms } : {}),
          ...(target.domain ? { domain: target.domain } : {}),
        },
      };
    },

    check(question, answer) {
      return { correct: answer === question.correctOptionId, correctAnswerId: question.correctOptionId };
    },
  };
}

export const wordToDefinition = createMeaningChoiceTrainer("word-to-definition");
export const definitionToWord = createMeaningChoiceTrainer("definition-to-word");
