import { expect, test } from "@playwright/test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chooseLevel, CYRILLIC, openHome, options, playSession } from "./helpers";

/** The single-file build (`npm run build:standalone`), opened straight from disk. */
const FILE = pathToFileURL(fileURLToPath(new URL("../apps/web/dist-standalone/Texi.html", import.meta.url))).href;

test("Texi.html works from disk with no server and no network, and keeps progress", async ({ page, context }) => {
  const remote: string[] = [];
  page.on("request", (r) => {
    if (!/^(file|data|blob):/.test(r.url())) remote.push(r.url());
  });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await context.setOffline(true);

  await openHome(page, FILE);
  await expect(page.getByTestId("sync-status")).toHaveText("Прогресс на устройстве");
  await chooseLevel(page, "A1");
  await page.getByRole("radio", { name: "Русские" }).click();
  await page.getByRole("radio", { name: "10" }).click();
  await page.getByRole("button", { name: "Начать тренировку" }).click();
  await playSession(page, 10, async () => {
    for (const text of await options(page).locator(".option__text").allTextContents()) expect(text).toMatch(CYRILLIC);
  });
  await page.getByRole("button", { name: /На главную/ }).click();
  await expect(page.getByRole("button", { name: /^A1/ })).toContainText("начато 10");

  // Progress and settings survive closing the page.
  await page.reload();
  await expect(page.getByRole("button", { name: /^A1/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: /^A1/ })).toContainText("начато 10");

  // Technical deck in hard mode is embedded as well.
  await page.getByRole("radio", { name: "Техническая лексика" }).click();
  await chooseLevel(page, "B2");
  await page.getByRole("radio", { name: "Сложный" }).click();
  await page.getByRole("button", { name: "Начать тренировку" }).click();
  await expect(page.getByText("Сложный режим")).toBeVisible();
  await playSession(page, 10, () => expect(page.locator(".card .tag--field")).toBeVisible(), 1);

  const events = await page.evaluate(() => (window as any).__lexi.store.pendingEvents(100));
  expect(events).toHaveLength(20);
  expect(events.filter((e: { deck: string; difficulty: string }) => e.deck === "tech" && e.difficulty === "hard")).toHaveLength(10);
  expect(remote).toEqual([]);
  expect(errors).toEqual([]);
});
