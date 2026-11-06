import { randomUUID } from "node:crypto";

export const DEVICE = "6f1d2c3b-4a5e-4f60-9a7b-8c9d0e1f2a3b";

export function ev(overrides: Record<string, unknown> = {}) {
  return {
    id: randomUUID(),
    trainerId: "word-to-definition",
    entryId: "dog-n",
    level: "A1",
    lang: "ru",
    correct: true,
    answerId: "dog-n",
    answeredAt: new Date("2026-11-01T10:00:00Z").toISOString(),
    durationMs: 1800,
    ...overrides,
  };
}
