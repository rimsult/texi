import { expect, type Page } from "@playwright/test";
import { createServer, type Server } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import type { AddressInfo } from "node:net";

export const API = "http://localhost:8787";
export const CYRILLIC = /[а-яё]/i;

export async function openHome(page: Page, url = "/") {
  await page.goto(url);
  await expect(page.getByRole("button", { name: "Начать тренировку" })).toBeVisible();
}

export async function chooseLevel(page: Page, level: string) {
  await page.getByRole("button", { name: new RegExp(`^${level}`) }).click();
  await expect(page.getByRole("button", { name: new RegExp(`^${level}`) })).toHaveAttribute("aria-pressed", "true");
}

export function options(page: Page) {
  return page.getByRole("group", { name: "Варианты ответа" }).getByRole("button");
}

/**
 * Answers every question of the running session (always picking `pick`),
 * checking that exactly one option is revealed as correct each time.
 * Returns the number of answers the app reported as correct.
 */
export async function playSession(page: Page, total: number, onQuestion?: (i: number) => Promise<void>, pick = 0,
  onFeedback?: (text: string) => void) {
  let correct = 0;
  for (let i = 1; i <= total; i++) {
    await expect(page.getByTestId("counter")).toHaveText(`${i} / ${total}`);
    await expect(options(page)).toHaveCount(3);
    await onQuestion?.(i);
    await options(page).nth(pick).click();
    const feedback = page.getByTestId("feedback");
    await expect(feedback).toBeVisible();
    await expect(page.getByLabel("верно", { exact: true })).toHaveCount(1);
    const text = (await feedback.textContent())!;
    onFeedback?.(text);
    if (text.includes("Верно!")) correct++;
    else await expect(page.getByLabel("неверно", { exact: true })).toHaveCount(1);
    await page.getByRole("button", { name: i === total ? /Результаты/ : /Дальше/ }).click();
  }
  await expect(page.getByTestId("score")).toHaveText(`${correct} / ${total}`);
  return correct;
}

export async function deviceId(page: Page): Promise<string> {
  return page.evaluate(() => (window as any).__lexi.store.deviceId());
}

export async function pending(page: Page): Promise<number> {
  return page.evaluate(() => (window as any).__lexi.store.pendingCount());
}

const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".webmanifest": "application/manifest+json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

/** A static server we can shut down mid-test to prove the app runs from the SW cache. */
export async function serveStatic(dir: string): Promise<{ url: string; close: () => Promise<void> }> {
  const server: Server = createServer(async (req, res) => {
    const path = normalize(decodeURIComponent(new URL(req.url!, "http://x").pathname)).replace(/^(\.\.[/\\])+/, "");
    let file = join(dir, path);
    try {
      if ((await stat(file)).isDirectory()) file = join(file, "index.html");
    } catch {
      file = join(dir, "index.html");
    }
    try {
      const body = await readFile(file);
      res.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream", "cache-control": "no-cache" });
      res.end(body);
    } catch {
      res.writeHead(404).end();
    }
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://localhost:${port}`,
    close: () =>
      new Promise<void>((r) => {
        server.closeAllConnections();
        server.close(() => r());
      }),
  };
}
