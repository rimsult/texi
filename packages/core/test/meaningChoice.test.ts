import { describe, expect, it } from "vitest";
import { createRng, definitionToWord, Lexicon, type McqQuestion, sessionLang, type TrainerContext, wordToDefinition } from "../src";
import { entry, world } from "./fixtures";

const ctx = (level: TrainerContext["level"], preferredLang: "ru" | "en" = "ru", seed = 1): TrainerContext => ({
  lexicon: new Lexicon(world()),
  level,
  preferredLang,
  rng: createRng(seed),
});

describe("word → definition", () => {
  it("builds 3 distinct options with exactly one correct", () => {
    const q = wordToDefinition.build("dog-n", ctx("A1"))!;
    expect(q.kind).toBe("mcq");
    expect(q.prompt).toMatchObject({ text: "dog", style: "word", lang: "en", pos: "noun" });
    expect(q.options).toHaveLength(3);
    expect(new Set(q.options.map((o) => o.id)).size).toBe(3);
    expect(new Set(q.options.map((o) => o.text)).size).toBe(3);
    expect(q.options.filter((o) => o.id === q.correctOptionId)).toHaveLength(1);
    // Russian mode shows the translated *definition*, the bare translation only after answering.
    expect(q.options.find((o) => o.id === q.correctOptionId)!.text).toBe("одомашненное хищное млекопитающее");
    expect(q.options.every((o) => o.lang === "ru")).toBe(true);
    expect(q.options.some((o) => o.text === "собака")).toBe(false);
    expect(q.reveal.english?.lang).toBe("en");
    expect(q.reveal.translation).toBe("собака");
  });

  it("does not reveal the Russian translation in English questions", () => {
    const q = wordToDefinition.build("dog-n", ctx("A1", "en"))!;
    expect(q.reveal.translation).toBeUndefined();
    expect(definitionToWord.build("dog-n", ctx("A1", "en"))!.reveal.translation).toBeUndefined();
    expect(definitionToWord.build("dog-n", ctx("A1", "ru"))!.reveal.translation).toBe("собака");
  });

  it("uses English at A1 when preferred", () => {
    const q = wordToDefinition.build("dog-n", ctx("A1", "en"))!;
    expect(q.lang).toBe("en");
    expect(q.options.find((o) => o.id === "dog-n")!.text).toBe("a domesticated carnivorous mammal");
  });

  it("keeps a session in one language: words without a Russian definition are skipped in ru mode", () => {
    const packs = world();
    const a1 = packs[0]!;
    a1.entries.push(entry("cup", "noun.artifact", { en: "a small open container for drinking" }));
    a1.questions.push({ trainer: "word-to-definition", entryId: "cup-n", lang: "en", distractors: ["dog-n", "apple-n"] });
    const c = (preferredLang: "ru" | "en"): TrainerContext => ({ lexicon: new Lexicon(packs), level: "A1", preferredLang, rng: createRng(3) });
    expect(wordToDefinition.items(c("ru"))).not.toContain("cup-n");
    expect(wordToDefinition.items(c("en"))).toContain("cup-n");
    for (const id of wordToDefinition.items(c("ru"))) expect(wordToDefinition.build(id, c("ru"))!.lang).toBe("ru");
    expect(sessionLang({ level: "A2", preferredLang: "ru" })).toBe("ru");
    expect(sessionLang({ level: "C1", preferredLang: "ru" })).toBe("en");
  });

  it("never shows Russian from B1, even if preferred", () => {
    const c = ctx("B1", "ru");
    for (const id of wordToDefinition.items(c)) {
      const q = wordToDefinition.build(id, c)!;
      expect(q.lang).toBe("en");
      expect(q.options.every((o) => !/[а-яё]/i.test(o.text))).toBe(true);
    }
  });

  it("checks answers", () => {
    const q = wordToDefinition.build("dog-n", ctx("A1"))!;
    expect(wordToDefinition.check(q, "dog-n").correct).toBe(true);
    const wrong = q.options.find((o) => o.id !== "dog-n")!.id;
    expect(wordToDefinition.check(q, wrong)).toEqual({ correct: false, correctAnswerId: "dog-n" });
  });

  it("is deterministic per seed but varies distractors across seeds", () => {
    const ids = (seed: number) => wordToDefinition.build("dog-n", ctx("A1", "ru", seed))!.options.map((o) => o.id).join();
    expect(ids(7)).toBe(ids(7));
    const variants = new Set(Array.from({ length: 30 }, (_, i) => ids(i).split(",").sort().join()));
    expect(variants.size).toBeGreaterThan(1);
  });

  it("returns null for unknown or invalid items", () => {
    expect(wordToDefinition.build("nope-n", ctx("A1"))).toBeNull();
    const c = ctx("A1");
    c.lexicon.add({ schemaVersion: 1, level: "A1", entries: [], questions: [{ trainer: "word-to-definition", entryId: "dog-n", lang: "ru", distractors: ["dog-n"] }] });
    expect(wordToDefinition.build("dog-n", c)).toBeNull();
  });
});

describe("definition → word", () => {
  it("shows the definition and offers words", () => {
    const q: McqQuestion = definitionToWord.build("apple-n", ctx("A1"))!;
    expect(q.prompt).toMatchObject({ text: "плод с красной или жёлтой кожурой", style: "definition", lang: "ru" });
    expect(q.options.map((o) => o.lang)).toEqual(["en", "en", "en"]);
    expect(q.options.map((o) => o.text)).toContain("apple");
    expect(q.instruction).toMatch(/слово/);
  });

  it("lists only items for its own trainer and level", () => {
    expect(definitionToWord.items(ctx("A2")).sort()).toEqual(["joy-n"]);
    expect(definitionToWord.items(ctx("B1")).sort()).toEqual(["idea-n", "journey-n", "weather-n"]);
  });
});

describe("feedback after answering", () => {
  it("explains every option: whose definition a wrong option was", () => {
    const q = wordToDefinition.build("dog-n", ctx("A1", "ru"))!;
    for (const o of q.options) {
      expect(o.explain.lemma).toBeTruthy();
      expect(o.explain.definition).toBeUndefined(); // the option text already is the definition
    }
    const wrong = q.options.find((o) => o.id !== q.correctOptionId)!;
    expect(wrong.explain.translation).toBeTruthy(); // ru mode: «это определение слова apple — яблоко»
    const d2w = definitionToWord.build("dog-n", ctx("A1", "en"))!;
    for (const o of d2w.options) {
      expect(o.explain.definition).toBeTruthy(); // word options: what the other words mean
      expect(o.explain.translation).toBeUndefined(); // no Russian in English mode
    }
  });

  it("reveals the example translation (Russian mode only) and synonyms", () => {
    const packs = world();
    Object.assign(packs[0]!.entries[0]!, { exampleRu: "Пример с собакой.", synonyms: ["hound"] });
    const c = (lang: "ru" | "en"): TrainerContext => ({ lexicon: new Lexicon(packs), level: "A1", preferredLang: lang, rng: createRng(2) });
    const ru = wordToDefinition.build("dog-n", c("ru"))!;
    expect(ru.reveal).toMatchObject({ example: "An example with dog.", exampleRu: "Пример с собакой.", synonyms: ["hound"] });
    const en = wordToDefinition.build("dog-n", c("en"))!;
    expect(en.reveal.exampleRu).toBeUndefined();
    expect(en.reveal.synonyms).toEqual(["hound"]);
  });
});
