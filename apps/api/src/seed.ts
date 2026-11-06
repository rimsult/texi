import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type pg from "pg";
import { createPool } from "./pgRepo";

interface Def { text: string; lang: string; source: string; quality: number }
interface Entry {
  id: string; lemma: string; pos: string; level: string; group: string | null; hardGroup?: string; domain?: string;
  deck?: string; definitions: Def[]; example?: string; exampleRu?: string; translation?: string; synonyms?: string[];
}
interface PackQ {
  trainer: string; entryId: string; lang: string; distractors: string[]; hard?: string[];
  span?: number[]; forms?: string[];
}
interface Manifest { version: string; decks: { id: string; levels: { file: string }[] }[] }
interface ReviewQ extends PackQ { id: string; status: string; reasons: string[] }

const root = fileURLToPath(new URL("../../../", import.meta.url));
export const DEFAULT_PACKS = join(root, "apps/web/public/packs");
export const DEFAULT_OUT = join(root, "data-pipeline/out");

const read = <T>(p: string): T => JSON.parse(readFileSync(p, "utf8")) as T;

/** Replace all content tables with the latest pipeline output in one transaction. */
export async function seed(pool: pg.Pool, packsDir = DEFAULT_PACKS, outDir = DEFAULT_OUT) {
  const lexicon = read<Entry[]>(join(outDir, "lexicon.json"));
  const review = read<ReviewQ[]>(join(outDir, "needs_review.json"));
  const manifest = read<Manifest>(join(packsDir, "manifest.json"));
  const files = manifest.decks.flatMap((d) => d.levels.map((l) => l.file));
  const ok = files.flatMap((f) => read<{ questions: PackQ[] }>(join(packsDir, f)).questions);
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query("TRUNCATE lexemes, definitions, questions RESTART IDENTITY CASCADE");
    await client.query(
      `INSERT INTO lexemes (id, lemma, pos, level, semantic_group, example, deck, domain, hard_group, translation, example_ru, synonyms)
       SELECT x.id, x.lemma, x.pos, x.level, x.grp, x.example, x.deck, x.domain, x.hard_group, x.translation, x.example_ru,
              ARRAY(SELECT jsonb_array_elements_text(x.synonyms))
       FROM unnest($1::text[], $2::text[], $3::text[], $4::text[], $5::text[], $6::text[], $7::text[], $8::text[], $9::text[],
                   $10::text[], $11::text[], $12::jsonb[])
         AS x(id, lemma, pos, level, grp, example, deck, domain, hard_group, translation, example_ru, synonyms)`,
      [lexicon.map((e) => e.id), lexicon.map((e) => e.lemma), lexicon.map((e) => e.pos), lexicon.map((e) => e.level),
        lexicon.map((e) => e.group), lexicon.map((e) => e.example ?? null), lexicon.map((e) => e.deck ?? "general"),
        lexicon.map((e) => e.domain ?? null), lexicon.map((e) => e.hardGroup ?? null), lexicon.map((e) => e.translation ?? null),
        lexicon.map((e) => e.exampleRu ?? null), lexicon.map((e) => JSON.stringify(e.synonyms ?? []))],
    );
    const defs = lexicon.flatMap((e) => e.definitions.map((d) => ({ ...d, id: e.id })));
    await client.query(
      `INSERT INTO definitions (lexeme_id, text, lang, source, quality)
       SELECT * FROM unnest($1::text[], $2::text[], $3::text[], $4::text[], $5::real[])`,
      [defs.map((d) => d.id), defs.map((d) => d.text), defs.map((d) => d.lang), defs.map((d) => d.source), defs.map((d) => d.quality)],
    );
    const questions = [
      ...ok.map((q) => ({ ...q, id: `${q.entryId}:${q.trainer}:${q.lang}`, status: "ok", reasons: [] as string[] })),
      ...review,
    ];
    // text[][] parameters must be rectangular, so distractors/reasons travel as JSON.
    await client.query(
      `INSERT INTO questions (id, trainer, lexeme_id, lang, distractors, hard_distractors, status, reasons, gap_span, gap_forms)
       SELECT q.id, q.trainer, q.entry_id, q.lang,
              ARRAY(SELECT jsonb_array_elements_text(q.distractors)),
              ARRAY(SELECT jsonb_array_elements_text(q.hard)), q.status,
              ARRAY(SELECT jsonb_array_elements_text(q.reasons)),
              CASE WHEN q.span IS NOT NULL THEN ARRAY(SELECT jsonb_array_elements_text(q.span)::int) END,
              CASE WHEN q.forms IS NOT NULL THEN ARRAY(SELECT jsonb_array_elements_text(q.forms)) END
       FROM unnest($1::text[], $2::text[], $3::text[], $4::text[], $5::jsonb[], $6::jsonb[], $7::text[], $8::jsonb[],
                   $9::jsonb[], $10::jsonb[])
         AS q(id, trainer, entry_id, lang, distractors, hard, status, reasons, span, forms)`,
      [questions.map((q) => q.id), questions.map((q) => q.trainer), questions.map((q) => q.entryId), questions.map((q) => q.lang),
        questions.map((q) => JSON.stringify(q.distractors)), questions.map((q) => JSON.stringify(q.hard ?? [])),
        questions.map((q) => q.status), questions.map((q) => JSON.stringify(q.reasons)),
        questions.map((q) => (q.span ? JSON.stringify(q.span) : null)),
        questions.map((q) => (q.forms ? JSON.stringify(q.forms) : null))],
    );
    await client.query(
      "INSERT INTO content_meta (key, value) VALUES ('manifest', $1) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
      [JSON.stringify(manifest)],
    );
    await client.query("COMMIT");
    return { lexemes: lexicon.length, definitions: defs.length, questions: questions.length, needsReview: review.length };
  } catch (e) {
    await client.query("ROLLBACK");
    throw e;
  } finally {
    client.release();
  }
}

/**
 * Seeds only when the database holds no content or an older content version
 * than the packs shipped with this build (used on server start-up).
 */
export async function seedIfOutdated(pool: pg.Pool, packsDir = DEFAULT_PACKS, outDir = DEFAULT_OUT) {
  const { version } = read<Manifest>(join(packsDir, "manifest.json"));
  const { rows } = await pool.query("SELECT value->>'version' AS version FROM content_meta WHERE key = 'manifest'");
  if (rows[0]?.version === version) return null;
  return seed(pool, packsDir, outDir);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is required");
  const pool = createPool(url);
  seed(pool, process.env.PACKS_DIR, process.env.PIPELINE_OUT)
    .then((r) => console.log("Seeded", r))
    .finally(() => pool.end());
}
