import { bestDefinition, type Lexicon } from "./lexicon";
import { isLangAllowed, levelIndex } from "./policy";
import type { Difficulty, Entry, Lang, PackQuestion } from "./types";

export type RejectionReason =
  | "missing_entry"
  | "same_word"
  | "pos_mismatch"
  | "level_out_of_range"
  | "unknown_semantic_group"
  | "same_semantic_group"
  | "different_semantic_group"
  | "same_cluster"
  | "no_definition_in_lang"
  | "duplicate_definition"
  | "lang_not_allowed";

export const hardGroupOf = (e: Entry): string | null => e.hardGroup ?? e.group;

/**
 * Client-side re-check of the structural distractor rules (defence in depth:
 * the pipeline already enforces these plus synonym/sense/translation checks).
 * Normal mode needs a *different* semantic group; hard mode needs the *same* one
 * (but never the same adjective cluster, whose members are near-synonyms).
 */
export function distractorRejection(
  target: Entry,
  cand: Entry | undefined,
  lang: Lang,
  difficulty: Difficulty = "normal",
): RejectionReason | null {
  if (!cand) return "missing_entry";
  if (cand.id === target.id || cand.lemma.toLowerCase() === target.lemma.toLowerCase()) return "same_word";
  if (cand.pos !== target.pos) return "pos_mismatch";
  if (Math.abs(levelIndex(cand.level) - levelIndex(target.level)) > 1) return "level_out_of_range";
  if (!target.group || !cand.group) return "unknown_semantic_group";
  if (difficulty === "hard") {
    if (hardGroupOf(cand) !== hardGroupOf(target)) return "different_semantic_group";
    if (target.group.startsWith("adj:") && cand.group === target.group) return "same_cluster";
  } else if (cand.group === target.group) return "same_semantic_group";
  const cDef = bestDefinition(cand, lang);
  const tDef = bestDefinition(target, lang);
  if (!cDef || !tDef) return "no_definition_in_lang";
  if (cDef.text.trim().toLowerCase() === tDef.text.trim().toLowerCase()) return "duplicate_definition";
  return null;
}

export interface QuestionCheck {
  ok: boolean;
  reasons: string[];
  validDistractors: Entry[];
}

export function checkPackQuestion(
  q: PackQuestion,
  lexicon: Lexicon,
  minDistractors = 2,
  difficulty: Difficulty = "normal",
): QuestionCheck {
  const target = lexicon.entry(q.entryId);
  if (!target) return { ok: false, reasons: ["missing_entry"], validDistractors: [] };
  const reasons: string[] = [];
  if (!isLangAllowed(target.level, q.lang)) reasons.push("lang_not_allowed");
  if (!bestDefinition(target, q.lang)) reasons.push("no_definition_in_lang");
  const pool = difficulty === "hard" ? (q.hard ?? []) : q.distractors;
  const validDistractors: Entry[] = [];
  const seenTexts = new Set<string>([bestDefinition(target, q.lang)?.text.toLowerCase() ?? ""]);
  for (const id of pool) {
    const cand = lexicon.entry(id);
    if (distractorRejection(target, cand, q.lang, difficulty) !== null) continue;
    const text = bestDefinition(cand!, q.lang)!.text.toLowerCase();
    if (seenTexts.has(text)) continue;
    seenTexts.add(text);
    validDistractors.push(cand!);
  }
  if (validDistractors.length < minDistractors) reasons.push("insufficient_distractors");
  return { ok: reasons.length === 0, reasons, validDistractors };
}
