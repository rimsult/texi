import type { McqQuestion, SessionSummary } from "@lexi/core";
import { type Strings, useT } from "../i18n";
import { DefinitionText } from "./McqCard";
import type { SessionConfig } from "./SessionScreen";

interface Props {
  summary: SessionSummary;
  config?: SessionConfig;
  onRetry: () => void;
  onMistakes: () => void;
  onHome: () => void;
}

function verdict(acc: number, t: Strings): string {
  const [perfect, great, good, low] = t.verdicts;
  if (acc === 1) return perfect!;
  if (acc >= 0.8) return great!;
  if (acc >= 0.5) return good!;
  return low!;
}

export function ResultsScreen({ summary, config, onRetry, onMistakes, onHome }: Props) {
  const t = useT();
  const pct = Math.round(summary.accuracy * 100);
  const minutes = Math.max(1, Math.round(summary.durationMs / 60000));
  return (
    <main className="results">
      <div className="results__card">
        <div className="results__score" style={{ ["--pct" as string]: pct }}>
          <span data-testid="score">{summary.correct} / {summary.total}</span>
          <small>{pct}%</small>
        </div>
        <h2>{verdict(summary.accuracy, t)}</h2>
        <p className="hint">
          {config && <>{config.level} · {t.decks[config.deck].short}{config.difficulty === "hard" ? ` · ${t.hardModeShort}` : ""} · </>}
          {t.minutes(minutes)}
        </p>
        <p className="hint">{t.mistakesReturn}</p>
      </div>
      {summary.mistakes.length > 0 && (
        <section className="mistakes" aria-labelledby="mistakes-title">
          <h3 id="mistakes-title">{t.mistakes}</h3>
          <ul>
            {(summary.mistakes as McqQuestion[]).map((q) => (
              <li key={q.id}>
                <b lang="en">{q.reveal?.lemma ?? q.entryId}</b>
                {q.reveal && (
                  <> — <span lang={q.reveal.definition.lang}><DefinitionText text={q.reveal.definition.text} fill={q.reveal.lemma} /></span></>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      <div className="results__actions">
        {summary.mistakes.length > 0 && (
          <button type="button" className="primary" onClick={onMistakes}>{t.workOnMistakes}</button>
        )}
        <button type="button" className={summary.mistakes.length ? "secondary" : "primary"} onClick={onRetry}>{t.again}</button>
        <button type="button" className="ghost" onClick={onHome}>{t.home}</button>
      </div>
    </main>
  );
}
