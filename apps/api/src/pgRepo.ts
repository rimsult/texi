import pg from "pg";
import type { DeviceSummary, Repository, ReviewItem, SyncResult } from "./repo";
import type { AttemptEventInput } from "./schemas";

export function createPool(connectionString: string): pg.Pool {
  const ssl = /sslmode=require|supabase\.co|render\.com/.test(connectionString) ? { rejectUnauthorized: false } : undefined;
  const pool = new pg.Pool({ connectionString, max: 5, ssl });
  // An idle client losing its connection (DB restart, pooler timeout) emits "error" on the
  // pool; unhandled, that would crash the process. The pool replaces the client itself.
  pool.on("error", (err) => console.error("postgres pool error:", err.message));
  return pool;
}

const RU_LEVELS = new Set(["A1", "A2", "B1"]); // Russian definitions (B1 words are A2 distractors)
const RU_QUESTION_LEVELS = new Set(["A1", "A2"]); // short translations: shown after Russian questions

export class PgRepository implements Repository {
  constructor(readonly pool: pg.Pool) {}

  async health() {
    await this.pool.query("SELECT 1");
    return true;
  }

  async saveEvents(deviceId: string, events: AttemptEventInput[]): Promise<SyncResult> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query(
        "INSERT INTO devices (id) VALUES ($1) ON CONFLICT (id) DO UPDATE SET last_seen_at = now()",
        [deviceId],
      );
      const { rows } = await client.query<{ id: string }>(
        `INSERT INTO attempt_events (id, device_id, trainer, entry_id, level, lang, correct, answer_id, answered_at, duration_ms, deck, difficulty)
         SELECT e.id, $1, e.trainer, e.entry_id, e.level, e.lang, e.correct, e.answer_id, e.answered_at, e.duration_ms, e.deck, e.difficulty
         FROM unnest($2::uuid[], $3::text[], $4::text[], $5::text[], $6::text[], $7::bool[], $8::text[], $9::timestamptz[], $10::int[],
                     $11::text[], $12::text[])
           AS e(id, trainer, entry_id, level, lang, correct, answer_id, answered_at, duration_ms, deck, difficulty)
         ON CONFLICT (id) DO NOTHING
         RETURNING id`,
        [
          deviceId,
          events.map((e) => e.id),
          events.map((e) => e.trainerId),
          events.map((e) => e.entryId),
          events.map((e) => e.level),
          events.map((e) => e.lang),
          events.map((e) => e.correct),
          events.map((e) => e.answerId),
          events.map((e) => e.answeredAt),
          events.map((e) => e.durationMs),
          events.map((e) => e.deck),
          events.map((e) => e.difficulty),
        ],
      );
      await client.query("COMMIT");
      const inserted = new Set(rows.map((r) => r.id));
      return {
        accepted: events.filter((e) => inserted.has(e.id)).map((e) => e.id),
        duplicates: events.filter((e) => !inserted.has(e.id)).map((e) => e.id),
      };
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  async deviceSummary(deviceId: string): Promise<DeviceSummary | null> {
    const { rows } = await this.pool.query(
      `SELECT count(*)::int AS events, count(*) FILTER (WHERE correct)::int AS correct,
              count(DISTINCT trainer || ':' || entry_id)::int AS words, max(answered_at) AS last
       FROM attempt_events WHERE device_id = $1`,
      [deviceId],
    );
    const r = rows[0];
    if (!r || r.events === 0) return null;
    return { events: r.events, correct: r.correct, words: r.words, lastAnsweredAt: new Date(r.last).toISOString() };
  }

  async manifest() {
    const { rows } = await this.pool.query("SELECT value FROM content_meta WHERE key = 'manifest'");
    return rows[0]?.value ?? null;
  }

  /** Rebuild a client pack from the database (same shape as the static file). */
  async pack(level: string, deck = "general") {
    const { rows: questions } = await this.pool.query(
      `SELECT q.trainer, q.lexeme_id AS "entryId", q.lang, q.distractors, q.hard_distractors AS hard,
              q.gap_span AS span, q.gap_forms AS forms
       FROM questions q JOIN lexemes l ON l.id = q.lexeme_id
       WHERE q.status = 'ok' AND l.level = $1 AND l.deck = $2 ORDER BY q.id`,
      [level, deck],
    );
    if (!questions.length) return null;
    const { rows: entries } = await this.pool.query(
      // Only the best definition per language ships (the one the client shows).
      `SELECT l.id, l.lemma, l.pos, l.level, l.semantic_group AS "group", l.hard_group AS "hardGroup", l.domain, l.example,
              CASE WHEN $4 THEN l.translation END AS translation, CASE WHEN $4 THEN l.example_ru END AS "exampleRu",
              l.synonyms,
              coalesce((SELECT json_agg(json_build_object('text', b.text, 'lang', b.lang, 'source', b.source, 'quality', b.quality)
                                        ORDER BY b.quality DESC, b.lang)
                        FROM (SELECT DISTINCT ON (d.lang) d.* FROM definitions d
                              WHERE d.lexeme_id = l.id AND (d.lang = 'en' OR $2)
                              ORDER BY d.lang, d.quality DESC, d.id) b), '[]') AS definitions
       FROM lexemes l
       WHERE l.level = $1 AND l.deck = $3 AND l.id IN (
         -- Every lexeme a shipped question refers to: answers and (hard) distractors.
         SELECT unnest(ARRAY[q.lexeme_id] || q.distractors || q.hard_distractors) FROM questions q WHERE q.status = 'ok')
       ORDER BY l.lemma`,
      [level, RU_LEVELS.has(level), deck, RU_QUESTION_LEVELS.has(level)],
    );
    return {
      schemaVersion: 2,
      deck,
      level,
      entries: entries.map(({ example, exampleRu, hardGroup, domain, translation, synonyms, ...e }) => ({
        ...e,
        ...(hardGroup ? { hardGroup } : {}),
        ...(domain ? { domain } : {}),
        ...(example ? { example } : {}),
        ...(example && exampleRu ? { exampleRu } : {}),
        ...(translation ? { translation } : {}),
        ...(synonyms?.length ? { synonyms } : {}),
      })),
      questions: questions.map(({ hard, span, forms, ...q }) => ({
        ...q,
        ...(hard.length ? { hard } : {}),
        ...(span ? { span, forms } : {}),
      })),
    };
  }

  async reviewQueue(level: string | undefined, limit: number): Promise<ReviewItem[]> {
    const { rows } = await this.pool.query(
      `SELECT q.id, q.trainer, q.lexeme_id AS "entryId", l.lemma, l.level, l.deck, q.lang, q.reasons
       FROM questions q JOIN lexemes l ON l.id = q.lexeme_id
       WHERE q.status = 'needs_review' AND ($1::text IS NULL OR l.level = $1)
       ORDER BY l.deck, l.level, l.lemma, q.id LIMIT $2`,
      [level ?? null, limit],
    );
    return rows;
  }

  async close() {
    await this.pool.end();
  }
}
