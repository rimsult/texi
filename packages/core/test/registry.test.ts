import { describe, expect, it } from "vitest";
import {
  type BaseQuestion,
  createDefaultRegistry,
  createRng,
  Lexicon,
  TrainerRegistry,
  type TrainerPlugin,
  TrainingSession,
} from "../src";
import { world } from "./fixtures";

interface SpellingQuestion extends BaseQuestion {
  kind: "spelling";
  hint: string;
  answer: string;
}

/** A brand-new trainer type built only against the public contract. */
const spelling: TrainerPlugin<SpellingQuestion, string> = {
  id: "spelling",
  title: "Spelling",
  subtitle: "Type the word",
  icon: "⌨️",
  availability: "ready",
  kind: "spelling",
  items: (ctx) => ["dog-n", "apple-n"].filter((id) => ctx.lexicon.entry(id)),
  build: (id, ctx) => {
    const e = ctx.lexicon.entry(id);
    return e
      ? { id: `spelling:${id}`, kind: "spelling", trainerId: "spelling", entryId: id, level: e.level, lang: "en", hint: e.definitions[0]!.text, answer: e.lemma }
      : null;
  },
  check: (q, a) => ({ correct: a.trim().toLowerCase() === q.answer, correctAnswerId: q.answer }),
};

describe("TrainerRegistry", () => {
  it("ships two main trainers, the optional gap-fill and roadmap placeholders", () => {
    const reg = createDefaultRegistry();
    expect(reg.ready().map((t) => t.id)).toEqual(["word-to-definition", "definition-to-word", "gap-fill"]);
    expect(reg.ready().filter((t) => t.tier === "extra").map((t) => t.id)).toEqual(["gap-fill"]);
    expect(reg.get("gap-fill")).toMatchObject({ questionLang: "en", supportsHard: false, kind: "mcq" });
    expect(reg.list().filter((t) => t.availability === "soon").map((t) => t.id)).toEqual(["listening", "grammar"]);
    const soon = reg.get("listening")!;
    expect(soon.items({} as never)).toEqual([]);
  });

  it("rejects duplicate ids", () => {
    const reg = createDefaultRegistry();
    expect(() => reg.register(reg.get("word-to-definition")!)).toThrow(/already registered/);
  });

  it("runs a new plugin through the unchanged session engine", () => {
    const reg = new TrainerRegistry().register(spelling);
    const plugin = reg.get("spelling") as typeof spelling;
    const ctx = { lexicon: new Lexicon(world()), level: "A1" as const, preferredLang: "en" as const, rng: createRng(1) };
    const session = new TrainingSession(plugin, ctx, plugin.items(ctx));
    expect(session.total).toBe(2);
    expect(session.answer(" DOG ").result.correct).toBe(true);
  });
});
