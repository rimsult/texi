import { describe, expect, it } from "vitest";
import { createRng, Lexicon, TrainingSession, wordToDefinition } from "../src";
import { world } from "./fixtures";

const ctx = () => ({ lexicon: new Lexicon(world()), level: "A1" as const, preferredLang: "ru" as const, rng: createRng(5) });

describe("TrainingSession", () => {
  it("runs a full session and summarises mistakes", () => {
    const s = new TrainingSession(wordToDefinition, ctx(), ["dog-n", "apple-n", "missing-n", "table-n"], 1000);
    expect(s.total).toBe(3); // invalid items are skipped, never shown
    const first = s.answer(s.current!.correctOptionId, 1500);
    expect(first.result.correct).toBe(true);
    expect(first.event).toMatchObject({ trainerId: "word-to-definition", entryId: "dog-n", level: "A1", lang: "ru", correct: true, durationMs: 500 });
    expect(first.event.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(() => s.answer("x")).toThrow(/already answered/);
    s.next(2000);
    const wrongId = s.current!.options.find((o) => o.id !== s.current!.correctOptionId)!.id;
    expect(s.answer(wrongId, 2600).result.correct).toBe(false);
    s.next(3000);
    s.answer(s.current!.correctOptionId, 3100);
    s.next(3200);
    expect(s.finished).toBe(true);
    const sum = s.summary(4000);
    expect(sum).toMatchObject({ total: 3, correct: 2, durationMs: 3000 });
    expect(sum.accuracy).toBeCloseTo(2 / 3);
    expect(sum.mistakes.map((m) => m.entryId)).toEqual(["apple-n"]);
    expect(() => s.answer("x")).toThrow(/finished/);
  });

  it("requires answering before moving on", () => {
    const s = new TrainingSession(wordToDefinition, ctx(), ["dog-n"]);
    expect(() => s.next()).toThrow(/Answer/);
  });
});
