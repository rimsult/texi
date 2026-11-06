import { describe, expect, it } from "vitest";
import {
  checkGapQuestion,
  type ContentPack,
  createRng,
  type Entry,
  gapFill,
  Lexicon,
  maskSentence,
  type PackQuestion,
  type TrainerContext,
} from "../src";
import { entry } from "./fixtures";

const SENTENCE = "I ate an apple for lunch.";

function gapWorld(overrides: Partial<PackQuestion> = {}, extra: Entry[] = []): ContentPack[] {
  const apple = entry("apple", "noun.food", {
    en: "a round fruit", ru: "круглый плод", translation: "яблоко", example: SENTENCE, exampleRu: "Я съел яблоко на обед.",
  });
  const others = [
    entry("idea", "noun.cognition", { en: "a thought" }),
    entry("river", "noun.object", { en: "a large stream of water", ru: "большой поток воды", translation: "река" }),
    entry("song", "noun.communication", { en: "music with words" }),
    entry("banana", "noun.food", { en: "a long yellow fruit" }), // same group: never valid
    ...extra,
  ];
  const q: PackQuestion = {
    trainer: "gap-fill", entryId: "apple-n", lang: "en",
    distractors: ["idea-n", "river-n", "song-n", "banana-n"],
    span: [9, 14], forms: ["apple", "idea", "river", "song", "banana"],
    ...overrides,
  };
  return [{ schemaVersion: 2, level: "A1", entries: [apple, ...others], questions: [q] }];
}

const ctx = (packs: ContentPack[], preferredLang: "ru" | "en" = "en", seed = 3): TrainerContext => ({
  lexicon: new Lexicon(packs), level: "A1", preferredLang, rng: createRng(seed),
});

describe("gap-fill trainer", () => {
  it("builds a sentence with a gap and three same-form options", () => {
    const q = gapFill.build("apple-n", ctx(gapWorld()))!;
    expect(q.trainerId).toBe("gap-fill");
    expect(q.lang).toBe("en");
    expect(q.prompt.style).toBe("sentence");
    expect(q.prompt.text).toBe("I ate a/an ___ for lunch.");
    expect(q.prompt.gap).toEqual({ before: "I ate an ", after: " for lunch.", answer: "apple" });
    expect(q.options).toHaveLength(3);
    expect(q.options.find((o) => o.id === q.correctOptionId)!.text).toBe("apple");
    expect(q.options.some((o) => o.id === "banana-n")).toBe(false); // same semantic group
    expect(q.reveal.example).toBe(SENTENCE);
    expect(gapFill.check(q, "apple-n").correct).toBe(true);
    expect(gapFill.check(q, "idea-n").correct).toBe(false);
  });

  it("explains in Russian at A1–A2 when Russian is preferred", () => {
    const q = gapFill.build("apple-n", ctx(gapWorld(), "ru"))!;
    expect(q.lang).toBe("en");
    expect(q.reveal.definition).toMatchObject({ lang: "ru", text: "круглый плод" });
    expect(q.reveal.english?.text).toBe("a round fruit");
    expect(q.reveal.translation).toBe("яблоко");
    expect(q.reveal.exampleRu).toBe("Я съел яблоко на обед.");
    const en = gapFill.build("apple-n", ctx(gapWorld(), "en"))!;
    expect(en.reveal.definition.lang).toBe("en");
    expect(en.reveal.translation).toBeUndefined();
  });

  it("lists only words with a gap question and ignores hard mode", () => {
    const packs = gapWorld();
    expect(gapFill.items(ctx(packs))).toEqual(["apple-n"]);
    expect(gapFill.items({ ...ctx(packs), difficulty: "hard" })).toEqual(["apple-n"]);
    expect(gapFill.build("idea-n", ctx(packs))).toBeNull();
  });

  it("rejects broken pack questions", () => {
    const lex = (o: Partial<PackQuestion>) => new Lexicon(gapWorld(o));
    const q = (o: Partial<PackQuestion>) => lex(o).questionsFor("A1", "gap-fill")[0]!;
    expect(checkGapQuestion(q({}), lex({})).ok).toBe(true);
    expect(checkGapQuestion(q({ span: [0, 5] }), lex({ span: [0, 5] })).reasons).toContain("span_mismatch");
    expect(checkGapQuestion(q({ span: [9, 99] }), lex({ span: [9, 99] })).reasons).toContain("bad_span");
    const short = { forms: ["apple", "idea"] };
    expect(checkGapQuestion(q(short), lex(short)).reasons).toContain("forms_mismatch");
    // a distractor form that already occurs in the sentence is dropped
    const inSentence = { forms: ["apple", "lunch", "river", "song", "banana"] };
    expect(checkGapQuestion(q(inSentence), lex(inSentence)).options.map((o) => o.form)).toEqual(["river", "song"]);
    const two = { distractors: ["idea-n", "banana-n"], forms: ["apple", "idea", "banana"] };
    expect(checkGapQuestion(q(two), lex(two)).reasons).toContain("insufficient_distractors");
    expect(gapFill.build("apple-n", ctx(gapWorld(two)))).toBeNull();
  });

  it("never offers an adjective from the answer's antonym family", () => {
    const adj = (lemma: string, group: string, fam: string, example?: string) =>
      entry(lemma, group, { pos: "adjective", hardGroup: fam, ...(example ? { example } : {}) });
    const packs: ContentPack[] = [{
      schemaVersion: 2, level: "A1",
      entries: [
        { ...adj("hot", "adj:hot", "adjfam:cold.a.01", "The soup is very hot today."), id: "hot-a" },
        { ...adj("cold", "adj:cold", "adjfam:cold.a.01"), id: "cold-a" },
        { ...adj("loud", "adj:loud", "adjfam:loud.a.01"), id: "loud-a" },
        { ...adj("busy", "adj:busy", "adjfam:busy.a.01"), id: "busy-a" },
      ],
      questions: [{ trainer: "gap-fill", entryId: "hot-a", lang: "en", distractors: ["cold-a", "loud-a", "busy-a"], span: [17, 20], forms: ["hot", "cold", "loud", "busy"] }],
    }];
    const check = checkGapQuestion(packs[0]!.questions[0]!, new Lexicon(packs));
    expect(check.ok).toBe(true);
    expect(check.options.map((o) => o.form)).toEqual(["loud", "busy"]);
  });

  it("masks a/an before the gap only", () => {
    expect(maskSentence("I ate an ", " for lunch.")).toBe("I ate a/an ___ for lunch.");
    expect(maskSentence("A ", " fell.")).toBe("A/An ___ fell.");
    expect(maskSentence("I saw a ", ".")).toBe("I saw a/an ___.");
    expect(maskSentence("I have ", " apples.")).toBe("I have ___ apples.");
    expect(maskSentence("Give me banana", ".")).toBe("Give me banana___.");
  });
});
