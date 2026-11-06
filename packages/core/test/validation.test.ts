import { describe, expect, it } from "vitest";
import { checkPackQuestion, distractorRejection, Lexicon } from "../src";
import { entry, world } from "./fixtures";

describe("distractor validation", () => {
  const dog = entry("dog", "noun.animal", { ru: "собака" });
  it.each([
    [{ pos: "verb" as const }, "pos_mismatch"],
    [{ level: "B1" as const }, "level_out_of_range"],
    [{ group: "noun.animal" }, "same_semantic_group"],
    [{ group: null }, "unknown_semantic_group"],
    [{ lemma: "Dog", id: "dog2-n" }, "same_word"],
  ])("rejects %o with %s", (override, reason) => {
    const cand = { ...entry("table", "noun.artifact", { ru: "стол" }), ...override };
    expect(distractorRejection(dog, cand, "en")).toBe(reason);
  });

  it("requires a definition in the question language", () => {
    const noRu = entry("table", "noun.artifact");
    expect(distractorRejection(dog, noRu, "ru")).toBe("no_definition_in_lang");
    expect(distractorRejection(dog, noRu, "en")).toBeNull();
  });

  it("rejects duplicate definitions and missing entries", () => {
    const twin = entry("hound", "noun.artifact", { en: dog.definitions[0]!.text.toUpperCase() });
    expect(distractorRejection(dog, twin, "en")).toBe("duplicate_definition");
    expect(distractorRejection(dog, undefined, "en")).toBe("missing_entry");
  });

  it("drops invalid distractors and flags insufficient pools", () => {
    const lex = new Lexicon(world());
    const ok = checkPackQuestion({ trainer: "word-to-definition", entryId: "dog-n", lang: "ru", distractors: ["apple-n", "idea-n", "nope-n", "table-n"] }, lex);
    expect(ok.ok).toBe(true);
    expect(ok.validDistractors.map((e) => e.id)).toEqual(["apple-n", "table-n"]);
    const bad = checkPackQuestion({ trainer: "word-to-definition", entryId: "dog-n", lang: "ru", distractors: ["apple-n", "idea-n"] }, lex);
    expect(bad.ok).toBe(false);
    expect(bad.reasons).toContain("insufficient_distractors");
  });

  it("refuses Russian questions from B1 upwards", () => {
    const lex = new Lexicon(world());
    const res = checkPackQuestion({ trainer: "word-to-definition", entryId: "idea-n", lang: "ru", distractors: ["journey-n", "weather-n"] }, lex);
    expect(res.ok).toBe(false);
    expect(res.reasons).toContain("lang_not_allowed");
  });
});
