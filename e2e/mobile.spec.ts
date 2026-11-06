import { expect, test, type Page } from "@playwright/test";
import { chooseLevel, openHome, options } from "./helpers";

async function noHorizontalOverflow(page: Page) {
  const { scroll, width } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: window.innerWidth }));
  expect(scroll).toBeLessThanOrEqual(width);
}

test("mobile layout: no horizontal scroll, start button reachable, large tap targets", async ({ page }) => {
  await openHome(page);
  await noHorizontalOverflow(page);
  for (const l of ["A1", "C2"]) {
    await chooseLevel(page, l);
    await noHorizontalOverflow(page);
  }
  // Technical deck + hard mode fit on a phone too (short segment labels).
  await page.getByRole("radio", { name: "Техническая лексика" }).click();
  await expect(page.getByRole("group", { name: "Области технической лексики" })).toBeVisible();
  await page.getByRole("radio", { name: "Сложный" }).click();
  await chooseLevel(page, "B2");
  await noHorizontalOverflow(page);
  const start = page.getByRole("button", { name: "Начать тренировку" });
  await expect(start).toBeInViewport(); // sticky at the bottom without scrolling
  await start.click();

  await expect(options(page)).toHaveCount(3);
  await noHorizontalOverflow(page);
  for (const box of await Promise.all((await options(page).all()).map((o) => o.boundingBox()))) {
    expect(box!.height).toBeGreaterThanOrEqual(44);
  }
  await options(page).first().tap();
  await expect(page.getByTestId("feedback")).toBeVisible();
  await noHorizontalOverflow(page);
  await expect(page.getByRole("button", { name: /Дальше/ })).toBeInViewport();
  await expect(page.getByText("Сложный режим")).toBeVisible();
});
