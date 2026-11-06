import {
  type AttemptEvent,
  type ContentManifest,
  type ContentPack,
  createDefaultRegistry,
  type Entry,
  LEVELS,
  type ManifestLevel,
  type PackQuestion,
} from "@lexi/core";
import { world } from "../../../packages/core/test/fixtures";
import { ContentService } from "../src/services/content";
import { openDatabase } from "../src/services/db";
import type { Services } from "../src/services";
import { LocalStore } from "../src/services/store";
import { SyncManager } from "../src/services/sync";

let dbCounter = 0;

/**
 * Fixture packs keyed by file name (without .json): the core "world" as the general
 * deck — A1/A2 words share one hard-mode family so hard pools exist there, B1 has
 * none — plus a tiny technical deck at A1.
 */
export function fixturePacks(): Record<string, ContentPack> {
  const packs: Record<string, ContentPack> = {};
  for (const p of world()) {
    const easy = p.level === "A1" || p.level === "A2";
    const entries = p.entries.map((e) => (easy ? { ...e, hardGroup: "noun.fixture" } : e));
    const questions = p.questions.map((q) =>
      p.level === "A1" ? { ...q, hard: q.distractors.filter((d) => entries.some((e) => e.id === d)) } : q,
    );
    packs[p.level] = { ...p, schemaVersion: 2, deck: "general", entries, questions: [...questions, ...gapQuestions(p.level, entries)] };
  }
  for (const l of LEVELS) packs[l] ??= { schemaVersion: 2, deck: "general", level: l, entries: [], questions: [] };
  packs["tech-A1"] = techPack();
  for (const l of LEVELS) packs[`tech-${l}`] ??= { schemaVersion: 2, deck: "tech", level: l, entries: [], questions: [] };
  return packs;
}

/** Gap-fill questions for A1: the fixture examples read "An example with <word>." */
function gapQuestions(level: string, entries: Entry[]): PackQuestion[] {
  if (level !== "A1") return [];
  return entries.map((e) => {
    const others = entries.filter((x) => x.id !== e.id);
    const start = e.example!.indexOf(e.lemma);
    return {
      trainer: "gap-fill", entryId: e.id, lang: "en" as const,
      distractors: others.map((x) => x.id),
      span: [start, start + e.lemma.length] as [number, number],
      forms: [e.lemma, ...others.map((x) => x.lemma)],
    };
  });
}

export const TECH_WORDS: Record<string, { field: string; en: string; ru: string; translation: string }> = {
  voltage: { field: "electrical", en: "the difference in electrical charge between two points", ru: "разность электрического заряда между двумя точками", translation: "напряжение" },
  algorithm: { field: "it", en: "a precise rule for solving a problem in steps", ru: "точное правило пошагового решения задачи", translation: "алгоритм" },
  molecule: { field: "chemistry", en: "the simplest structural unit of a compound", ru: "простейшая структурная единица соединения", translation: "молекула" },
};
export const FIELDS = { it: "ИТ", electrical: "Электротехника", physics: "Физика", math: "Математика", chemistry: "Химия", engineering: "Инженерия" };

function techPack(): ContentPack {
  const groups = ["noun.attribute", "noun.cognition", "noun.substance"];
  const entries: Entry[] = Object.entries(TECH_WORDS).map(([lemma, w], i) => ({
    id: `tech:${lemma}-n`,
    lemma,
    pos: "noun",
    level: "A1",
    group: groups[i]!,
    domain: w.field,
    definitions: [
      { text: w.en, lang: "en", source: "wordnet", quality: 0.9 },
      { text: w.ru, lang: "ru", source: "machine", quality: 0.7 },
    ],
    translation: w.translation,
  }));
  const questions = entries.flatMap((e) =>
    ["word-to-definition", "definition-to-word"].flatMap((trainer) =>
      (["ru", "en"] as const).map((lang) => ({
        trainer,
        entryId: e.id,
        lang,
        distractors: entries.filter((x) => x.id !== e.id).map((x) => x.id),
      })),
    ),
  );
  return { schemaVersion: 2, deck: "tech", level: "A1", entries, questions };
}

function levelInfo(file: string, pack: ContentPack): ManifestLevel {
  const count = (qs: PackQuestion[]) =>
    qs.reduce<Record<string, number>>((acc, q) => ({ ...acc, [`${q.trainer}:${q.lang}`]: (acc[`${q.trainer}:${q.lang}`] ?? 0) + 1 }), {});
  return {
    level: pack.level,
    file: `${file}.json`,
    words: new Set(pack.questions.map((q) => q.entryId)).size,
    bytes: 1,
    hash: "x",
    questions: count(pack.questions),
    hard: count(pack.questions.filter((q) => q.hard?.length)),
    ...(pack.deck === "tech" && pack.entries.length
      ? {
          fields: Object.fromEntries(
            [...new Set(pack.entries.map((e) => e.domain!))].map((f) => {
              const qs = pack.questions.filter((q) => pack.entries.find((e) => e.id === q.entryId)?.domain === f);
              return [f, { questions: count(qs), hard: count(qs.filter((q) => q.hard?.length)) }];
            }),
          ),
        }
      : {}),
  };
}

export function fixtureManifest(packs = fixturePacks()): ContentManifest {
  return {
    schemaVersion: 2,
    version: "test",
    decks: [
      { id: "general", title: "Общая лексика", description: "", levels: LEVELS.map((l) => levelInfo(l, packs[l]!)) },
      { id: "tech", title: "Техническая лексика", description: "", levels: LEVELS.map((l) => levelInfo(`tech-${l}`, packs[`tech-${l}`]!)) },
    ],
    fields: FIELDS,
    sources: [{ name: "Fixture", url: "https://example.org", license: "CC0" }],
  };
}

/** fetch() stub that serves packs and records requested files. */
export function packFetch(packs = fixturePacks()) {
  const calls: string[] = [];
  const fn = (async (input: RequestInfo | URL) => {
    const file = String(input).split("/").pop()!;
    calls.push(file);
    const body = file === "manifest.json" ? fixtureManifest(packs) : packs[file.replace(".json", "")];
    if (!body) return new Response("not found", { status: 404 });
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  return { fetch: fn, calls };
}

export async function makeStore(): Promise<LocalStore> {
  return new LocalStore(await openDatabase(`test-${++dbCounter}-${Math.random()}`));
}

export async function makeServices(opts: { store?: LocalStore; apiUrl?: string; apiFetch?: typeof fetch; contentFetch?: typeof fetch } = {}): Promise<Services> {
  const store = opts.store ?? (await makeStore());
  return {
    content: new ContentService("/packs/", opts.contentFetch ?? packFetch().fetch),
    store,
    sync: new SyncManager({ apiUrl: opts.apiUrl, store, fetchImpl: opts.apiFetch, isOnline: () => navigator.onLine }),
    registry: createDefaultRegistry(),
    now: () => Date.UTC(2026, 10, 4, 12),
    seed: () => 1234,
  };
}

export const RU_BY_LEMMA: Record<string, string> = Object.fromEntries(
  world().flatMap((p) => p.entries).map((e) => [e.lemma, e.definitions.find((d) => d.lang === "ru")?.text ?? ""]),
);
export const TRANSLATION_BY_LEMMA: Record<string, string> = Object.fromEntries(
  world().flatMap((p) => p.entries).map((e) => [e.lemma, e.translation ?? ""]),
);
export const EN_BY_LEMMA: Record<string, string> = Object.fromEntries(
  world().flatMap((p) => p.entries).map((e) => [e.lemma, e.definitions.find((d) => d.lang === "en")!.text]),
);

export const event = (i: number, trainerId = "word-to-definition"): AttemptEvent => ({
  id: `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
  trainerId,
  entryId: `w${i}-n`,
  level: "A1",
  lang: "ru",
  deck: "general",
  difficulty: "normal",
  correct: i % 2 === 0,
  answerId: `w${i}-n`,
  answeredAt: new Date(Date.UTC(2026, 0, 1, 0, i)).toISOString(),
  durationMs: 1000,
});
