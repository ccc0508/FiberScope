import assert from "node:assert/strict";
import { chromium } from "playwright";

const BASE_URL = (process.env.SMOKE_BASE_URL ?? "http://127.0.0.1:4173").replace(/\/+$/, "");

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  const pageErrors = [];
  const serverErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 500) {
      serverErrors.push(`${response.status()} ${response.url()}`);
    }
  });

  try {
    // 1. Overview + sample drawer + mode switch
    await page.goto(`${BASE_URL}/?mode=polarized`, { waitUntil: "networkidle" });
    await page.locator("main .sample-code").first().waitFor();
    assert.equal(await page.locator("main [role=alert]").count(), 0, "Unexpected alert on /");

    await page.locator("main .sample-code").first().click();
    await page.locator(".detail-drawer[open]").waitFor();
    await page.keyboard.press("Escape");
    await page.locator(".detail-drawer[open]").waitFor({ state: "detached" });

    // Mode switching (polarized -> garden -> polarized)
    await page.locator(".mode-switch").getByRole("radio", { name: "花园" }).click();
    await page.locator('html[data-mode="garden"]').waitFor({ state: "attached" });
    await page.locator(".mode-switch").getByRole("radio", { name: "偏光" }).click();
    await page.locator('html[data-mode="polarized"]').waitFor({ state: "attached" });

    // 2. Beating curve + table
    await page.goto(`${BASE_URL}/beating`, { waitUntil: "networkidle" });
    await page.locator(".beating-table tbody tr[data-code]").first().waitFor();
    await page.locator("svg.beating-plot").waitFor();

    // 3. Blends
    await page.goto(`${BASE_URL}/blends`, { waitUntil: "networkidle" });
    await page.locator("main table tbody tr").first().waitFor();
    assert.equal(await page.locator("main [role=alert]").count(), 0, "Unexpected alert on /blends");

    // 4. Association
    await page.goto(`${BASE_URL}/association`, { waitUntil: "networkidle" });
    await page.locator("main table tbody tr").first().waitFor();
    assert.equal(await page.locator("main [role=alert]").count(), 0, "Unexpected alert on /association");

    // 5. Recycled
    await page.goto(`${BASE_URL}/recycled`, { waitUntil: "networkidle" });
    await page.locator("main table tbody tr").first().waitFor();
    assert.equal(await page.locator("main [role=alert]").count(), 0, "Unexpected alert on /recycled");

    // 6. Sources
    await page.goto(`${BASE_URL}/sources`, { waitUntil: "networkidle" });
    await page.locator(".sources-table tbody tr").first().waitFor();
    assert.ok(
      (await page.locator(".sources-table tbody tr").count()) > 0,
      "Expected at least one source row on /sources",
    );

    // 7. Prediction: validation + fiber mode + degree mode
    await page.goto(`${BASE_URL}/prediction`, { waitUntil: "networkidle" });
    await page.locator(".prediction-form").waitFor();
    await page.getByRole("button", { name: "开始预测" }).click();
    await page.locator("input[aria-invalid='true']").first().waitFor();

    await page.getByRole("button", { name: /填入示例/ }).click();
    await page.getByRole("button", { name: "开始预测" }).click();
    await page.locator(".prediction-paper").first().waitFor();

    await page.getByRole("button", { name: "只有打浆度" }).click();
    await page.getByRole("button", { name: /填入示例/ }).click();
    await page.getByRole("button", { name: "开始预测" }).click();
    await page.locator(".prediction-fibers tbody tr").first().waitFor();

    // 8. Glossary
    await page.goto(`${BASE_URL}/glossary`, { waitUntil: "networkidle" });
    await page.locator(".glossary-index-item").first().waitFor();

    // 9. Mobile viewport overflow check
    await page.setViewportSize({ width: 390, height: 844 });
    for (const path of ["/", "/beating", "/prediction", "/sources"]) {
      await page.goto(`${BASE_URL}${path}`, { waitUntil: "networkidle" });
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      );
      assert.equal(overflow, false, `Horizontal overflow at 390px on ${path}`);
    }

    assert.deepEqual(pageErrors, [], `Uncaught page errors: ${pageErrors.join("; ")}`);
    assert.deepEqual(serverErrors, [], `HTTP 5xx errors: ${serverErrors.join("; ")}`);
    console.log("Playwright smoke suite passed across all 8 non-LLM pages.");
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
