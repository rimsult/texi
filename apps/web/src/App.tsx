import { type ContentManifest, deckOfEntry, isLangAllowed, type Level, MASTERED_BOX, type SessionSummary } from "@lexi/core";
import { useCallback, useEffect, useState } from "react";
import { I18nProvider, STRINGS, UI_LANGS, type UiLang } from "./i18n";
import type { Services } from "./services";
import type { Settings } from "./services/store";
import { HomeScreen, type LevelProgress } from "./ui/HomeScreen";
import { useOnline, useSyncStatus } from "./ui/hooks";
import { ResultsScreen } from "./ui/ResultsScreen";
import { type SessionConfig, SessionScreen } from "./ui/SessionScreen";
import { StatusPill } from "./ui/StatusPill";
import logo from "./assets/logo.png";

type Screen =
  | { name: "home" }
  | { name: "session"; config: SessionConfig; run: number }
  | { name: "results"; config: SessionConfig; summary: SessionSummary };

interface Props {
  services: Services;
  offlineReady?: boolean;
}

export function App({ services, offlineReady = false }: Props) {
  const [manifest, setManifest] = useState<ContentManifest | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [progress, setProgress] = useState<Partial<Record<Level, LevelProgress>>>({});
  const [error, setError] = useState<string | null>(null);
  const [screen, setScreen] = useState<Screen>({ name: "home" });
  const online = useOnline();
  const sync = useSyncStatus(services.sync);

  useEffect(() => {
    Promise.all([services.content.manifest(), services.store.settings()])
      .then(([m, s]) => {
        setManifest(m);
        setSettings(s);
      })
      .catch((e: Error) => setError(e.message));
  }, [services]);

  useEffect(() => services.sync.start(), [services]);

  const refreshProgress = useCallback(async (trainerId: string, deck: Settings["deck"]) => {
    const map = await services.store.progressFor(trainerId);
    const out: Partial<Record<Level, LevelProgress>> = {};
    for (const p of map.values()) {
      if (deckOfEntry(p.entryId) !== deck) continue;
      const lp = (out[p.level] ??= { seen: 0, mastered: 0 });
      lp.seen++;
      if (p.box >= MASTERED_BOX) lp.mastered++;
    }
    setProgress(out);
  }, [services]);

  useEffect(() => {
    if (settings && screen.name === "home") void refreshProgress(settings.trainerId, settings.deck);
  }, [settings?.trainerId, settings?.deck, screen.name, refreshProgress]); // eslint-disable-line react-hooks/exhaustive-deps

  const changeSettings = (s: Settings) => {
    setSettings(s);
    void services.store.saveSettings(s);
  };

  const uiLang: UiLang = settings?.uiLang ?? "ru";
  const t = STRINGS[uiLang];
  useEffect(() => {
    document.documentElement.lang = uiLang;
  }, [uiLang]);
  const setUiLang = (l: UiLang) => settings && changeSettings({ ...settings, uiLang: l });

  const start = (entryIds?: string[]) => {
    if (!settings) return;
    const lang = isLangAllowed(settings.level, settings.lang) ? settings.lang : "en";
    const fieldIds = Object.keys(manifest?.fields ?? {});
    const fields = settings.deck === "tech" ? settings.fields.filter((f) => fieldIds.includes(f)) : [];
    const config: SessionConfig = {
      trainerId: settings.trainerId,
      level: settings.level,
      lang,
      size: settings.sessionSize,
      deck: settings.deck,
      // Trainers with a single difficulty (gap-fill) always run in normal mode.
      difficulty: services.registry.get(settings.trainerId)?.supportsHard === false ? "normal" : settings.difficulty,
      ...(fields.length ? { fields } : {}),
      ...(entryIds ? { entryIds } : {}),
    };
    setScreen({ name: "session", config, run: Date.now() });
  };

  const finish = useCallback(
    (summary: SessionSummary) => setScreen((s) => (s.name === "session" ? { name: "results", config: s.config, summary } : s)),
    [],
  );
  const goHome = useCallback(() => setScreen({ name: "home" }), []);

  return (
    <I18nProvider lang={uiLang}>
    <div className="app">
      <header className="topbar">
        <button type="button" className="brand" onClick={goHome} aria-label={t.brandHome}>
          <img className="brand__logo" src={logo} alt="" width={36} height={36} />
          <span className="brand__name">texi</span>
        </button>
        <div className="topbar__end">
          <StatusPill online={online} sync={sync} offlineReady={offlineReady} persistent={services.store.persistent} />
          {settings && (
            <div className="langswitch" role="group" aria-label={t.switchLang}>
              {UI_LANGS.map((l) => (
                <button key={l} type="button" lang={l} aria-pressed={uiLang === l} onClick={() => setUiLang(l)}>
                  {l.toUpperCase()}
                </button>
              ))}
            </div>
          )}
        </div>
      </header>
      {error && <main className="center"><p role="alert">{error}</p></main>}
      {!error && (!manifest || !settings) && (
        <main className="center" aria-busy="true"><span className="spinner" aria-hidden />{t.loading}</main>
      )}
      {manifest && settings && screen.name === "home" && (
        <HomeScreen
          manifest={manifest}
          registry={services.registry}
          settings={settings}
          progress={progress}
          onChange={changeSettings}
          onStart={() => start()}
        />
      )}
      {screen.name === "session" && (
        <SessionScreen
          key={screen.run}
          services={services}
          config={screen.config}
          fields={manifest?.fields ?? {}}
          onExit={goHome}
          onFinish={finish}
        />
      )}
      {screen.name === "results" && (
        <ResultsScreen
          summary={screen.summary}
          config={screen.config}
          onHome={goHome}
          onRetry={() => setScreen({ name: "session", config: { ...screen.config, entryIds: undefined } as SessionConfig, run: Date.now() })}
          onMistakes={() =>
            setScreen({ name: "session", config: { ...screen.config, entryIds: screen.summary.mistakes.map((m) => m.entryId) }, run: Date.now() })
          }
        />
      )}
    </div>
    </I18nProvider>
  );
}
