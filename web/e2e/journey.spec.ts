import { expect, test, type Page } from "@playwright/test";

import { translate, type Key, type Language } from "../src/i18n";

const API = process.env.E2E_API ?? "http://127.0.0.1:8790";
const TOKEN = process.env.E2E_TOKEN ?? "";
const USER = process.env.E2E_USER ?? "e2e";
const PASSWORD = process.env.E2E_PASSWORD ?? "";
const SEARCH = process.env.E2E_SEARCH ?? "may_export_report";
const EXPECTED = process.env.E2E_EXPECTED ?? "reports.py";
const QUESTION = process.env.E2E_QUESTION ?? "Where do I check that a user may export a report?";
const SCREENSHOTS = process.env.E2E_SCREENSHOTS;

type PublicConfig = { auth_mode: "token" | "oidc"; language: Language };

/** Signs in with whatever the backend announces (API token or OIDC popup). */
async function signIn(page: Page, publicConfig: PublicConfig) {
  const t = (key: Key) => translate(publicConfig.language, key);
  await page.goto("/");
  if (publicConfig.auth_mode === "token") {
    await page.getByLabel(t("signin.tokenLabel")).fill(TOKEN);
    await page.getByRole("button", { name: t("signin.button") }).click();
  } else {
    const popupOpened = page.waitForEvent("popup");
    await page.getByRole("button", { name: t("signin.button") }).click();
    const popup = await popupOpened;
    await popup.locator("#username").fill(USER);
    await popup.locator("#password").fill(PASSWORD);
    await popup.locator("#kc-login").click();
  }
  await expect(page.getByRole("button", { name: t("header.signOut") })).toBeVisible({ timeout: 30_000 });
}

test("sign-in, search, source and question", async ({ page, request }) => {
  const publicConfig = (await (await request.get(`${API}/v1/public-config`)).json()) as PublicConfig;
  const t = (key: Key) => translate(publicConfig.language, key);
  if (publicConfig.auth_mode === "token") test.skip(!TOKEN, "E2E_TOKEN missing");
  else test.skip(!PASSWORD, "E2E_PASSWORD missing");

  await signIn(page, publicConfig);

  // Nothing in browser storage: credentials stay in memory.
  const storage = await page.evaluate(() => [window.localStorage.length, window.sessionStorage.length]);
  expect(storage).toEqual([0, 0]);

  await page.getByRole("button", { name: t("nav.search"), exact: true }).click();
  await page.getByLabel(t("search.input")).fill(SEARCH);
  await page.getByRole("button", { name: t("search.submit") }).click();
  await expect(page.getByText(/\d+ \S+ \S+ \d+ ms/)).toBeVisible({ timeout: 60_000 });
  const first = page.locator(".chunks .chunk").first();
  await expect(first).toContainText(EXPECTED);
  await page.waitForTimeout(800);
  await first.click();
  await expect(page.getByRole("region", { name: t("source.label") })).toContainText(EXPECTED);
  await page.waitForTimeout(1500);
  if (SCREENSHOTS) await page.screenshot({ path: `${SCREENSHOTS}/search.png` });

  await page.getByRole("button", { name: t("nav.repos"), exact: true }).click();
  await expect(page.getByRole("region", { name: t("repos.label") }).locator("table")).toBeVisible();
  await page.waitForTimeout(1500);

  if (process.env.E2E_CHAT) {
    await page.getByRole("button", { name: t("nav.ask"), exact: true }).click();
    await page.getByLabel(t("chat.input")).fill(QUESTION);
    await page.getByRole("button", { name: t("chat.ask") }).click();
    const citation = page.locator(".answer .citation").first();
    await expect(citation).toBeVisible({ timeout: 150_000 });
    await expect(page.getByRole("button", { name: t("chat.ask") })).toBeVisible({ timeout: 150_000 });
    await citation.click();
    await expect(page.getByRole("region", { name: t("source.label") })).toBeVisible();
    await page.waitForTimeout(2500);
    if (SCREENSHOTS) await page.screenshot({ path: `${SCREENSHOTS}/chat.png` });
  }
});
