import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../src/App";
import { EN_BY_LEMMA, FIELDS, makeServices, makeStore, RU_BY_LEMMA, TECH_WORDS, TRANSLATION_BY_LEMMA } from "./helpers";

async function startApp(services?: Awaited<ReturnType<typeof makeServices>>) {
  const s = services ?? (await makeServices());
  const user = userEvent.setup();
  render(<App services={s} />);
  await screen.findByRole("button", { name: "Начать тренировку" });
  return { services: s, user };
}

/** Answer the current question; `correct` decides which option is clicked. */
async function answer(user: ReturnType<typeof userEvent.setup>, correct: boolean) {
  const word = screen.getByTestId("prompt").textContent!;
  const expected = RU_BY_LEMMA[word] || EN_BY_LEMMA[word] || TECH_WORDS[word]?.ru;
  const options = within(screen.getByRole("group", { name: "Варианты ответа" })).getAllByRole("button");
  const target = options.find((o) => (o.textContent!.includes(expected!) ? correct : !correct))!;
  await user.click(target);
  await screen.findByTestId("feedback");
  return word;
}

describe("App", () => {
  it("lists ready trainers, roadmap trainers and all CEFR levels", async () => {
    await startApp();
    expect(screen.getByRole("button", { name: /Слово → определение/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Определение → слово/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Определение → слово/ }).querySelector(".trainer__icon svg")).not.toBeNull();
    expect(screen.getByText(/двумя офлайн-переводчиками/)).toBeInTheDocument();
    expect(screen.getByTestId("definition-note")).toHaveTextContent("простыми словами");
    expect(screen.getByRole("button", { name: "Texi — на главную" })).toHaveTextContent("texi");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Слова, которые запомнятся");
    expect(screen.queryByText(/без интернета|никакой рекламы|Работает без сети/)).not.toBeInTheDocument();
    expect(screen.getByText("Уровень сложности")).toBeInTheDocument();
    const soon = screen.getByRole("list", { name: "Скоро" });
    expect(within(soon).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("Аудирование"),
      expect.stringContaining("Грамматика"),
    ]);
    for (const l of ["A1", "A2", "B1", "B2", "C1", "C2"]) expect(screen.getByRole("button", { name: new RegExp(`^${l}`) })).toBeInTheDocument();
  });

  it("offers the optional gap-fill trainer with a single difficulty", async () => {
    const { services, user } = await startApp();
    expect(screen.getByText("Дополнительно")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Вставьте слово/ }));
    expect(screen.getByRole("button", { name: /Вставьте слово/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("single-difficulty")).toHaveTextContent("Один уровень сложности");
    expect(screen.queryByRole("button", { name: "Сложный" })).toBeNull();
    expect(screen.getByText(/Предложения — на английском/)).toBeInTheDocument();
    expect(screen.getByTestId("summary")).toHaveTextContent("A1 · Общая · 5 слов");
    expect(screen.getByRole("button", { name: /^A2/ })).toBeDisabled(); // no gap questions there
    await user.click(screen.getByRole("button", { name: "Начать тренировку" }));
    expect(await screen.findByTestId("prompt")).toHaveTextContent("An example with ___.");
    expect(screen.getByText("Вставьте пропущенное слово")).toBeInTheDocument();
    const options = within(screen.getByRole("group", { name: "Варианты ответа" })).getAllByRole("button");
    expect(options).toHaveLength(3);
    await user.click(options[0]!);
    await screen.findByTestId("feedback");
    expect(screen.getByTestId("prompt").querySelector(".gap--filled")).not.toBeNull();
    expect(screen.getByTestId("prompt")).not.toHaveTextContent("___");
    expect((await services.store.progressFor("gap-fill")).size).toBe(1);
  });

  it("runs a full session, saves progress locally and offers work on mistakes", async () => {
    const { services, user } = await startApp();
    await user.click(screen.getByRole("button", { name: "Начать тренировку" }));
    await screen.findByTestId("prompt");
    expect(screen.getByTestId("counter")).toHaveTextContent("1 / 5");
    const wrongWord = await answer(user, false);
    expect(screen.getByTestId("feedback")).toHaveTextContent("Не совсем.");
    const feedback = screen.getByTestId("feedback");
    const fact = (name: string) => within(feedback).getByText(name).nextElementSibling!;
    expect(fact("Оригинал")).toHaveTextContent(EN_BY_LEMMA[wrongWord]!);
    // Russian mode: options are translated definitions; the word's translation comes after answering.
    expect(fact("Перевод")).toHaveTextContent(TRANSLATION_BY_LEMMA[wrongWord]!);
    expect(fact("Пример")).toHaveTextContent(`An example with ${wrongWord}.`);
    // the wrong choice is explained: whose definition it was
    expect(screen.getByTestId("why")).toHaveTextContent(/^Вы выбрали определение слова \w+ \(.+\)\.$/);
    expect(screen.getAllByTestId("option-explain")).toHaveLength(2); // every wrong option names its word
    await user.click(screen.getByRole("button", { name: /Дальше/ }));
    for (let i = 2; i <= 5; i++) {
      expect(screen.getByTestId("counter")).toHaveTextContent(`${i} / 5`);
      await answer(user, true);
      expect(screen.getByTestId("feedback")).toHaveTextContent("Верно!");
      await user.click(screen.getByRole("button", { name: i === 5 ? /Результаты/ : /Дальше/ }));
    }
    expect(await screen.findByTestId("score")).toHaveTextContent("4 / 5");
    expect(screen.getByRole("heading", { name: "Ошибки" })).toBeInTheDocument();
    expect(screen.getByText(wrongWord)).toBeInTheDocument();

    const progress = await services.store.progressFor("word-to-definition");
    expect(progress.size).toBe(5);
    expect(await services.store.pendingCount()).toBe(5);

    await user.click(screen.getByRole("button", { name: "Работа над ошибками" }));
    await screen.findByTestId("prompt");
    expect(screen.getByTestId("counter")).toHaveTextContent("1 / 1");
    expect(screen.getByTestId("prompt")).toHaveTextContent(wrongWord);
  });

  it("supports keyboard: 1–3 to answer, Enter to continue, Esc to exit", async () => {
    const { user } = await startApp();
    await user.click(screen.getByRole("button", { name: "Начать тренировку" }));
    await screen.findByTestId("prompt");
    await user.keyboard("2");
    await screen.findByTestId("feedback");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.getByTestId("counter")).toHaveTextContent("2 / 5"));
    await user.keyboard("{Escape}");
    await screen.findByRole("button", { name: "Начать тренировку" });
  });

  it("uses English only from B1 and hides the language switch", async () => {
    const { user } = await startApp();
    expect(screen.getByRole("radiogroup", { name: "Язык определений" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^B1/ }));
    expect(screen.queryByRole("radiogroup", { name: "Язык определений" })).not.toBeInTheDocument();
    expect(screen.getByText(/только на английском/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Определение → слово/ }));
    await user.click(screen.getByRole("button", { name: "Начать тренировку" }));
    const prompt = await screen.findByTestId("prompt");
    expect(prompt.textContent).not.toMatch(/[а-яё]/i);
    expect(screen.getByText("Выберите слово по определению")).toBeInTheDocument();
  });

  it("lets A1 learners switch definitions to English", async () => {
    const { user } = await startApp();
    await user.click(screen.getByRole("radio", { name: "English" }));
    await user.click(screen.getByRole("button", { name: "Начать тренировку" }));
    await screen.findByTestId("prompt");
    const options = within(screen.getByRole("group", { name: "Варианты ответа" })).getAllByRole("button");
    expect(options.every((o) => !/[а-яё]/i.test(o.textContent!))).toBe(true);
  });

  it("remembers settings between visits", async () => {
    const store = await makeStore();
    const first = await startApp(await makeServices({ store }));
    await first.user.click(screen.getByRole("button", { name: /^A2/ }));
    await first.user.click(screen.getByRole("radio", { name: "20" }));
    await waitFor(async () => expect((await store.settings()).level).toBe("A2"));
    screen.getByRole("button", { name: /^A2/ }).ownerDocument.body.innerHTML = "";
    await startApp(await makeServices({ store }));
    expect(screen.getByRole("button", { name: /^A2/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("radio", { name: "20" })).toHaveAttribute("aria-checked", "true");
  });

  it("shows progress per level after training", async () => {
    const { user } = await startApp();
    await user.click(screen.getByRole("button", { name: "Начать тренировку" }));
    for (let i = 1; i <= 5; i++) {
      await screen.findByTestId("prompt");
      await answer(user, true);
      await user.click(screen.getByRole("button", { name: /Дальше|Результаты/ }));
    }
    await user.click(await screen.findByRole("button", { name: "На главную" }));
    expect(await screen.findByRole("button", { name: /^A1/ })).toHaveTextContent("5 слов");
  });

  it("shows a clear error when content cannot be loaded", async () => {
    const services = await makeServices({ contentFetch: (async () => { throw new TypeError("offline"); }) as typeof fetch });
    render(<App services={services} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Нет соединения/);
  });

  it("reflects offline state in the status bar when a server is configured", async () => {
    const apiFetch = (async () => new Response(JSON.stringify({ accepted: [], duplicates: [] }))) as typeof fetch;
    await startApp(await makeServices({ apiUrl: "https://api.example", apiFetch }));
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => false });
    window.dispatchEvent(new Event("offline"));
    await waitFor(() => expect(screen.getByTestId("sync-status")).toHaveTextContent("Офлайн"));
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => true });
    window.dispatchEvent(new Event("online"));
  });

  it("without a server (single-file build) progress is local and the network does not matter", async () => {
    await startApp();
    expect(screen.getByTestId("sync-status")).toHaveTextContent("Прогресс на устройстве");
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => false });
    window.dispatchEvent(new Event("offline"));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByTestId("sync-status")).toHaveTextContent("Прогресс на устройстве");
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => true });
    window.dispatchEvent(new Event("online"));
  });

  it("trains the technical deck separately, with fields shown and events tagged", async () => {
    const { services, user } = await startApp();
    await user.click(screen.getByRole("radio", { name: "Техническая лексика" }));
    const fields = screen.getByRole("group", { name: "Области технической лексики" });
    for (const f of Object.values(FIELDS)) expect(within(fields).getByRole("button", { name: f })).toBeInTheDocument();
    expect(within(fields).getByRole("button", { name: "Все области" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /^A1/ })).toHaveTextContent("3 слова");
    expect(screen.getByRole("button", { name: /^B1/ })).toBeDisabled(); // nothing to play there
    await user.click(screen.getByRole("button", { name: "Начать тренировку" }));
    const word = (await screen.findByTestId("prompt")).textContent!;
    expect(Object.keys(TECH_WORDS)).toContain(word);
    expect(screen.getByText(FIELDS[TECH_WORDS[word]!.field as keyof typeof FIELDS])).toBeInTheDocument();
    expect(screen.getByTestId("counter")).toHaveTextContent("1 / 3");
    await answer(user, true);
    await waitFor(async () => expect(await services.store.pendingCount()).toBe(1));
    const [ev] = await services.store.pendingEvents(1);
    expect(ev).toMatchObject({ deck: "tech", difficulty: "normal", entryId: `tech:${word}-n`, correct: true });
    // progress of one deck never leaks into the other
    await user.click(screen.getByRole("button", { name: "Завершить тренировку" }));
    await user.click(await screen.findByRole("radio", { name: "Общая лексика" }));
    expect(screen.getByRole("button", { name: /^A1/ })).toHaveTextContent("5 слов");
  });

  it("hard mode uses same-group options, labels the session and records the difficulty", async () => {
    const { services, user } = await startApp();
    await user.click(screen.getByRole("radio", { name: "Сложный" }));
    expect(screen.getByText(/из той же смысловой группы/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^A2/ })).toBeDisabled(); // no hard pools in the fixture at A2
    expect(screen.getByTestId("summary")).toHaveTextContent("сложный");
    await user.click(screen.getByRole("button", { name: "Начать тренировку" }));
    await screen.findByTestId("prompt");
    expect(screen.getByText("Сложный режим")).toBeInTheDocument();
    const options = within(screen.getByRole("group", { name: "Варианты ответа" })).getAllByRole("button");
    // A1 fixture hard pools contain only A1 words (never the A2 word "joy")
    expect(options.map((o) => o.textContent).join(" ")).not.toContain(RU_BY_LEMMA.joy);
    await answer(user, false);
    await waitFor(async () => expect(await services.store.pendingCount()).toBe(1));
    expect((await services.store.pendingEvents(1))[0]).toMatchObject({ difficulty: "hard", deck: "general", correct: false });
  });

  it("remembers deck and difficulty between visits", async () => {
    const store = await makeStore();
    const first = await startApp(await makeServices({ store }));
    await first.user.click(screen.getByRole("radio", { name: "Техническая лексика" }));
    await first.user.click(screen.getByRole("radio", { name: "Сложный" }));
    await waitFor(async () => expect(await store.settings()).toMatchObject({ deck: "tech", difficulty: "hard" }));
    document.body.innerHTML = "";
    await startApp(await makeServices({ store }));
    expect(screen.getByRole("radio", { name: "Техническая лексика" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Сложный" })).toHaveAttribute("aria-checked", "true");
  });

  it("segmented controls work from the keyboard", async () => {
    const { user } = await startApp();
    screen.getByRole("radio", { name: "Обычный" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "Сложный" })).toHaveAttribute("aria-checked", "true");
  });

  it("lets learners pick technical fields; counts and questions follow the choice", async () => {
    const store = await makeStore();
    const { user } = await startApp(await makeServices({ store }));
    await user.click(screen.getByRole("radio", { name: "Техническая лексика" }));
    const fields = screen.getByRole("group", { name: "Области технической лексики" });
    await user.click(within(fields).getByRole("button", { name: "ИТ" }));
    expect(within(fields).getByRole("button", { name: "ИТ" })).toHaveAttribute("aria-pressed", "true");
    expect(within(fields).getByRole("button", { name: "Все области" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: /^A1/ })).toHaveTextContent("1 слово");
    await user.click(within(fields).getByRole("button", { name: "Химия" }));
    expect(screen.getByRole("button", { name: /^A1/ })).toHaveTextContent("2 слова");
    await waitFor(async () => expect((await store.settings()).fields).toEqual(["it", "chemistry"]));
    expect(screen.getByTestId("summary")).toHaveTextContent("ИТ, Химия");
    await user.click(within(fields).getByRole("button", { name: "Химия" }));
    await user.click(screen.getByRole("button", { name: "Начать тренировку" }));
    expect(await screen.findByTestId("prompt")).toHaveTextContent("algorithm");
    expect(screen.getByTestId("counter")).toHaveTextContent("1 / 1");
    await user.click(screen.getByRole("button", { name: "Завершить тренировку" }));
    await user.click(within(await screen.findByRole("group", { name: "Области технической лексики" })).getByRole("button", { name: "Все области" }));
    expect(screen.getByRole("button", { name: /^A1/ })).toHaveTextContent("3 слова");
  });

  it("switches the interface to English and remembers it", async () => {
    const store = await makeStore();
    const { user } = await startApp(await makeServices({ store }));
    expect(document.documentElement.lang).toBe("ru");
    await user.click(screen.getByRole("button", { name: "EN" }));
    expect(await screen.findByRole("button", { name: "Start training" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Words you will remember");
    expect(screen.getByText("Difficulty level")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "EN" })).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement.lang).toBe("en");
    await waitFor(async () => expect((await store.settings()).uiLang).toBe("en"));
    await user.click(screen.getByRole("button", { name: "Start training" }));
    await screen.findByTestId("prompt");
    expect(screen.getByRole("group", { name: "Answer options" })).toBeInTheDocument();
    await user.keyboard("1");
    expect(await screen.findByTestId("feedback")).toHaveTextContent(/Correct!|Not quite\./);
    document.body.innerHTML = "";
    render(<App services={await makeServices({ store })} />);
    expect(await screen.findByRole("button", { name: "Start training" })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "RU" }));
    expect(await screen.findByRole("button", { name: "Начать тренировку" })).toBeInTheDocument();
  });
});
