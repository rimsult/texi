import {
  allowedLangs,
  type ContentManifest,
  DECKS,
  DIFFICULTIES,
  type Lang,
  LEVEL_INFO,
  LEVELS,
  type Level,
  type ManifestLevel,
  sessionLang,
  type TrainerPlugin,
  type TrainerRegistry,
} from "@lexi/core";
import type { ReactNode } from "react";
import { definitionBand, useT } from "../i18n";
import type { Settings } from "../services/store";
import { ArrowIcon, BookIcon, CheckIcon, GapIcon } from "./icons";
import { Segmented } from "./Segmented";

export interface LevelProgress {
  seen: number;
  mastered: number;
}

interface Props {
  manifest: ContentManifest;
  registry: TrainerRegistry;
  settings: Settings;
  progress: Partial<Record<Level, LevelProgress>>;
  onChange: (s: Settings) => void;
  onStart: () => void;
}

/** Words a session can use: those with a question in the session language (and a hard pool in
 * hard mode), limited to the selected technical fields when there are any. */
export function playableWords(
  info: ManifestLevel | undefined,
  trainerId: string,
  hard: boolean,
  lang: Lang,
  fields: string[] = [],
  questionLang?: Lang,
): number {
  if (!info) return 0;
  const key = `${trainerId}:${questionLang ?? sessionLang({ level: info.level, preferredLang: lang })}`;
  if (fields.length && info.fields) {
    return fields.reduce((sum, f) => {
      const c = info.fields?.[f];
      return sum + ((hard ? c?.hard?.[key] : c?.questions?.[key]) ?? 0);
    }, 0);
  }
  // Old manifests have no per-trainer counts for the main trainers; optional ones need them.
  return (hard ? info.hard?.[key] : info.questions?.[key]) ?? (hard || questionLang ? 0 : info.words);
}

const TRAINER_GLYPH: Record<string, ReactNode> = {
  "word-to-definition": "Aa",
  "definition-to-word": <BookIcon />,
  "gap-fill": <GapIcon />,
};

export function HomeScreen({ manifest, registry, settings, progress, onChange, onStart }: Props) {
  const t = useT();
  const set = (patch: Partial<Settings>) => onChange({ ...settings, ...patch });
  const ruAllowed = allowedLangs(settings.level).includes("ru");
  const plugin = registry.get(settings.trainerId);
  // Gap-fill has one difficulty and English sentences; its explanations follow the language setting.
  const hardSupported = plugin?.supportsHard !== false;
  const hard = hardSupported && settings.difficulty === "hard";
  const questionLang = plugin?.questionLang;
  const soon = registry.list().filter((p) => p.availability === "soon");
  const deck = manifest.decks.find((d) => d.id === settings.deck) ?? manifest.decks[0]!;
  const levelInfo = (l: Level) => deck.levels.find((m) => m.level === l);
  const fieldIds = Object.keys(manifest.fields ?? {});
  // Only fields the manifest knows count; nothing selected = every field.
  const selectedFields = settings.deck === "tech" ? settings.fields.filter((f) => fieldIds.includes(f)) : [];
  const fieldLabel = (f: string) => t.fields[f] ?? manifest.fields?.[f] ?? f;
  const available = playableWords(levelInfo(settings.level), settings.trainerId, hard, settings.lang, selectedFields, questionLang);
  const main = registry.ready().filter((p) => p.tier !== "extra");
  const extra = registry.ready().filter((p) => p.tier === "extra");
  const trainerText = (id: string, fallback: { title: string; subtitle: string }) => t.trainers[id] ?? fallback;

  const trainerButton = (p: TrainerPlugin) => {
    const selected = p.id === settings.trainerId;
    const text = trainerText(p.id, p);
    return (
      <button
        key={p.id}
        type="button"
        className={`trainer ${selected ? "is-selected" : ""}`}
        aria-pressed={selected}
        data-trainer={p.id}
        onClick={() => set({ trainerId: p.id })}
      >
        <span className="trainer__icon" aria-hidden>{TRAINER_GLYPH[p.id] ?? p.icon}</span>
        <span className="trainer__body">
          <span className="trainer__title">{text.title}</span>
          <span className="trainer__subtitle">{text.subtitle}</span>
        </span>
        <span className="trainer__check" aria-hidden />
      </button>
    );
  };

  const toggleField = (f: string) => {
    const current = selectedFields.length ? selectedFields : [];
    const next = current.includes(f) ? current.filter((x) => x !== f) : [...current, f];
    // Selecting every field is the same as "all".
    set({ fields: next.length === fieldIds.length ? [] : next });
  };

  return (
    <main className="home">
      <section className="hero" aria-labelledby="hero-title">
        <p className="hero__eyebrow">{t.hero.eyebrow}</p>
        <h1 id="hero-title" className="hero__title">
          {t.hero.titleStart}<span className="grad">{t.hero.titleAccent}</span>
        </h1>
        <p className="hero__lead">{t.hero.lead}</p>
      </section>

      <div className="home__grid">
        <div className="home__main">
          <section className="block" aria-labelledby="trainer-title">
            <h2 id="trainer-title" className="block__title"><span className="step" aria-hidden>1</span>{t.steps.trainer}</h2>
            <div className="trainers">{main.map((p) => trainerButton(p))}</div>
            {extra.length > 0 && (
              <>
                <p className="trainers__label" id="extra-trainers">{t.extraTrainers}</p>
                <div className="trainers trainers--extra" aria-labelledby="extra-trainers">{extra.map((p) => trainerButton(p))}</div>
              </>
            )}
            {soon.length > 0 && (
              <ul className="soon" aria-label={t.soon}>
                {soon.map((p) => {
                  const text = trainerText(p.id, p);
                  return (
                    <li key={p.id} title={text.subtitle}>
                      <span aria-hidden>{p.icon}</span> {text.title} <span className="badge">{t.soonBadge}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="block" aria-labelledby="level-title">
            <div className="block__head">
              <h2 id="level-title" className="block__title"><span className="step" aria-hidden>2</span>{t.steps.words}</h2>
              <Segmented
                label={t.deckLabel}
                value={settings.deck}
                options={DECKS.filter((d) => manifest.decks.some((m) => m.id === d)).map((d) => ({
                  value: d,
                  label: t.decks[d].title,
                  short: t.decks[d].short,
                }))}
                onChange={(d) => set({ deck: d })}
              />
            </div>
            {settings.deck === "tech" && fieldIds.length > 0 ? (
              <div className="fields" role="group" aria-label={t.fieldsLabel}>
                <button
                  type="button"
                  className={`chip ${selectedFields.length === 0 ? "is-on" : ""}`}
                  aria-pressed={selectedFields.length === 0}
                  onClick={() => set({ fields: [] })}
                >
                  {selectedFields.length === 0 && <CheckIcon />}
                  {t.allFields}
                </button>
                {fieldIds.map((f) => {
                  const on = selectedFields.includes(f);
                  return (
                    <button
                      key={f}
                      type="button"
                      className={`chip ${on ? "is-on" : ""}`}
                      aria-pressed={on}
                      onClick={() => toggleField(f)}
                    >
                      {on && <CheckIcon />}
                      {fieldLabel(f)}
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="block__desc">{t.decks.general.description}</p>
            )}
            <div className="levels">
              {LEVELS.map((l) => {
                const info = levelInfo(l);
                const total = info?.words ?? 0;
                const playable = playableWords(info, settings.trainerId, hard, settings.lang, selectedFields, questionLang);
                const p = progress[l];
                const pct = total && p ? Math.min(100, Math.round((p.mastered / total) * 100)) : 0;
                // Started words get a faint bar so a first session is visible at once.
                const seenPct = total && p?.seen ? Math.min(100, Math.max(3, Math.round((p.seen / total) * 100))) : 0;
                const selected = l === settings.level;
                return (
                  <button
                    key={l}
                    type="button"
                    className={`level ${selected ? "is-selected" : ""}`}
                    aria-pressed={selected}
                    disabled={playable === 0}
                    onClick={() => set({ level: l })}
                  >
                    <span className="level__code">{l}</span>
                    <span className="level__title">{LEVEL_INFO[l].title}</span>
                    <span className="level__meta">
                      {t.words(playable)}
                      {p?.mastered ? <span className="level__done" aria-hidden> · ✓ {p.mastered}</span> : null}
                      {p?.seen ? <span className="sr-only">{t.levelStarted(p.seen, p.mastered)}</span> : null}
                    </span>
                    <span className="level__bar" aria-hidden>
                      <span className="level__seen" style={{ width: `${seenPct}%` }} />
                      <span className="level__mastered" style={{ width: `${pct}%` }} />
                    </span>
                  </button>
                );
              })}
            </div>
            <p className="block__note" data-testid="definition-note">
              <b>{settings.level}</b> · {t.definitionNote[definitionBand(settings.level)]}
            </p>
          </section>
        </div>

        <aside className="panel" aria-labelledby="options-title">
          <h2 id="options-title" className="block__title"><span className="step" aria-hidden>3</span>{t.steps.options}</h2>

          <div className="setting">
            <span className="setting__label" id="difficulty-label">{t.difficultyLabel}</span>
            {hardSupported ? (
              <>
                <Segmented
                  label={t.difficultyLabel}
                  value={settings.difficulty}
                  options={DIFFICULTIES.map((d) => ({ value: d, label: t.difficulty[d].title }))}
                  onChange={(d) => set({ difficulty: d })}
                />
                <p className="setting__hint">{t.difficulty[settings.difficulty].description}</p>
              </>
            ) : (
              <p className="setting__hint" data-testid="single-difficulty">{t.singleDifficulty}</p>
            )}
          </div>

          <div className="setting">
            <span className="setting__label">{t.definitionsLabel}</span>
            {ruAllowed ? (
              <Segmented
                label={t.definitionLangLabel}
                value={settings.lang}
                options={[
                  { value: "ru", label: t.langRu },
                  { value: "en", label: t.langEn },
                ]}
                onChange={(lang) => set({ lang })}
              />
            ) : (
              <p className="setting__hint">{t.englishOnly}</p>
            )}
            {ruAllowed && settings.lang === "ru" && <p className="setting__hint">{t.ruHint}</p>}
            {questionLang === "en" && <p className="setting__hint">{t.sentencesHint}</p>}
          </div>

          <div className="setting">
            <span className="setting__label">{t.questionsLabel}</span>
            <Segmented
              label={t.sessionLength}
              value={String(settings.sessionSize)}
              options={[{ value: "10", label: "10" }, { value: "20", label: "20" }]}
              onChange={(n) => set({ sessionSize: Number(n) })}
            />
          </div>

          <div className="panel__footer">
            <p className="summary" data-testid="summary">
              <b>{settings.level}</b> · {t.decks[settings.deck].short}
              {selectedFields.length > 0 && <> ({selectedFields.map(fieldLabel).join(", ")})</>} ·{" "}
              {hardSupported && <>{t.difficulty[settings.difficulty].title.toLowerCase()} · </>}
              {t.words(available)}
            </p>
            <button type="button" className="primary start" onClick={onStart} disabled={available === 0}>
              {t.start} <span className="start__arrow" aria-hidden><ArrowIcon /></span>
            </button>
          </div>
        </aside>
      </div>

      <details className="sources">
        <summary>{t.sources}</summary>
        <ul>
          {manifest.sources.map((s) => (
            <li key={s.name}>
              <a href={s.url} target="_blank" rel="noreferrer">{s.name}</a> — {s.license}
            </li>
          ))}
          <li>{t.fonts}</li>
        </ul>
        <p>{t.version}: {manifest.version}</p>
      </details>
    </main>
  );
}
