import type { Rng } from "./random";
import { shuffle } from "./random";
import type { Level } from "./types";

const MIN = 60_000;
const DAY = 24 * 60 * MIN;

/** Leitner boxes: 0 = new … 5 = long-term. */
export const BOX_INTERVALS_MS = [0, 10 * MIN, 1 * DAY, 3 * DAY, 7 * DAY, 21 * DAY] as const;
export const MAX_BOX = BOX_INTERVALS_MS.length - 1;
export const MASTERED_BOX = 4;

export interface ItemProgress {
  key: string; // `${trainerId}:${entryId}`
  trainerId: string;
  entryId: string;
  level: Level;
  box: number;
  due: number;
  seen: number;
  correct: number;
  wrong: number;
  lastAnsweredAt: number;
}

export const progressKey = (trainerId: string, entryId: string) => `${trainerId}:${entryId}`;

export function applyAnswer(
  prev: ItemProgress | undefined,
  item: { trainerId: string; entryId: string; level: Level },
  correct: boolean,
  now: number,
): ItemProgress {
  const base: ItemProgress = prev ?? {
    key: progressKey(item.trainerId, item.entryId),
    trainerId: item.trainerId,
    entryId: item.entryId,
    level: item.level,
    box: 0,
    due: now,
    seen: 0,
    correct: 0,
    wrong: 0,
    lastAnsweredAt: 0,
  };
  // A new word answered correctly is probably known: skip straight to box 2.
  const box = correct ? Math.min(MAX_BOX, base.box === 0 ? 2 : base.box + 1) : 1;
  return {
    ...base,
    box,
    due: now + BOX_INTERVALS_MS[box]!,
    seen: base.seen + 1,
    correct: base.correct + (correct ? 1 : 0),
    wrong: base.wrong + (correct ? 0 : 1),
    lastAnsweredAt: now,
  };
}

export interface PlanOptions {
  items: string[]; // entry ids available
  progress: Map<string, ItemProgress>; // keyed by entryId for this trainer
  size: number;
  now: number;
  rng: Rng;
  reviewShare?: number;
}

/** Due reviews first (most overdue / weakest first), then new words, then early reviews. */
export function planSession({ items, progress, size, now, rng, reviewShare = 0.6 }: PlanOptions): string[] {
  const due: ItemProgress[] = [];
  const later: ItemProgress[] = [];
  const fresh: string[] = [];
  for (const id of items) {
    const p = progress.get(id);
    if (!p) fresh.push(id);
    else if (p.due <= now) due.push(p);
    else later.push(p);
  }
  due.sort((a, b) => a.box - b.box || a.due - b.due);
  later.sort((a, b) => a.due - b.due);
  const freshShuffled = shuffle(fresh, rng);

  const reviewSlots = Math.min(due.length, Math.max(1, Math.round(size * reviewShare)));
  const picked: string[] = due.slice(0, reviewSlots).map((p) => p.entryId);
  for (const id of freshShuffled) if (picked.length < size) picked.push(id);
  for (const p of due.slice(reviewSlots)) if (picked.length < size) picked.push(p.entryId);
  for (const p of later) if (picked.length < size) picked.push(p.entryId);
  return shuffle(picked, rng);
}

export interface LevelStats {
  total: number;
  seen: number;
  mastered: number;
  due: number;
  accuracy: number | null;
}

export function levelStats(items: string[], progress: Map<string, ItemProgress>, now: number): LevelStats {
  let seen = 0, mastered = 0, due = 0, correct = 0, answers = 0;
  for (const id of items) {
    const p = progress.get(id);
    if (!p) continue;
    seen++;
    if (p.box >= MASTERED_BOX) mastered++;
    if (p.due <= now) due++;
    correct += p.correct;
    answers += p.seen;
  }
  return { total: items.length, seen, mastered, due, accuracy: answers ? correct / answers : null };
}
