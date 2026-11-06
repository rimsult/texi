import { type Deck, type Difficulty, LEVELS, type Lang, type Level } from "./types";

export const levelIndex = (level: Level): number => LEVELS.indexOf(level);

/** A1–A2 may use Russian definitions; B1 and above are English-only. */
export function allowedLangs(level: Level): Lang[] {
  return levelIndex(level) <= 1 ? ["ru", "en"] : ["en"];
}

export function isLangAllowed(level: Level, lang: Lang): boolean {
  return allowedLangs(level).includes(lang);
}

/** Levels whose packs are needed to render questions of `level` (distractors are ±1). */
export function neighbourLevels(level: Level): Level[] {
  const i = levelIndex(level);
  return LEVELS.slice(Math.max(0, i - 1), i + 2);
}

export const LEVEL_INFO: Record<Level, { title: string; description: string }> = {
  A1: { title: "Beginner", description: "Базовые слова: семья, еда, дом" },
  A2: { title: "Elementary", description: "Повседневные ситуации и простые темы" },
  B1: { title: "Intermediate", description: "Работа, учёба, путешествия" },
  B2: { title: "Upper-Intermediate", description: "Абстрактные темы и аргументы" },
  C1: { title: "Advanced", description: "Академическая и профессиональная лексика" },
  C2: { title: "Proficiency", description: "Редкие и тонкие значения" },
};

export const DECK_INFO: Record<Deck, { title: string; short: string; description: string }> = {
  general: { title: "Общая лексика", short: "Общая", description: "Повседневные и академические слова A1–C2" },
  tech: { title: "Техническая лексика", short: "Техническая", description: "ИТ, электротехника, физика, математика, химия, инженерия" },
};

export const DIFFICULTY_INFO: Record<Difficulty, { title: string; description: string }> = {
  normal: { title: "Обычная", description: "Варианты из разных смысловых групп" },
  hard: { title: "Сложная", description: "Варианты из той же смысловой группы — близкие по смыслу слова" },
};
