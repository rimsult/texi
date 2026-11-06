/** Integration tests against a real PostgreSQL (set TEST_DATABASE_URL to run). */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { buildApp } from "../src/app";
import { migrate, withStartupLock } from "../src/migrate";
import { createPool, PgRepository } from "../src/pgRepo";
import { DEFAULT_OUT, DEFAULT_PACKS, seed, seedIfOutdated } from "../src/seed";
import { DEVICE, ev } from "./helpers";

const url = process.env.TEST_DATABASE_URL;

describe.skipIf(!url)("PostgreSQL repository", () => {
  const pool = createPool(url!);
  const repo = new PgRepository(pool);
  let app: Awaited<ReturnType<typeof buildApp>>;
  let seeded: Awaited<ReturnType<typeof seed>>;

  beforeAll(async () => {
    await pool.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public;");
    expect(await migrate(pool)).toEqual(["001_init.sql", "002_decks_hard_mode.sql", "003_ru_definitions.sql", "004_learner_definitions.sql", "005_gap_fill.sql"]);
    seeded = await seed(pool);
    app = await buildApp({ repo });
  }, 120_000);
  afterAll(async () => {
    await app?.close();
    await pool.end();
  });

  it("migrations are idempotent", async () => {
    expect(await migrate(pool)).toEqual([]);
  });

  it("serialises start-up work of concurrent instances with an advisory lock", async () => {
    const log: string[] = [];
    const step = (name: string) => async () => {
      log.push(`${name}:start`);
      await new Promise((r) => setTimeout(r, 50));
      log.push(`${name}:end`);
      return name;
    };
    expect(await Promise.all([withStartupLock(pool, step("a")), withStartupLock(pool, step("b"))])).toEqual(["a", "b"]);
    expect(log).toEqual(["a:start", "a:end", "b:start", "b:end"]);
    await expect(withStartupLock(pool, async () => Promise.reject(new Error("boom")))).rejects.toThrow("boom");
    expect(await withStartupLock(pool, async () => "released")).toBe("released");
  });

  it("seeds the full lexicon and review queue", async () => {
    const lexicon = JSON.parse(readFileSync(join(DEFAULT_OUT, "lexicon.json"), "utf8"));
    const review = JSON.parse(readFileSync(join(DEFAULT_OUT, "needs_review.json"), "utf8"));
    expect(seeded.lexemes).toBe(lexicon.length);
    expect(seeded.needsReview).toBe(review.length);
    const { rows } = await pool.query("SELECT status, count(*)::int AS n FROM questions GROUP BY status ORDER BY status");
    expect(rows).toEqual([
      { status: "needs_review", n: review.length },
      { status: "ok", n: seeded.questions - review.length },
    ]);
  });

  it("enforces content invariants in the schema", async () => {
    await expect(
      pool.query("INSERT INTO definitions (lexeme_id, text, lang, source, quality) VALUES ('dog-n', 'x', 'en', 'generated', 0.9)"),
    ).rejects.toThrow(/generated_quality_cap/);
    const b1 = (await pool.query("SELECT id FROM lexemes WHERE level = 'B1' LIMIT 1")).rows[0].id;
    await expect(
      pool.query("INSERT INTO questions (id, trainer, lexeme_id, lang, distractors, status) VALUES ('t1', 'word-to-definition', $1, 'ru', '{a,b}', 'ok')", [b1]),
    ).rejects.toThrow(/only allowed for A1-A2/);
    await expect(
      pool.query("INSERT INTO questions (id, trainer, lexeme_id, lang, distractors, status) VALUES ('t2', 'word-to-definition', 'dog-n', 'en', '{a}', 'ok')"),
    ).rejects.toThrow(/ok_needs_two_distractors/);
  });

  it("rebuilds client packs from the database identical to the static files", async () => {
    const manifest = JSON.parse(readFileSync(join(DEFAULT_PACKS, "manifest.json"), "utf8"));
    const fileOf = (deck: string, level: string) =>
      manifest.decks.find((d: { id: string }) => d.id === deck).levels.find((l: { level: string }) => l.level === level).file;
    type Q = { entryId: string; trainer: string; lang: string; distractors: string[]; hard?: string[]; span?: number[]; forms?: string[] };
    type E = {
      id: string; group: string; hardGroup?: string; domain?: string; translation?: string; example?: string; exampleRu?: string;
      synonyms?: string[]; definitions: { text: string; lang: string; source: string }[];
    };
    const key = (q: Q) =>
      `${q.entryId}|${q.trainer}|${q.lang}|${q.distractors.join(",")}|${(q.hard ?? []).join(",")}|${(q.span ?? []).join(",")}|${(q.forms ?? []).join(",")}`;
    const defs = (es: E[]) =>
      es
        .map((e) => [e.id, e.group, e.hardGroup, e.domain, e.translation, e.example, e.exampleRu, (e.synonyms ?? []).join(","),
          e.definitions.map((d) => d.lang + ":" + d.source + ":" + d.text).sort().join("/")].map((x) => x ?? "").join("|"))
        .sort();
    const cases: [string, string][] = [["general", "A1"], ["general", "B1"], ["general", "B2"], ["tech", "A2"], ["tech", "C1"]];
    for (const [deck, level] of cases) {
      const file = JSON.parse(readFileSync(join(DEFAULT_PACKS, fileOf(deck, level)), "utf8"));
      const db = (await app.inject(`/v1/content/packs/${level}${deck === "tech" ? "?deck=tech" : ""}`)).json();
      expect(db).toMatchObject({ schemaVersion: file.schemaVersion, deck, level });
      expect(db.questions.map(key).sort()).toEqual(file.questions.map(key).sort());
      expect(db.questions.some((q: Q) => q.trainer === "gap-fill" && q.span && q.forms)).toBe(file.questions.some((q: Q) => q.trainer === "gap-fill"));
      expect(defs(db.entries)).toEqual(defs(file.entries));
    }
    expect((await app.inject("/v1/content/manifest")).json().version).toBe(manifest.version);
    // Russian = machine-translated definitions; the short translation only where Russian questions exist
    const a1 = (await app.inject("/v1/content/packs/A1")).json();
    expect(a1.entries.some((e: { translation?: string }) => e.translation)).toBe(true);
    expect(a1.entries.flatMap((e: { definitions: { lang: string; source: string }[] }) => e.definitions)
      .filter((d: { lang: string }) => d.lang === "ru").every((d: { source: string }) => d.source === "machine")).toBe(true);
    const b1 = (await app.inject("/v1/content/packs/B1")).json();
    expect(b1.entries.some((e: { translation?: string }) => e.translation)).toBe(false);
  }, 30_000);

  it("keeps gap-fill questions well-formed in the schema", async () => {
    const { rows } = await pool.query("SELECT count(*)::int AS n FROM questions WHERE trainer = 'gap-fill' AND status = 'ok'");
    expect(rows[0].n).toBeGreaterThan(1000);
    await expect(
      pool.query("UPDATE questions SET gap_forms = '{a}' WHERE id = (SELECT id FROM questions WHERE trainer = 'gap-fill' AND status = 'ok' LIMIT 1)"),
    ).rejects.toThrow(/gap_fill_shape/);
    await expect(
      pool.query("UPDATE questions SET gap_span = '{0,4}' WHERE id = (SELECT id FROM questions WHERE trainer = 'word-to-definition' LIMIT 1)"),
    ).rejects.toThrow(/gap_fill_shape/);
  });

  it("keeps decks and hard mode consistent in the schema", async () => {
    await expect(
      pool.query("INSERT INTO lexemes (id, lemma, pos, level, semantic_group, deck) VALUES ('ohm-n', 'ohm', 'noun', 'B1', 'noun.quantity', 'tech')"),
    ).rejects.toThrow(/tech_ids_prefixed/);
    await expect(
      pool.query("UPDATE questions SET hard_distractors = '{x}' WHERE id = (SELECT id FROM questions LIMIT 1)"),
    ).rejects.toThrow(/hard_needs_two_distractors/);
    const { rows } = await pool.query("SELECT deck, count(*)::int AS n FROM lexemes GROUP BY deck ORDER BY deck");
    expect(rows.map((r) => r.deck)).toEqual(["general", "tech"]);
  });

  it("stores events idempotently, even under concurrent retries", async () => {
    const events = Array.from({ length: 50 }, (_, i) => ev({ correct: i % 5 !== 0, entryId: `w${i % 10}-n` }));
    const results = await Promise.all(
      [1, 2, 3].map(() => app.inject({ method: "POST", url: "/v1/sync", payload: { deviceId: DEVICE, events } })),
    );
    const accepted = results.flatMap((r) => r.json().accepted);
    expect(accepted.sort()).toEqual(events.map((e) => e.id).sort());
    const { rows } = await pool.query("SELECT count(*)::int AS n FROM attempt_events WHERE device_id = $1", [DEVICE]);
    expect(rows[0].n).toBe(50);
    const summary = (await app.inject(`/v1/devices/${DEVICE}/summary`)).json();
    expect(summary).toMatchObject({ events: 50, correct: 40, words: 10 });
    const stored = await pool.query("SELECT DISTINCT deck, difficulty FROM attempt_events WHERE device_id = $1", [DEVICE]);
    expect(stored.rows).toEqual([{ deck: "general", difficulty: "normal" }]);
  });

  it("stores the deck and difficulty of each answer", async () => {
    const other = "0b7f5e2a-1c3d-4e5f-8a9b-0c1d2e3f4a5b";
    const events = [
      ev({ deck: "tech", entryId: "tech:voltage-n", answerId: "tech:current-n", level: "B1", lang: "en", difficulty: "hard" }),
      ev({ difficulty: "hard" }),
    ];
    const res = await app.inject({ method: "POST", url: "/v1/sync", payload: { deviceId: other, events } });
    expect(res.json().accepted).toHaveLength(2);
    const { rows } = await pool.query("SELECT entry_id, deck, difficulty FROM attempt_events WHERE device_id = $1 ORDER BY entry_id", [other]);
    expect(rows).toEqual([
      { entry_id: "dog-n", deck: "general", difficulty: "hard" },
      { entry_id: "tech:voltage-n", deck: "tech", difficulty: "hard" },
    ]);
    await pool.query("DELETE FROM attempt_events WHERE device_id = $1", [other]);
  });

  it("serves the review queue from the database", async () => {
    const { items } = (await app.inject("/v1/review?level=A1&limit=3")).json();
    expect(items).toHaveLength(3);
    expect(items[0]).toMatchObject({ level: "A1" });
  });

  it("re-seeding replaces content without touching progress", async () => {
    const again = await seed(pool);
    expect(again).toEqual(seeded);
    const { rows } = await pool.query("SELECT count(*)::int AS n FROM attempt_events");
    expect(rows[0].n).toBe(50);
  });

  it("start-up seeding runs only when the content version changes", async () => {
    expect(await seedIfOutdated(pool)).toBeNull();
    await pool.query("UPDATE content_meta SET value = jsonb_set(value, '{version}', '\"old\"') WHERE key = 'manifest'");
    const seeded = await seedIfOutdated(pool);
    expect(seeded?.lexemes).toBeGreaterThan(9000);
    expect(await seedIfOutdated(pool)).toBeNull();
  });
});
