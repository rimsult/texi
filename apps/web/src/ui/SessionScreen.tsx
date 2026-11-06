import {
  applyAnswer,
  type BaseQuestion,
  createRng,
  type Deck,
  type Difficulty,
  type ItemProgress,
  type Level,
  planSession,
  type SessionSummary,
  TrainingSession,
} from "@lexi/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { useT } from "../i18n";
import type { Services } from "../services";
import { CloseIcon } from "./icons";
import { RENDERERS } from "./renderers";

export interface SessionConfig {
  trainerId: string;
  level: Level;
  lang: "ru" | "en";
  size: number;
  deck: Deck;
  difficulty: Difficulty;
  /** Tech deck: only these fields (none = all). */
  fields?: string[];
  /** Explicit items, e.g. "work on mistakes". */
  entryIds?: string[];
}

interface Props {
  services: Services;
  config: SessionConfig;
  /** Technical field id -> label (from the manifest). */
  fields?: Record<string, string>;
  onExit: () => void;
  onFinish: (summary: SessionSummary) => void;
}

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; session: TrainingSession };

export function SessionScreen({ services, config, fields = {}, onExit, onFinish }: Props) {
  const t = useT();
  const tRef = useRef(t);
  tRef.current = t;
  const [state, setState] = useState<State>({ status: "loading" });
  const [chosen, setChosen] = useState<string | null>(null);
  const [correctId, setCorrectId] = useState<string | null>(null);
  const [score, setScore] = useState(0);
  const progressRef = useRef<Map<string, ItemProgress>>(new Map());
  const nextRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const plugin = services.registry.get(config.trainerId);
        const tt = tRef.current;
        if (!plugin || plugin.availability !== "ready") throw new Error(tt.trainerUnavailable);
        const lexicon = await services.content.ensureLevel(config.level, config.deck);
        const rng = createRng(services.seed());
        const ctx = {
          lexicon,
          level: config.level,
          rng,
          preferredLang: config.lang,
          deck: config.deck,
          difficulty: config.difficulty,
          ...(config.fields?.length ? { domains: config.fields } : {}),
        };
        progressRef.current = await services.store.progressFor(config.trainerId);
        const plan =
          config.entryIds ??
          planSession({ items: plugin.items(ctx), progress: progressRef.current, size: config.size, now: services.now(), rng });
        const session = new TrainingSession(plugin, ctx, plan, services.now());
        if (session.total === 0)
          throw new Error(
            config.difficulty === "hard" ? tt.noHardQuestions : config.fields?.length ? tt.noFieldQuestions : tt.noQuestions,
          );
        if (!cancelled) setState({ status: "ready", session });
      } catch (e) {
        if (!cancelled) setState({ status: "error", message: e instanceof Error ? e.message : String(e) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [services, config]);

  const session = state.status === "ready" ? state.session : null;
  const question = session?.current as BaseQuestion | undefined;

  const answer = useCallback(
    (answerId: string) => {
      if (!session || !question || session.answeredCurrent) return;
      const now = services.now();
      const { result, event } = session.answer(answerId, now);
      setChosen(answerId);
      setCorrectId(result.correctAnswerId);
      if (result.correct) setScore((s) => s + 1);
      const item = { trainerId: question.trainerId, entryId: question.entryId, level: question.level };
      const next = applyAnswer(progressRef.current.get(question.entryId), item, result.correct, now);
      progressRef.current.set(question.entryId, next);
      void services.store.recordAttempt(event, next).then(() => services.sync.flush());
      requestAnimationFrame(() => nextRef.current?.focus());
    },
    [session, question, services],
  );

  const next = useCallback(() => {
    if (!session || !session.answeredCurrent) return;
    session.next(services.now());
    setChosen(null);
    setCorrectId(null);
    if (session.finished) onFinish(session.summary(services.now()));
  }, [session, services, onFinish]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!session || e.metaKey || e.ctrlKey || e.altKey) return;
      if (!session.answeredCurrent && /^[1-9]$/.test(e.key)) {
        const q = session.current as { options?: { id: string }[] } | undefined;
        const opt = q?.options?.[Number(e.key) - 1];
        if (opt) answer(opt.id);
      } else if (session.answeredCurrent && e.key === "Enter") {
        e.preventDefault();
        next();
      } else if (e.key === "Escape") {
        onExit();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [session, answer, next, onExit]);

  if (state.status === "loading")
    return (
      <main className="center" aria-busy="true">
        <span className="spinner" aria-hidden />
        {t.loadingWords}
      </main>
    );
  if (state.status === "error")
    return (
      <main className="center">
        <p role="alert">{state.message}</p>
        <button type="button" className="primary" onClick={onExit}>{t.home}</button>
      </main>
    );

  const s = state.session;
  if (!question) return null;
  const Renderer = RENDERERS[question.kind];
  const position = s.index + 1;
  const done = s.index + (chosen !== null ? 1 : 0);
  return (
    <main className="session">
      <div className="session__top">
        <button type="button" className="icon-btn" onClick={onExit} aria-label={t.exitSession} title={t.exitHint}>
          <CloseIcon />
        </button>
        <div
          className="progress"
          role="progressbar"
          aria-label={t.sessionProgress}
          aria-valuemin={0}
          aria-valuemax={s.total}
          aria-valuenow={s.index}
        >
          <span style={{ width: `${(done / s.total) * 100}%` }} />
        </div>
        <span className="session__counter" data-testid="counter">{position} / {s.total}</span>
      </div>
      <div className="session__tags">
        <span className="tag tag--level">{config.level}</span>
        <span className="tag">{t.decks[config.deck].short}</span>
        {config.fields?.map((f) => <span key={f} className="tag tag--field">{t.fields[f] ?? fields[f] ?? f}</span>)}
        {config.difficulty === "hard" && <span className="tag tag--hard">{t.hardMode}</span>}
        <span className="session__score" aria-label={t.correctCount}>
          <span aria-hidden>●</span> {score}
        </span>
      </div>
      {Renderer ? (
        <Renderer
          key={question.id + s.index}
          question={question}
          chosen={chosen}
          correctId={correctId}
          onAnswer={answer}
          fields={fields}
        />
      ) : (
        <p role="alert">{t.unknownKind(question.kind)}</p>
      )}
      <div className="session__actions">
        {chosen !== null ? (
          <button ref={nextRef} type="button" className="primary next" onClick={next}>
            {position === s.total ? t.results : t.next} <kbd>Enter</kbd>
          </button>
        ) : (
          <p className="hint hint--keys">{t.keys} <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> {t.keysHint}</p>
        )}
      </div>
    </main>
  );
}
