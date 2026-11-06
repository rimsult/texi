import { createContext, type ReactNode, useContext } from "react";
import { STRINGS, type Strings, type UiLang } from "./strings";

export * from "./strings";

const I18nContext = createContext<{ lang: UiLang; t: Strings }>({ lang: "ru", t: STRINGS.ru });

export function I18nProvider({ lang, children }: { lang: UiLang; children: ReactNode }) {
  return <I18nContext.Provider value={{ lang, t: STRINGS[lang] }}>{children}</I18nContext.Provider>;
}

/** Current interface strings (Russian by default). */
export const useT = (): Strings => useContext(I18nContext).t;
export const useUiLang = (): UiLang => useContext(I18nContext).lang;
