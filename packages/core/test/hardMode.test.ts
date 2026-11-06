import { describe, expect, it } from "vitest";
import {
  checkPackQuestion,
  type ContentPack,
  createRng,
  deckOfEntry,
  definitionToWord,
  distractorRejection,
  type Entry,
  Lexicon,
  type McqQuestion,
  type TrainerContext,
  TrainingSession,
  wordToDefinition,
} from "../src";
import { entry } from "./fixtures";

/** A1 world where some words also have same-group ("hard") distractor pools. */
function hardWorld(): ContentPack[] {
  const food = ["lunch", "dinner", "breakfast", "supper", "brunch"].map((w) =>
    entry(w, "noun.food", { en: `${w} — a meal number ${w.length}`, ru: `ру-${w}` }),
  );
  const others = [
    entry("dog", "noun.animal", { en: "a domesticated carnivorous mammal", ru: "одомашненное хищное млекопитающее" }),
    entry("table", "noun.artifact", { en: "a piece of furniture with a flat top", ru: "предмет мебели с плоским верхом" }),
    entry("morning", "noun.time", { en: "the first part of the day", ru: "первая часть дня" }),
  ];
  const big = entry("big", "adj:large.a.01", { pos: "adjective", hardGroup: "adjfam:large.a.01", id: "big-adj", en: "above average in size", ru: "большой" });
  const huge = entry("huge", "adj:large.a.01", { pos: "adjective", hardGroup: "adjfam:large.a.01", id: "huge-adj", en: "unusually great in size", ru: "огромный" });
  const small = entry("small", "adj:small.a.01", { pos: "adjective", hardGroup: "adjfam:large.a.01", id: "small-adj", en: "limited in size", ru: "маленький" });
  const little = entry("little", "adj:small.a.01", { pos: "adjective", hardGroup: "adjfam:large.a.01", id: "little-adj", en: "of short duration or distance", ru: "небольшой" });
  const happy = entry("happy", "adj:happy.a.01", { pos: "adjective", id: "happy-adj", en: "enjoying well-being", ru: "счастливый" });
  const cold = entry("cold", "adj:cold.a.01", { pos: "adjective", id: "cold-adj", en: "having a low temperature", ru: "холодный" });
  const entries = [...food, ...others, big, huge, small, little, happy, cold];
  const ids = (xs: Entry[]) => xs.map((e) => e.id);
  const questions = (e: Entry, distractors: string[], hard?: string[]) =>
    ["word-to-definition", "definition-to-word"].flatMap((trainer) =>
      (["ru", "en"] as const).map((lang) => ({ trainer, entryId: e.id, lang, distractors, ...(hard ? { hard } : {}) })),
    );
  const [lunch, dinner, breakfast, supper, brunch] = food;
  return [
    {
      schemaVersion: 2,
      deck: "general",
      level: "A1",
      entries,
      questions: [
        // pool order = similarity: brunch is 4th, so it must never be drawn
        ...questions(lunch!, ids(others), ids([dinner!, breakfast!, supper!, brunch!])),
        ...questions(dinner!, ids(others), ids([lunch!, supper!, breakfast!])),
        ...questions(breakfast!, ids(others)), // no hard pool
        // a corrupted pool: "huge" shares big's cluster, "dog" is another group
        ...questions(big, ids([happy, cold]), ["huge-adj", "dog-n", "small-adj", "little-adj"]),
      ],
    },
  ];
}

const ctx = (difficulty: "normal" | "hard", seed = 1, lang: "ru" | "en" = "en"): TrainerContext => ({
  lexicon: new Lexicon(hardWorld()),
  level: "A1",
  preferredLang: lang,
  rng: createRng(seed),
  difficulty,
});
const groupOf = (lex: Lexicon, id: string) => lex.entry(id)!.group;

describe("hard mode (same semantic group)", () => {
  it("lists only words that have a hard pool", () => {
    expect(wordToDefinition.items(ctx("normal")).sort()).toEqual(["big-adj", "breakfast-n", "dinner-n", "lunch-n"]);
    expect(wordToDefinition.items(ctx("hard")).sort()).toEqual(["big-adj", "dinner-n", "lunch-n"]);
  });

  it("builds options from the answer's own group, drawn from the closest three", () => {
    const seen = new Set<string>();
    for (let seed = 0; seed < 40; seed++) {
      const c = ctx("hard", seed);
      const q = wordToDefinition.build("lunch-n", c)!;
      expect(q.difficulty).toBe("hard");
      expect(q.id).toBe("word-to-definition:lunch-n:en:hard");
      expect(q.options).toHaveLength(3);
      for (const o of q.options) {
        expect(groupOf(c.lexicon, o.id)).toBe("noun.food");
        seen.add(o.id);
      }
    }
    expect(seen.has("brunch-n")).toBe(false);
    expect(seen).toEqual(new Set(["lunch-n", "dinner-n", "breakfast-n", "supper-n"]));
  });

  it("normal mode keeps using different groups", () => {
    const c = ctx("normal");
    const q = definitionToWord.build("lunch-n", c)!;
    expect(q.difficulty).toBe("normal");
    expect(q.id).toBe("definition-to-word:lunch-n:en");
    const groups = q.options.filter((o) => o.id !== "lunch-n").map((o) => groupOf(c.lexicon, o.id));
    expect(groups).not.toContain("noun.food");
  });

  it("re-checks hard pools on the client: same family, never the same adjective cluster", () => {
    const c = ctx("hard", 3, "ru");
    const lex = c.lexicon;
    const big = lex.entry("big-adj")!;
    expect(distractorRejection(big, lex.entry("huge-adj"), "ru", "hard")).toBe("same_cluster");
    expect(distractorRejection(big, lex.entry("dog-n"), "ru", "hard")).toBe("pos_mismatch");
    expect(distractorRejection(big, lex.entry("small-adj"), "ru", "hard")).toBeNull();
    expect(distractorRejection(big, lex.entry("small-adj"), "ru", "normal")).toBeNull();
    expect(distractorRejection(lex.entry("lunch-n")!, lex.entry("dinner-n"), "en", "normal")).toBe("same_semantic_group");
    expect(distractorRejection(lex.entry("lunch-n")!, lex.entry("dog-n"), "en", "hard")).toBe("different_semantic_group");
    const q = lex.questionsFor("A1", "word-to-definition").find((x) => x.entryId === "big-adj" && x.lang === "ru")!;
    const check = checkPackQuestion(q, lex, 2, "hard");
    expect(check.ok).toBe(true);
    expect(check.validDistractors.map((e) => e.id)).toEqual(["small-adj", "little-adj"]);
    const built = wordToDefinition.build("big-adj", c)!;
    expect(built.options.map((o) => o.text).sort()).toEqual(["большой", "маленький", "небольшой"]);
  });

  it("drops a hard question when fewer than two valid options remain", () => {
    const packs = hardWorld();
    const q = packs[0]!.questions.find((x) => x.entryId === "dinner-n" && x.lang === "en" && x.trainer === "word-to-definition")!;
    q.hard = ["lunch-n", "dog-n"];
    const c = { ...ctx("hard"), lexicon: new Lexicon(packs) };
    expect(wordToDefinition.build("dinner-n", c)).toBeNull();
  });

  it("records difficulty and deck on attempt events", () => {
    const c = ctx("hard");
    const s = new TrainingSession<McqQuestion>(wordToDefinition, c, ["lunch-n", "dinner-n"], 0);
    const { event } = s.answer(s.current!.correctOptionId, 1500);
    expect(event).toMatchObject({ difficulty: "hard", deck: "general", correct: true, durationMs: 1500 });
  });
});

describe("technical deck", () => {
  const techPack = (): ContentPack => {
    const mk = (w: string, group: string, domain: string) =>
      entry(w, group, { id: `tech:${w}-n`, domain, en: `technical meaning of ${w}`, ru: `тех-${w}` });
    const entries = [
      mk("voltage", "noun.attribute", "electrical"),
      mk("algorithm", "noun.cognition", "it"),
      mk("molecule", "noun.substance", "chemistry"),
    ];
    return {
      schemaVersion: 2,
      deck: "tech",
      level: "A1",
      entries,
      questions: entries.map((e) => ({
        trainer: "word-to-definition",
        entryId: e.id,
        lang: "en" as const,
        distractors: entries.filter((x) => x.id !== e.id).map((x) => x.id),
      })),
    };
  };

  it("derives the deck from the entry id", () => {
    expect(deckOfEntry("tech:voltage-n")).toBe("tech");
    expect(deckOfEntry("voltage-n")).toBe("general");
  });

  it("shows the field on reveal and tags events with the deck", () => {
    const c: TrainerContext = { lexicon: new Lexicon([techPack()]), level: "A1", preferredLang: "en", rng: createRng(5), deck: "tech" };
    const q = wordToDefinition.build("tech:voltage-n", c)!;
    expect(q.reveal.domain).toBe("electrical");
    const s = new TrainingSession<McqQuestion>(wordToDefinition, c, ["tech:voltage-n"], 0);
    expect(s.answer("wrong", 10).event).toMatchObject({ deck: "tech", difficulty: "normal", correct: false });
  });

  const fieldPack = (): ContentPack => {
    const mk = (w: string, group: string, domain: string) =>
      entry(w, group, { id: `tech:${w}-n`, domain, en: `technical meaning of ${w}`, ru: `тех-${w}` });
    const entries = [
      mk("voltage", "noun.attribute", "electrical"),
      mk("resistor", "noun.artifact", "electrical"),
      mk("capacitor", "noun.object", "electrical"),
      mk("algorithm", "noun.cognition", "it"),
      mk("compiler", "noun.communication", "it"),
      mk("triangle", "noun.shape", "math"),
    ];
    return {
      schemaVersion: 2,
      deck: "tech",
      level: "A1",
      entries,
      questions: entries.map((e) => ({
        trainer: "word-to-definition",
        entryId: e.id,
        lang: "en" as const,
        distractors: entries.filter((x) => x.id !== e.id).map((x) => x.id),
      })),
    };
  };

  it("limits words and options to the chosen fields", () => {
    const lexicon = new Lexicon([fieldPack()]);
    const c = (domains?: string[], seed = 1): TrainerContext => ({
      lexicon, level: "A1", preferredLang: "en", rng: createRng(seed), deck: "tech", ...(domains ? { domains } : {}),
    });
    expect(wordToDefinition.items(c()).length).toBe(6);
    expect(wordToDefinition.items(c([]))).toHaveLength(6); // empty selection = every field
    expect(wordToDefinition.items(c(["electrical"])).sort()).toEqual(["tech:capacitor-n", "tech:resistor-n", "tech:voltage-n"]);
    expect(wordToDefinition.items(c(["it", "math"]))).toHaveLength(3);
    for (let seed = 1; seed <= 20; seed++) {
      const q = wordToDefinition.build("tech:voltage-n", c(["electrical"], seed))!;
      const domains = q.options.map((o) => lexicon.entry(o.id)!.domain);
      expect(domains.every((d) => d === "electrical")).toBe(true); // options from the same field
    }
    // A field with too few words for options borrows them from the rest of the deck.
    const q = wordToDefinition.build("tech:triangle-n", c(["math"]))!;
    expect(q.options).toHaveLength(3);
  });
});
