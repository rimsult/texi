import type { McqOption, McqQuestion } from "@lexi/core";
import { Fragment, type ReactNode } from "react";
import { type Strings, useT } from "../i18n";
import { CheckIcon, CloseIcon } from "./icons";
import type { RendererProps } from "./renderers";

const BLANK = "___";

/** Learner definitions hide the headword as "___"; after answering the gap shows the word. */
export function DefinitionText({ text, fill }: { text: string; fill?: string }) {
  if (!text.includes(BLANK)) return <>{text}</>;
  const parts = text.split(BLANK);
  return (
    <>
      {parts.map((p, i) => (
        <Fragment key={i}>
          {p}
          {i < parts.length - 1 &&
            (fill ? <b className="gap gap--filled">{fill}</b> : <span className="gap" aria-label="…">{BLANK}</span>)}
        </Fragment>
      ))}
    </>
  );
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Regular inflections of one word: run → runs/running, study → studied, make → making. */
function formsPattern(word: string): string {
  const w = escapeRe(word);
  if (word.length === 1) return w;
  if (/[^aeiou]y$/.test(word)) return `${w.slice(0, -1)}(?:y|ies|ied|ier|iest|ying|ily)`;
  if (/ie$/.test(word)) return `${w.slice(0, -2)}(?:ie|ies|ied|ying)`;
  if (word.length > 3 && /e$/.test(word)) return `${w.slice(0, -1)}(?:e|es|ed|en|er|ers|est|ing|eing|ely)`;
  // A doubled final consonant only before a vowel suffix: stop → stopped, big → bigger.
  const double = /[^aeiou]$/.test(word) ? `(?:${escapeRe(word.slice(-1))}(?=ed|ing|er|est))?` : "";
  return `${w}${double}(?:s|es|ed|en|er|ers|est|ing|ly|n|ne)?`;
}

/**
 * The example with the word highlighted. Multi-word items inflect their last word
 * (full stop → full stops). Irregular forms (children, forgotten) fall back to prefix
 * matching for longer words; short words never do, or "be" would mark "because".
 */
export function Highlighted({ text, word }: { text: string; word: string }) {
  const space = word.lastIndexOf(" ");
  const strict = `\\b(${escapeRe(word.slice(0, space + 1))}${formsPattern(word.slice(space + 1))})\\b`;
  const source = new RegExp(strict, "i").test(text) || word.length < 4 ? strict : `\\b(${escapeRe(word)}[a-z]*)\\b`;
  const re = new RegExp(source, "gi");
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    out.push(text.slice(last, m.index), <mark key={m.index}>{m[0]}</mark>);
    last = m.index! + m[0].length;
  }
  out.push(text.slice(last));
  return <>{out}</>;
}

/** Why a wrong option is wrong: whose definition it is / what the chosen word means. */
function WrongChoice({ option, isWordPrompt, t }: { option: McqOption; isWordPrompt: boolean; t: Strings }) {
  const tr = option.explain.translation ? <span className="muted"> ({option.explain.translation})</span> : null;
  if (isWordPrompt) {
    return (
      <p className="reveal__why" data-testid="why">
        {t.yourChoiceDefinition} <b lang="en">{option.explain.lemma}</b>
        {tr}.
      </p>
    );
  }
  return (
    <p className="reveal__why" data-testid="why">
      {t.yourChoiceWord} <b lang="en">{option.explain.lemma}</b>
      {tr} — {t.means}: <span lang={option.lang === "en" ? undefined : option.lang}>
        <DefinitionText text={option.explain.definition ?? ""} fill={option.explain.lemma} />
      </span>
    </p>
  );
}

/** Gap-fill sentence: "___" before answering, the word in place afterwards. */
function SentenceText({ question, answered }: { question: McqQuestion; answered: boolean }) {
  const gap = question.prompt.gap;
  if (!answered || !gap) return <DefinitionText text={question.prompt.text} />;
  return (
    <>
      {gap.before}
      <b className="gap gap--filled">{gap.answer}</b>
      {gap.after}
    </>
  );
}

/** A wrong gap-fill option: its dictionary form (if the gap shows another form) and meaning. */
function GapExplain({ option }: { option: McqOption }) {
  const { lemma, definition, translation } = option.explain;
  const head = lemma.toLowerCase() !== option.text.toLowerCase() ? lemma : null;
  return (
    <>
      {head && <b>{head}</b>}
      {head && (translation || definition) ? " — " : ""}
      {translation ? `${translation}${definition ? "; " : ""}` : ""}
      {definition}
    </>
  );
}

export function McqCard({ question, chosen, correctId, onAnswer, fields = {} }: RendererProps<McqQuestion>) {
  const t = useT();
  const answered = chosen !== null;
  const ok = chosen === correctId;
  const style = question.prompt.style;
  const isDefinitionPrompt = style === "definition";
  const isSentence = style === "sentence";
  const isWordPrompt = style === "word";
  const r = question.reveal;
  const domain = r.domain ? (t.fields[r.domain] ?? fields[r.domain] ?? r.domain) : null;
  const instruction = t.trainers[question.trainerId]?.instruction || question.instruction;
  const chosenOption = answered && !ok ? question.options.find((o) => o.id === chosen) : undefined;
  const definitionLang = r.definition.lang;
  return (
    <div className="card">
      <div className="card__head">
        <p className="card__instruction">{instruction}</p>
        {domain && <span className="tag tag--field">{domain}</span>}
      </div>
      <div className={`prompt prompt--${isWordPrompt ? "word" : isSentence ? "sentence" : "definition"}`} lang={question.prompt.lang}>
        <span data-testid="prompt">
          {isSentence ? (
            <SentenceText question={question} answered={answered} />
          ) : isDefinitionPrompt ? (
            <DefinitionText text={question.prompt.text} fill={answered ? r.lemma : undefined} />
          ) : (
            question.prompt.text
          )}
        </span>
        <span className="prompt__pos">{t.pos[question.prompt.pos] ?? question.prompt.pos}</span>
      </div>
      <div className="options" role="group" aria-label={t.options}>
        {question.options.map((o, i) => {
          let state = "idle";
          if (answered && o.id === correctId) state = "correct";
          else if (answered && o.id === chosen) state = "wrong";
          else if (answered) state = "muted";
          // After answering every wrong option tells what it really is.
          const explain =
            answered && o.id !== correctId
              ? isWordPrompt
                ? <>{o.explain.lemma}{o.explain.translation ? ` · ${o.explain.translation}` : ""}</>
                : isSentence
                  ? <GapExplain option={o} />
                  : o.explain.definition
                  ? <DefinitionText text={o.explain.definition} fill={o.explain.lemma} />
                  : null
              : null;
          return (
            <button
              key={o.id}
              type="button"
              className={`option option--${state}`}
              data-state={state}
              lang={o.lang}
              disabled={answered}
              aria-keyshortcuts={String(i + 1)}
              onClick={() => onAnswer(o.id)}
              style={{ ["--i" as string]: i }}
            >
              <kbd className="option__key">{i + 1}</kbd>
              <span className="option__body">
                <span className="option__text">
                  {isWordPrompt ? <DefinitionText text={o.text} /> : o.text}
                </span>
                {explain && (
                  <span className="option__explain" data-testid="option-explain" lang={isWordPrompt ? "en" : isSentence || o.explain.translation ? undefined : "en"}>
                    {explain}
                  </span>
                )}
              </span>
              {state === "correct" && <span className="option__mark" role="img" aria-label={t.markCorrect}><CheckIcon /></span>}
              {state === "wrong" && <span className="option__mark" role="img" aria-label={t.markWrong}><CloseIcon /></span>}
            </button>
          );
        })}
      </div>
      {answered && (
        <div className={`reveal ${ok ? "reveal--ok" : "reveal--bad"}`} aria-live="polite" data-testid="feedback">
          <p className="reveal__verdict">
            <strong>{ok ? t.verdictOk : t.verdictBad}</strong>{" "}
            {!ok && <span className="reveal__answer-label">{t.answerIs} </span>}
            <span lang="en" className="reveal__lemma">{r.lemma}</span>{" "}
            <span className="reveal__pos">{t.pos[r.pos] ?? r.pos}</span>{" "}
            — <span lang={definitionLang}><DefinitionText text={r.definition.text} fill={r.lemma} /></span>
          </p>
          {chosenOption && <WrongChoice option={chosenOption} isWordPrompt={isWordPrompt} t={t} />}
          <dl className="reveal__facts">
            {r.translation && (
              <div className="reveal__translation">
                <dt>{t.translation}</dt>
                <dd lang="ru">{r.translation}</dd>
              </div>
            )}
            {isSentence && r.exampleRu && (
              <div className="reveal__example">
                <dt>{t.sentenceTranslation}</dt>
                <dd lang="ru">{r.exampleRu}</dd>
              </div>
            )}
            {r.example && !isSentence && (
              <div className="reveal__example">
                <dt>{t.example}</dt>
                <dd>
                  <span lang="en">«<Highlighted text={r.example} word={r.lemma} />»</span>
                  {r.exampleRu && <span className="reveal__example-ru" lang="ru">{r.exampleRu}</span>}
                </dd>
              </div>
            )}
            {r.synonyms && r.synonyms.length > 0 && (
              <div className="reveal__synonyms">
                <dt>{t.synonyms}</dt>
                <dd lang="en">{r.synonyms.join(", ")}</dd>
              </div>
            )}
            {r.english && (
              <div className="reveal__extra">
                <dt>{t.original}</dt>
                <dd lang="en"><DefinitionText text={r.english.text} fill={r.lemma} /></dd>
              </div>
            )}
          </dl>
          {r.definition.source === "generated" && <div className="reveal__note">{t.generatedNote}</div>}
        </div>
      )}
    </div>
  );
}
