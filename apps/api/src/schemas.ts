import { z } from "zod";

const LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"] as const;
export const levelSchema = z.enum(LEVELS);
export const deckSchema = z.enum(["general", "tech"]);

export const attemptEventSchema = z
  .object({
    id: z.uuid(),
    trainerId: z.string().regex(/^[a-z0-9-]{1,64}$/),
    entryId: z.string().min(1).max(128),
    level: levelSchema,
    lang: z.enum(["en", "ru"]),
    correct: z.boolean(),
    answerId: z.string().min(1).max(128),
    answeredAt: z.iso.datetime({ offset: true }),
    durationMs: z.number().int().min(0).max(3_600_000),
    // Older clients do not send these: default to the original behaviour.
    deck: deckSchema.default("general"),
    difficulty: z.enum(["normal", "hard"]).default("normal"),
  })
  .refine((e) => (e.deck === "tech") === e.entryId.startsWith("tech:"), {
    message: "entryId does not belong to the deck",
    path: ["deck"],
  })
  .refine((e) => e.lang === "en" || e.level === "A1" || e.level === "A2", {
    message: "Russian definitions are only allowed for A1–A2",
    path: ["lang"],
  })
  .refine((e) => Date.parse(e.answeredAt) <= Date.now() + 24 * 3600_000, {
    message: "answeredAt is in the future",
    path: ["answeredAt"],
  });

/**
 * The batch envelope. Events are validated one by one (see `parseEvents`) so that a
 * single bad event is rejected on its own instead of blocking the whole outbox.
 */
export const syncBodySchema = z.object({
  deviceId: z.uuid(),
  events: z.array(z.object({ id: z.uuid() }).loose()).min(1).max(500),
});

/** Split a batch into valid events (deduplicated by id) and ids of invalid ones. */
export function parseEvents(raw: readonly unknown[]): { valid: AttemptEventInput[]; rejected: string[] } {
  const valid = new Map<string, AttemptEventInput>();
  const rejected = new Set<string>();
  for (const item of raw) {
    const parsed = attemptEventSchema.safeParse(item);
    if (parsed.success) valid.set(parsed.data.id, parsed.data);
    else rejected.add((item as { id: string }).id);
  }
  for (const id of valid.keys()) rejected.delete(id);
  return { valid: [...valid.values()], rejected: [...rejected] };
}

export type AttemptEventInput = z.infer<typeof attemptEventSchema>;
export type SyncBody = z.infer<typeof syncBodySchema>;
