import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { API, chooseLevel, deviceId, openHome, pending, playSession, serveStatic } from "./helpers";

const DIST = fileURLToPath(new URL("../apps/web/dist-e2e", import.meta.url));

test("works with the web server gone and the network off, then syncs when back online", async ({ page, context, request }) => {
  const site = await serveStatic(DIST);
  try {
    await openHome(page, site.url);
    // Service worker installed and every pack precached.
    await expect(page.locator(".status[data-offline-ready]")).toBeVisible({ timeout: 30_000 });
    await page.evaluate(async () => {
      await navigator.serviceWorker.ready;
      if (!navigator.serviceWorker.controller)
        await new Promise((r) => navigator.serviceWorker.addEventListener("controllerchange", r, { once: true }));
    });
    const cached = await page.evaluate(async () => {
      const urls: string[] = [];
      for (const name of await caches.keys()) for (const req of await (await caches.open(name)).keys()) urls.push(new URL(req.url).pathname);
      return urls;
    });
    for (const l of ["A1", "A2", "B1", "B2", "C1", "C2"]) {
      expect(cached).toContain(`/packs/${l}.json`);
      expect(cached).toContain(`/packs/tech-${l}.json`);
    }
  } finally {
    await site.close(); // nothing serves the app any more
  }

  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole("button", { name: "Начать тренировку" })).toBeVisible();
  await expect(page.getByTestId("sync-status")).toHaveText("Офлайн-режим");

  await chooseLevel(page, "A2");
  await page.getByRole("radio", { name: "10" }).click();
  await page.getByRole("button", { name: "Начать тренировку" }).click();
  await playSession(page, 10);
  expect(await pending(page)).toBe(10);
  await expect(page.getByTestId("sync-status")).toHaveText("Офлайн · 10 в очереди");

  const id = await deviceId(page);
  expect((await request.get(`${API}/v1/devices/${id}/summary`)).status()).toBe(404);

  await context.setOffline(false);
  await expect(page.getByTestId("sync-status")).toHaveText("Синхронизировано", { timeout: 15_000 });
  expect(await pending(page)).toBe(0);
  const summary = await (await request.get(`${API}/v1/devices/${id}/summary`)).json();
  expect(summary).toMatchObject({ events: 10, words: 10 });
});
