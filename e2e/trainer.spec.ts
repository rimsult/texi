import { expect, test } from "@playwright/test";
import { API, chooseLevel, CYRILLIC, deviceId, openHome, options, pending, playSession } from "./helpers";

test("A1: word → Russian definition, full session is saved and synced", async ({ page, request }) => {
  await openHome(page);
  await expect(page.getByRole("button", { name: /Слово → определение/ })).toHaveAttribute("aria-pressed", "true");
  await chooseLevel(page, "A1");
  await page.getByRole("radio", { name: "Русские" }).click();
  await page.getByRole("radio", { name: "10" }).click();
  await page.getByRole("button", { name: "Начать тренировку" }).click();

  const seen = new Set<string>();
  const texts: string[] = [];
  const feedback: string[] = [];
  await playSession(page, 10, async () => {
    const word = (await page.getByTestId("prompt").textContent())!;
    expect(word).not.toMatch(CYRILLIC);
    seen.add(word);
    for (const text of await options(page).locator(".option__text").allTextContents()) {
      expect(text).toMatch(CYRILLIC);
      texts.push(text);
    }
  }, 0, (t) => feedback.push(t));
  expect(seen.size).toBe(10); // no word repeats inside a session
  // Russian options are whole translated definitions, not one-word translations.
  expect(texts.filter((t) => t.trim().split(/\s+/).length >= 3).length / texts.length).toBeGreaterThan(0.7);
  // …and the short translation of the word comes after answering.
  expect(feedback.filter((t) => t.includes("Перевод")).length).toBeGreaterThanOrEqual(7);
  // A1 words are explained in basic English, with the example translated too.
  expect(feedback.filter((t) => t.includes("Пример")).length).toBeGreaterThanOrEqual(5);

  // Answers reach the server and the local queue drains.
  await expect(page.getByTestId("sync-status")).toHaveText("Синхронизировано");
  expect(await pending(page)).toBe(0);
  const id = await deviceId(page);
  const summary = await (await request.get(`${API}/v1/devices/${id}/summary`)).json();
  expect(summary).toMatchObject({ events: 10, words: 10 });

  // Progress is visible on the level card after returning home.
  await page.getByRole("button", { name: /На главную|Домой|К выбору/ }).first().click();
  await expect(page.getByRole("button", { name: /^A1/ })).toContainText("начато 10");
});

test("B2: definition → word is English-only and settings survive a reload", async ({ page }) => {
  await openHome(page);
  await page.getByRole("button", { name: /Определение → слово/ }).click();
  await chooseLevel(page, "B2");
  await expect(page.getByRole("radiogroup", { name: "Язык определений" })).toHaveCount(0);
  await expect(page.getByText("С уровня B1 определения только на английском.")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("button", { name: /^B2/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: /Определение → слово/ })).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("radio", { name: "10" }).click();
  await page.getByRole("button", { name: "Начать тренировку" }).click();
  await playSession(page, 10, async () => {
    const definition = (await page.getByTestId("prompt").textContent())!;
    expect(definition).not.toMatch(CYRILLIC);
    expect(definition.split(" ").length).toBeGreaterThan(1);
    const words = await options(page).locator(".option__text").allTextContents();
    expect(new Set(words).size).toBe(3);
    for (const w of words) {
      expect(w).not.toMatch(CYRILLIC);
      // The answer word must never be spelled out inside the definition.
      expect(definition.toLowerCase().split(/\W+/)).not.toContain(w.toLowerCase());
    }
  }, 2);
});

test("keyboard-only session and work on mistakes", async ({ page }) => {
  await openHome(page);
  await chooseLevel(page, "B1");
  await page.getByRole("radio", { name: "10" }).click();
  await page.getByRole("button", { name: "Начать тренировку" }).focus();
  await page.keyboard.press("Enter");
  let wrong = 0;
  for (let i = 1; i <= 10; i++) {
    await expect(page.getByTestId("counter")).toHaveText(`${i} / 10`);
    await page.keyboard.press(String((i % 3) + 1));
    const text = (await page.getByTestId("feedback").textContent())!;
    if (!text.includes("Верно!")) wrong++;
    await page.keyboard.press("Enter");
  }
  await expect(page.getByTestId("score")).toHaveText(`${10 - wrong} / 10`);
  if (wrong > 0) {
    await page.getByRole("button", { name: "Работа над ошибками" }).click();
    await expect(page.getByTestId("counter")).toHaveText(`1 / ${wrong}`);
  }
});

test("technical vocabulary in hard mode: distractors are the word's closest neighbours", async ({ page, request }) => {
  await openHome(page);
  await page.getByRole("radio", { name: "Техническая лексика" }).click();
  await expect(page.getByRole("group", { name: "Области технической лексики" })).toContainText("Электротехника");
  await page.getByRole("button", { name: /Определение → слово/ }).click();
  await chooseLevel(page, "C1");
  await page.getByRole("radio", { name: "Сложный" }).click();
  await page.getByRole("radio", { name: "10" }).click();
  await expect(page.getByTestId("summary")).toContainText("C1 · Техническая · сложный");
  await page.getByRole("button", { name: "Начать тренировку" }).click();
  await expect(page.getByText("Сложный режим")).toBeVisible();

  type Q = { trainer: string; entryId: string; lang: string; hard?: string[] };
  type E = { id: string; lemma: string };
  // Distractors may come from the neighbouring levels, as in the normal mode.
  const packs: { level: string; entries: E[]; questions: Q[] }[] = await page.evaluate(() =>
    Promise.all(["B2", "C1", "C2"].map(async (l) => (await fetch(`/packs/tech-${l}.json`)).json())),
  );
  const pack = { entries: packs.flatMap((p) => p.entries), questions: packs.find((p) => p.level === "C1")!.questions };
  const ids = (lemma: string) => pack.entries.filter((e) => e.lemma === lemma).map((e) => e.id);
  const hardOf = (id: string) =>
    pack.questions.find((q) => q.trainer === "definition-to-word" && q.lang === "en" && q.entryId === id)?.hard ?? [];

  for (let i = 1; i <= 10; i++) {
    await expect(page.getByTestId("counter")).toHaveText(`${i} / 10`);
    await expect(page.locator(".card .tag--field")).toBeVisible(); // the technical field is shown
    const words = await options(page).locator(".option__text").allTextContents();
    expect(new Set(words).size).toBe(3);
    for (const w of words) expect(ids(w).length).toBeGreaterThan(0); // every option is a technical word
    await options(page).nth(i % 3).click();
    const answer = (await page.locator(".option--correct .option__text").textContent())!;
    const hard = ids(answer).flatMap(hardOf);
    for (const w of words.filter((x) => x !== answer)) expect(ids(w).some((id) => hard.includes(id))).toBe(true);
    await page.getByRole("button", { name: i === 10 ? /Результаты/ : /Дальше/ }).click();
  }
  await expect(page.getByTestId("sync-status")).toHaveText("Синхронизировано");
  const summary = await (await request.get(`${API}/v1/devices/${await deviceId(page)}/summary`)).json();
  expect(summary).toMatchObject({ events: 10, words: 10 });
});

test("API serves content identical to the static packs", async ({ page, request }) => {
  await openHome(page);
  for (const [api, file] of [["A2", "A2.json"], ["B1?deck=tech", "tech-B1.json"]]) {
    const fromApi = await (await request.get(`${API}/v1/content/packs/${api}`)).json();
    const fromStatic = await page.evaluate(async (f) => (await fetch(`/packs/${f}`)).json(), file);
    expect(fromApi).toEqual(fromStatic);
  }
});

test("English interface and one technical field: the choice survives a reload", async ({ page }) => {
  await openHome(page);
  await page.getByRole("group", { name: "Язык интерфейса" }).getByRole("button", { name: "EN" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Words you will remember");
  await page.getByRole("radio", { name: "Technical" }).click();
  const fields = page.getByRole("group", { name: "Technical fields" });
  await fields.getByRole("button", { name: "Electrical" }).click();
  await expect(fields.getByRole("button", { name: "Electrical" })).toHaveAttribute("aria-pressed", "true");
  await expect(fields.getByRole("button", { name: "All fields" })).toHaveAttribute("aria-pressed", "false");
  await chooseLevel(page, "C2");

  await page.reload();
  await expect(page.getByTestId("summary")).toContainText("C2 · Technical (Electrical) · normal");
  await page.getByRole("radio", { name: "10" }).click();
  await page.getByRole("button", { name: "Start training" }).click();
  for (let i = 1; i <= 5; i++) {
    await expect(page.getByTestId("counter")).toHaveText(`${i} / 10`);
    await expect(page.locator(".card .tag--field")).toHaveText("Electrical"); // only the chosen field
    await page.getByRole("group", { name: "Answer options" }).getByRole("button").nth(i % 3).click();
    await expect(page.getByTestId("feedback")).toContainText(/Correct|Not quite|Wrong|Answer/);
    await page.getByRole("button", { name: /Next/ }).click();
  }
});

test("optional «Вставьте слово»: a sentence with a gap, options in one form, the word shown in place", async ({ page }) => {
  await openHome(page);
  await expect(page.getByText("Дополнительно")).toBeVisible();
  await page.getByRole("button", { name: /Вставьте слово/ }).click();
  await expect(page.getByRole("button", { name: /Вставьте слово/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("single-difficulty")).toBeVisible();
  await expect(page.getByRole("radio", { name: "Сложный" })).toHaveCount(0);
  await chooseLevel(page, "A1");
  await page.getByRole("radio", { name: "Русские" }).click();
  await page.getByRole("radio", { name: "10" }).click();
  await page.getByRole("button", { name: "Начать тренировку" }).click();

  const prompt = page.getByTestId("prompt");
  let translated = 0;
  for (let i = 1; i <= 10; i++) {
    await expect(page.getByTestId("counter")).toHaveText(`${i} / 10`);
    await expect(options(page)).toHaveCount(3);
    await expect(page.getByText("Вставьте пропущенное слово")).toBeVisible();
    const sentence = (await prompt.textContent())!;
    expect(sentence.match(/___/g)).toHaveLength(1);
    expect(sentence).not.toMatch(CYRILLIC);
    const words = (await options(page).locator(".option__text").allTextContents()).map((w) => w.toLowerCase());
    expect(new Set(words).size).toBe(3);
    const tokens = sentence.toLowerCase().split(/[^a-z'-]+/);
    for (const w of words) {
      expect(w).not.toMatch(CYRILLIC);
      expect(tokens).not.toContain(w); // no option is already in the sentence
    }
    await options(page).nth(i % 3).click();
    const feedback = page.getByTestId("feedback");
    await expect(feedback).toBeVisible();
    await expect(prompt).not.toContainText("___");
    expect(words).toContain((await prompt.locator(".gap--filled").textContent())!.toLowerCase());
    if ((await feedback.textContent())!.includes("Перевод предложения")) translated++;
    await page.getByRole("button", { name: i === 10 ? /Результаты/ : /Дальше/ }).click();
  }
  await expect(page.getByTestId("score")).toBeVisible();
  expect(translated).toBeGreaterThanOrEqual(5); // A1 sentences come with a Russian translation
});
