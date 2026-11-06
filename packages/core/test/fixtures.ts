import type { ContentPack, Entry, Level, PackQuestion, PartOfSpeech } from "../src";

let n = 0;
export function entry(lemma: string, group: string, opts: Partial<Entry> & { en?: string; ru?: string } = {}): Entry {
  const { en = `meaning of ${lemma} number ${++n}`, ru, ...rest } = opts;
  return {
    id: `${lemma}-n`,
    lemma,
    pos: "noun" as PartOfSpeech,
    level: "A1" as Level,
    group,
    definitions: [
      { text: en, lang: "en", source: "wordnet", quality: 0.9 },
      ...(ru ? [{ text: ru, lang: "ru" as const, source: "machine" as const, quality: 0.7 }] : []),
    ],
    example: `An example with ${lemma}.`,
    ...rest,
  };
}

/** Synthetic A1/A2/B1 world with valid distractors in different semantic groups. */
export function world(): ContentPack[] {
  const a1: Entry[] = [
    entry("dog", "noun.animal", { ru: "одомашненное хищное млекопитающее", translation: "собака", en: "a domesticated carnivorous mammal" }),
    entry("apple", "noun.food", { ru: "плод с красной или жёлтой кожурой", translation: "яблоко", en: "fruit with red or yellow skin" }),
    entry("table", "noun.artifact", { ru: "предмет мебели с плоским верхом", translation: "стол", en: "a piece of furniture with a flat top" }),
    entry("morning", "noun.time", { ru: "первая часть дня", translation: "утро", en: "the first part of the day" }),
    entry("mother", "noun.person", { ru: "родитель женского пола", translation: "мать", en: "a female parent" }),
  ];
  const a2: Entry[] = [entry("joy", "noun.feeling", { level: "A2", ru: "большое счастье", translation: "радость", en: "great happiness" })];
  const b1: Entry[] = [
    entry("idea", "noun.cognition", { level: "B1", en: "a thought or suggestion" }),
    entry("journey", "noun.act", { level: "B1", en: "travel from one place to another" }),
    entry("weather", "noun.phenomenon", { level: "B1", en: "the state of the atmosphere" }),
  ];
  const others = (e: Entry, pool: Entry[]) => pool.filter((x) => x.id !== e.id).map((x) => x.id);
  const q = (e: Entry, pool: Entry[], langs: ("en" | "ru")[]): PackQuestion[] =>
    ["word-to-definition", "definition-to-word"].flatMap((trainer) =>
      langs.map((lang) => ({ trainer, entryId: e.id, lang, distractors: others(e, pool) })),
    );
  const a12 = [...a1, ...a2];
  return [
    { schemaVersion: 1, level: "A1", entries: a1, questions: a1.flatMap((e) => q(e, a12, ["ru", "en"])) },
    { schemaVersion: 1, level: "A2", entries: a2, questions: a2.flatMap((e) => q(e, a12, ["ru", "en"])) },
    {
      schemaVersion: 1,
      level: "B1",
      entries: b1,
      questions: b1.flatMap((e) => q(e, [...b1, ...a2], ["en"])),
    },
  ];
}
