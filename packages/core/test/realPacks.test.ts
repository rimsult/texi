/** Integration: every shipped question must build and pass client-side validation, in both decks and modes. */
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  type ContentManifest,
  type ContentPack,
  createRng,
  definitionToWord,
  DIFFICULTIES,
  gapFill,
  hardGroupOf,
  Lexicon,
  wordToDefinition,
} from "../src";

const dir = fileURLToPath(new URL("../../../apps/web/public/packs/", import.meta.url));
const hasPacks = existsSync(dir + "manifest.json");

describe.skipIf(!hasPacks)("real content packs", () => {
  const manifest = JSON.parse(readFileSync(dir + "manifest.json", "utf8")) as ContentManifest;
  const lexicons = new Map(
    manifest.decks.map((d) => [
      d.id,
      new Lexicon(d.levels.map((l) => JSON.parse(readFileSync(dir + l.file, "utf8")) as ContentPack)),
    ]),
  );
  const cases = manifest.decks.flatMap((deck) =>
    deck.levels.flatMap((l) =>
      DIFFICULTIES.flatMap((difficulty) =>
        [wordToDefinition, definitionToWord].map((t) => [deck.id, l.level, difficulty, t.id, t, l] as const),
      ),
    ),
  );

  it.each(cases)("%s %s %s %s: every item builds a valid 3-option question", (deck, level, difficulty, _id, trainer, info) => {
    const lexicon = lexicons.get(deck)!;
    for (const lang of ["ru", "en"] as const) {
      const ctx = { lexicon, level, preferredLang: lang, rng: createRng(42), deck, difficulty };
      const items = trainer.items(ctx);
      const sessionLang = ["A1", "A2"].includes(level) ? lang : "en";
      // A session never mixes languages: exactly the words that have a question in its language.
      expect(items.length).toBe((difficulty === "hard" ? info.hard : info.questions)?.[`${trainer.id}:${sessionLang}`] ?? 0);
      expect(items.length).toBeLessThanOrEqual(info.words);
      if (deck === "general") expect(items.length).toBeGreaterThan(difficulty === "hard" ? 200 : 300);
      for (const id of items) {
        const q = trainer.build(id, ctx);
        expect(q, `${deck} ${level} ${difficulty} ${id}`).not.toBeNull();
        expect(new Set(q!.options.map((o) => o.text.toLowerCase())).size).toBe(3);
        expect(q!.lang).toBe(sessionLang);
        if (difficulty === "hard") {
          const group = hardGroupOf(lexicon.entry(id)!);
          expect(q!.options.every((o) => hardGroupOf(lexicon.entry(o.id)!) === group)).toBe(true);
        }
        if (deck === "tech") expect(q!.reveal.domain).toBeTruthy();
      }
    }
  });

  const gapCases = manifest.decks.flatMap((deck) => deck.levels.map((l) => [deck.id, l.level, l] as const));

  it.each(gapCases)("%s %s gap-fill: every item builds a sentence with one gap and 3 options", (deck, level, info) => {
    const lexicon = lexicons.get(deck)!;
    for (const lang of ["ru", "en"] as const) {
      const ctx = { lexicon, level, preferredLang: lang, rng: createRng(7), deck };
      const items = gapFill.items(ctx);
      expect(items.length).toBe(info.questions?.["gap-fill:en"] ?? 0);
      if (deck === "general") expect(items.length).toBeGreaterThan(100);
      for (const id of items) {
        const q = gapFill.build(id, ctx);
        expect(q, `${deck} ${level} ${id}`).not.toBeNull();
        expect(q!.prompt.text.split("___")).toHaveLength(2);
        const gap = q!.prompt.gap!;
        expect(gap.before + gap.answer + gap.after).toBe(lexicon.entry(id)!.example);
        expect(new Set(q!.options.map((o) => o.text.toLowerCase())).size).toBe(3);
        expect(q!.lang).toBe("en");
      }
    }
  });

  it("ships no definition with a \"___\" blank (learner frames are rewritten)", () => {
    for (const d of manifest.decks)
      for (const l of d.levels) {
        const pack = JSON.parse(readFileSync(dir + l.file, "utf8")) as ContentPack;
        const blanks = pack.entries.flatMap((e) => e.definitions.filter((x) => x.text.includes("___")).map((x) => `${e.id}: ${x.text}`));
        expect(blanks).toEqual([]);
      }
  });
});
