import { uuid } from "./random";
import type { AnswerResult, BaseQuestion, TrainerContext, TrainerPlugin } from "./trainer";
import { type Deck, type Difficulty, type Lang, type Level, deckOfEntry } from "./types";

/** Immutable fact appended to the local outbox and synced to the server. */
export interface AttemptEvent {
  id: string;
  trainerId: string;
  entryId: string;
  level: Level;
  lang: Lang;
  deck: Deck;
  difficulty: Difficulty;
  correct: boolean;
  answerId: string;
  answeredAt: string; // ISO-8601
  durationMs: number;
}

export interface SessionSummary<Q extends BaseQuestion = BaseQuestion> {
  total: number;
  correct: number;
  accuracy: number;
  mistakes: Q[];
  durationMs: number;
}

export class TrainingSession<Q extends BaseQuestion = BaseQuestion, A = string> {
  readonly questions: Q[];
  private cursor = 0;
  private answers: { question: Q; result: AnswerResult; answer: A }[] = [];
  private shownAt: number;
  private startedAt: number;
  readonly deck: Deck | undefined;
  readonly difficulty: Difficulty;

  constructor(
    readonly plugin: TrainerPlugin<Q, A>,
    ctx: TrainerContext,
    entryIds: string[],
    now: number = Date.now(),
  ) {
    this.questions = entryIds.map((id) => plugin.build(id, ctx)).filter((q): q is Q => q !== null);
    this.deck = ctx.deck;
    this.difficulty = ctx.difficulty ?? "normal";
    this.shownAt = this.startedAt = now;
  }

  get index(): number {
    return this.cursor;
  }

  get total(): number {
    return this.questions.length;
  }

  get current(): Q | undefined {
    return this.questions[this.cursor];
  }

  get answeredCurrent(): boolean {
    return this.answers.length > this.cursor;
  }

  get finished(): boolean {
    return this.cursor >= this.questions.length;
  }

  answer(answer: A, now: number = Date.now()): { result: AnswerResult; event: AttemptEvent } {
    const q = this.current;
    if (!q) throw new Error("Session is finished");
    if (this.answeredCurrent) throw new Error("Question already answered");
    const result = this.plugin.check(q, answer);
    this.answers.push({ question: q, result, answer });
    const event: AttemptEvent = {
      id: uuid(),
      trainerId: q.trainerId,
      entryId: q.entryId,
      level: q.level,
      lang: q.lang,
      deck: this.deck ?? deckOfEntry(q.entryId),
      difficulty: q.difficulty ?? this.difficulty,
      correct: result.correct,
      answerId: String(answer),
      answeredAt: new Date(now).toISOString(),
      durationMs: Math.max(0, now - this.shownAt),
    };
    return { result, event };
  }

  next(now: number = Date.now()): Q | undefined {
    if (!this.answeredCurrent) throw new Error("Answer the current question first");
    this.cursor++;
    this.shownAt = now;
    return this.current;
  }

  summary(now: number = Date.now()): SessionSummary<Q> {
    const correct = this.answers.filter((a) => a.result.correct).length;
    return {
      total: this.answers.length,
      correct,
      accuracy: this.answers.length ? correct / this.answers.length : 0,
      mistakes: this.answers.filter((a) => !a.result.correct).map((a) => a.question),
      durationMs: now - this.startedAt,
    };
  }
}
