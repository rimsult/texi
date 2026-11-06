import { bestDefinition, type Lexicon } from "../lexicon";
import { levelIndex } from "../policy";
import { sample, shuffle } from "../random";
import type { McqQuestion, TrainerContext, TrainerPlugin } from "../trainer";
import type { Entry, Lang, PackQuestion } from "../types";
import { hardGroupOf } from "../validation";
import { sessionLang } from "./meaningChoice";

export const GAP_FILL = "gap-fill";
export const GAP = "___";

export interface GapCheck {
  ok: boolean;
  reasons: string[];
  /** Valid distractors with the form each one takes in the gap. */
  options: { entry: Entry; form: string }[];
}

const norm = (s: string) => s.trim().replace(/\s+/g, " ").toLowerCase();
const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** The form occurs in the sentence as a whole word (a distractor must not). */
const occursIn = (sentence: string, form: string) =>
  new RegExp(`(^|[^\\p{L}\\-])${escapeRe(norm(form))}($|[^\\p{L}\\-])`, "u").test(norm(sentence));

/**
 * Client-side re-check of a gap-fill question (defence in depth; the pipeline also
 * runs synonym, translation and language-model checks): the span must point at the
 * answer's form in the example, and every distractor must be a different word of the
 * same part of speech, ±1 level, from another semantic group, with a distinct form.
 */
export function checkGapQuestion(q: PackQuestion, lexicon: Lexicon, minDistractors = 2): GapCheck {
  const target = lexicon.entry(q.entryId);
  if (!target) return { ok: false, reasons: ["missing_entry"], options: [] };
  const reasons: string[] = [];
  const example = target.example ?? "";
  const [start, end] = q.span ?? [-1, -1];
  const forms = q.forms ?? [];
  if (!example || start < 0 || end <= start || end > example.length) reasons.push("bad_span");
  else if (norm(example.slice(start, end)) !== norm(forms[0] ?? "")) reasons.push("span_mismatch");
  if (forms.length !== q.distractors.length + 1) reasons.push("forms_mismatch");
  const seen = new Set([norm(forms[0] ?? "")]);
  const options: GapCheck["options"] = [];
  q.distractors.forEach((id, i) => {
    const cand = lexicon.entry(id);
    const form = forms[i + 1];
    if (!cand || !form || !target.group || !cand.group) return;
    if (cand.id === target.id || cand.lemma.toLowerCase() === target.lemma.toLowerCase()) return;
    if (cand.pos !== target.pos) return;
    if (Math.abs(levelIndex(cand.level) - levelIndex(target.level)) > 1) return;
    if (cand.group === target.group) return;
    // Adjectives: never from the answer's antonym family (hot / cold both fit "The soup is ___").
    if (hardGroupOf(target)?.startsWith("adjfam:") && hardGroupOf(cand) === hardGroupOf(target)) return;
    if (seen.has(norm(form)) || occursIn(example, form)) return;
    seen.add(norm(form));
    options.push({ entry: cand, form });
  });
  if (options.length < minDistractors) reasons.push("insufficient_distractors");
  return { ok: reasons.length === 0, reasons, options };
}

/** The sentence with the gap; "a"/"an" right before it becomes "a/an" so it gives nothing away. */
export function maskSentence(before: string, after: string): string {
  const masked = before.replace(/\b([Aa])(n?)(\s+)$/, (_m, a: string, _n: string, sp: string) =>
    `${a}/${a === "A" ? "An" : "an"}${sp}`,
  );
  return `${masked}${GAP}${after}`;
}

const domainFilter = (ctx: TrainerContext): Set<string> | undefined =>
  ctx.domains && ctx.domains.length ? new Set(ctx.domains) : undefined;

/** Explanations (definitions after answering) follow the session language where available. */
const explainLang = (ctx: TrainerContext): Lang => sessionLang(ctx);

/**
 * Optional trainer "Fill the gap": an example sentence with the word left out; the
 * options are words in the same grammatical form (ate / slept / drank). Always English
 * sentences; the definitions shown after answering follow the session language.
 */
export function createGapFillTrainer(): TrainerPlugin<McqQuestion> {
  const itemCache = new WeakMap<object, Map<string, string[]>>();
  return {
    id: GAP_FILL,
    title: "Вставьте слово",
    subtitle: "Предложение с пропуском — выберите слово, которое подходит по смыслу.",
    icon: "✍️",
    availability: "ready",
    kind: "mcq",
    tier: "extra",
    questionLang: "en",
    supportsHard: false,

    items(ctx) {
      let byLevel = itemCache.get(ctx.lexicon);
      if (!byLevel) itemCache.set(ctx.lexicon, (byLevel = new Map()));
      const domains = domainFilter(ctx);
      const key = `${ctx.level}:${domains ? [...domains].sort().join(",") : "*"}`;
      const cached = byLevel.get(key);
      if (cached) return cached;
      const ids = new Set<string>();
      for (const q of ctx.lexicon.questionsFor(ctx.level, GAP_FILL)) {
        if (!q.span) continue;
        if (domains && !domains.has(ctx.lexicon.entry(q.entryId)?.domain ?? "")) continue;
        ids.add(q.entryId);
      }
      const list = [...ids];
      byLevel.set(key, list);
      return list;
    },

    build(entryId, ctx) {
      const packQ = ctx.lexicon.questionsFor(ctx.level, GAP_FILL).find((q) => q.entryId === entryId);
      if (!packQ) return null;
      const check = checkGapQuestion(packQ, ctx.lexicon);
      if (!check.ok) return null; // never show a question that fails validation
      const target = ctx.lexicon.entry(entryId)!;
      const [start, end] = packQ.span!;
      const example = target.example!;
      const before = example.slice(0, start);
      const after = example.slice(end);
      let valid = check.options;
      const domains = domainFilter(ctx);
      if (domains) {
        const own = valid.filter((o) => domains.has(o.entry.domain ?? ""));
        if (own.length >= 2) valid = own;
      }
      const options = shuffle([{ entry: target, form: packQ.forms![0]! }, ...sample(valid, 2, ctx.rng)], ctx.rng);
      const wanted = explainLang(ctx);
      const def = (e: Entry) => bestDefinition(e, wanted) ?? bestDefinition(e, "en");
      const targetDef = def(target);
      if (!targetDef) return null;
      const ru = targetDef.lang === "ru";
      const english = ru ? bestDefinition(target, "en") : undefined;
      return {
        id: `${GAP_FILL}:${entryId}:en`,
        kind: "mcq",
        trainerId: GAP_FILL,
        entryId,
        level: target.level,
        lang: "en",
        difficulty: "normal",
        instruction: "Вставьте пропущенное слово",
        prompt: {
          text: maskSentence(before, after),
          lang: "en",
          style: "sentence",
          pos: target.pos,
          gap: { before, after, answer: example.slice(start, end) },
        },
        options: options.map(({ entry: e, form }) => {
          const d = def(e);
          return {
            id: e.id,
            text: form,
            lang: "en" as Lang,
            explain: {
              lemma: e.lemma,
              ...(d ? { definition: d.text } : {}),
              ...(ru && e.translation ? { translation: e.translation } : {}),
            },
          };
        }),
        correctOptionId: target.id,
        reveal: {
          lemma: target.lemma,
          pos: target.pos,
          definition: targetDef,
          ...(english ? { english } : {}),
          ...(ru && target.translation ? { translation: target.translation } : {}),
          example,
          ...(ru && target.exampleRu ? { exampleRu: target.exampleRu } : {}),
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

export const gapFill = createGapFillTrainer();
