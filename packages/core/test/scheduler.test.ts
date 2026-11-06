import { describe, expect, it } from "vitest";
import { applyAnswer, BOX_INTERVALS_MS, createRng, type ItemProgress, levelStats, MAX_BOX, planSession } from "../src";

const item = { trainerId: "word-to-definition", entryId: "dog-n", level: "A1" as const };
const T0 = Date.UTC(2026, 0, 1);

describe("Leitner scheduling", () => {
  it("promotes known new words and demotes mistakes", () => {
    const first = applyAnswer(undefined, item, true, T0);
    expect(first).toMatchObject({ key: "word-to-definition:dog-n", box: 2, seen: 1, correct: 1, wrong: 0 });
    expect(first.due).toBe(T0 + BOX_INTERVALS_MS[2]);
    const wrong = applyAnswer(first, item, false, T0 + 1);
    expect(wrong).toMatchObject({ box: 1, seen: 2, wrong: 1 });
    expect(wrong.due).toBe(T0 + 1 + BOX_INTERVALS_MS[1]);
    const newWrong = applyAnswer(undefined, item, false, T0);
    expect(newWrong.box).toBe(1);
  });

  it("caps at the last box", () => {
    let p: ItemProgress | undefined;
    for (let i = 0; i < 10; i++) p = applyAnswer(p, item, true, T0 + i);
    expect(p!.box).toBe(MAX_BOX);
  });
});

describe("session planning", () => {
  const items = Array.from({ length: 30 }, (_, i) => `w${i}-n`);
  const prog = (id: string, due: number, box = 1): [string, ItemProgress] => [
    id,
    { key: `t:${id}`, trainerId: "t", entryId: id, level: "A1", box, due, seen: 1, correct: 0, wrong: 1, lastAnsweredAt: 0 },
  ];

  it("returns the requested size with no duplicates", () => {
    const plan = planSession({ items, progress: new Map(), size: 10, now: T0, rng: createRng(1) });
    expect(plan).toHaveLength(10);
    expect(new Set(plan).size).toBe(10);
  });

  it("prioritises due reviews and mixes in new words", () => {
    const progress = new Map([prog("w1-n", T0 - 1), prog("w2-n", T0 - 5), prog("w3-n", T0 + 1e9)]);
    const plan = planSession({ items, progress, size: 10, now: T0, rng: createRng(2) });
    expect(plan).toEqual(expect.arrayContaining(["w1-n", "w2-n"]));
    expect(plan).not.toContain("w3-n");
  });

  it("falls back to early reviews when everything has been seen", () => {
    const progress = new Map(items.map((id) => prog(id, T0 + 1000)));
    expect(planSession({ items, progress, size: 5, now: T0, rng: createRng(3) })).toHaveLength(5);
  });

  it("handles small item sets", () => {
    expect(planSession({ items: ["a", "b"], progress: new Map(), size: 10, now: T0, rng: createRng(1) }).sort()).toEqual(["a", "b"]);
  });

  it("computes level statistics", () => {
    const progress = new Map([prog("w1-n", T0 - 1, 4), prog("w2-n", T0 + 1, 2)]);
    expect(levelStats(items, progress, T0)).toEqual({ total: 30, seen: 2, mastered: 1, due: 1, accuracy: 0 });
  });
});
