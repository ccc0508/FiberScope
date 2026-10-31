// Run with playwright-cli run-code --filename frontend/scripts/browser-audit.js.
// Requires the local frontend and real read-only API. No database mutations.
async (page) => {
  const base = "http://127.0.0.1:5173";
  const results = [],
    runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  const check = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const test = async (name, action) => {
    try {
      const detail = await action();
      results.push({ name, passed: true, detail });
    } catch (error) {
      results.push({ name, passed: false, error: error.message });
    }
  };
  const go = async (path, selector = "main table tbody tr") => {
    await page.goto(base + path);
    await page.locator(selector).first().waitFor();
  };
  const format = (v, digits = 4) =>
    v == null
      ? "—"
      : v.toLocaleString("zh-CN", {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        });
  const choose = async (id, index) => {
    await page.locator(`[aria-controls="${id}-options"]`).click();
    await page.locator(`#${id}-options [role=option]`).nth(index).click();
    await page.locator(`#${id}-options`).waitFor({ state: 'hidden' });
  };
  const api = async (path) => {
    const response = await page.request.get(`${base}/api/v1/${path}`);
    check(response.ok(), `API ${path}: ${response.status()}`);
    return response.json();
  };
  const [metadata, samples, beating, blends, paired, cycles, details, lineage] =
    await Promise.all([
      api("metadata"),
      ...[
        "samples",
        "beating",
        "blends",
        "fiber-paper",
        "recycled/cycles",
        "recycled/details",
        "lineage",
      ].map((p) => api(p + "?page_size=500").then((b) => b.data)),
    ]);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await test("Overview: pagination, invalid URLs and sample/source round trip", async () => {
    await go("/");
    const seen = [];
    while (true) {
      seen.push(...(await page.locator("main .sample-code").allTextContents()));
      const next = page.getByRole("button", { name: "下一页", exact: true });
      if (await next.isDisabled()) break;
      const first = await page
        .locator("main .sample-code")
        .first()
        .textContent();
      await next.click();
      await page.waitForFunction(
        (old) =>
          document.querySelector("main .sample-code")?.textContent !== old,
        first,
      );
      await page.waitForFunction(
        () => !document.querySelector('[aria-label="上一页"]').disabled,
      );
    }
    check(
      seen.length === samples.length && new Set(seen).size === samples.length,
      "overview pagination missing/duplicate rows",
    );
    for (const value of [
      "1.5",
      "Infinity",
      "100001",
      "-1",
      "garbage",
      "99999",
    ]) {
      await go("/?page=" + value, "main .sample-code");
      check(
        !(await page.locator("main [role=alert]").count()),
        "invalid page causes an error: " + value,
      );
    }
    await go("/?q=BLEND_SW010_HW090", "main .sample-code");
    await page.locator("main .sample-code").first().focus();
    await page.keyboard.press("Enter");
    await page.locator(".detail-drawer[open]").waitFor();
    await page.keyboard.press("Escape");
    check(
      await page
        .locator("main .sample-code")
        .first()
        .evaluate((e) => e === document.activeElement),
      "drawer focus not restored",
    );
    await page.keyboard.press("Enter");
    await page.getByRole("link", { name: "查看合并后的来源行" }).click();
    await page.locator(".sources-table").waitFor();
    check(
      (await page.locator(".sources-table tbody tr").count()) === 2,
      "blend source rows not grouped",
    );
    await page.locator(".sources-table tbody button").first().click();
    check(
      (await page.locator(".usage-list li").count()) === 4,
      "missing component uses",
    );
    await page.locator(".usage-list a").first().click();
    await page.locator("main .sample-code").waitFor();
    await page.goBack();
    await page.locator(".sources-table").waitFor();
    await page.reload();
    await page.locator(".sources-table").waitFor();
    check(
      (await page.locator(".sources-table tbody tr").count()) === 2,
      "source query lost on refresh/back",
    );
    return { samples: seen.length, invalidLinks: 6 };
  });
  await test("Beating/blends: every core metric matches API values and ordering", async () => {
    const metrics = metadata.indicators.filter((i) => i.scope.includes("core"));
    let values = 0;
    for (const config of [
      {
        path: "/beating",
        id: "beating-metric",
        // 按原料分组（针叶在前），组内按打浆转数升序；分组标题行不计入
        rows: "main table tbody tr[data-code]",
        data: [...beating].sort(
          (a, b) =>
            (a.material_code === "SW" ? 0 : 1) -
              (b.material_code === "SW" ? 0 : 1) ||
            a.beating_revolutions - b.beating_revolutions ||
            a.canonical_code.localeCompare(b.canonical_code),
        ),
        metrics: [{ key: "beating_degree_sr" }, ...metrics],
        cell: 2,
      },
      {
        path: "/blends",
        id: "blend-metric",
        data: [...blends].sort(
          (a, b) =>
            a.sw_proportion_pct - b.sw_proportion_pct ||
            a.canonical_code.localeCompare(b.canonical_code),
        ),
        metrics,
        cell: 5,
      },
    ]) {
      await go(config.path, "main .sample-code");
      for (let i = 0; i < config.metrics.length; i++) {
        await choose(config.id, i);
        const actual = await page
          .locator(config.rows ?? "main table tbody tr")
          .evaluateAll(
            (rows, col) =>
              rows.map((r) => [
                r.cells[0].textContent.trim(),
                r.cells[col].textContent.trim(),
              ]),
            config.cell,
          );
        const expected = config.data.map((r) => [
          r.canonical_code,
          format(r[config.metrics[i].key]),
        ]);
        check(
          JSON.stringify(actual) === JSON.stringify(expected),
          config.path + " mismatch " + config.metrics[i].key,
        );
        values += actual.length;
      }
      check(
        (await page.locator("main").innerText()).includes("单位未确认"),
        "missing unconfirmed unit notice",
      );
      await page.locator("main .sample-code").first().click();
      await page.locator(".detail-drawer[open]").waitFor();
      await page.keyboard.press("Escape");
    }
    return { displayedValues: values };
  });
  await test("Association: all axis indicators and grouped counts", async () => {
    await go("/association", "main .sample-code");
    const sorted = [...paired].sort((a, b) =>
      a.canonical_code.localeCompare(b.canonical_code),
    );
    let values = 0;
    for (const [group, id, col] of [
      ["fiber", "association-x", 2],
      ["paper", "association-y", 3],
    ]) {
      const metrics = metadata.indicators.filter(
        (i) => i.scope.includes("core") && i.group === group,
      );
      for (let i = 0; i < metrics.length; i++) {
        await choose(id, i);
        const actual = await page
          .locator("main table tbody tr")
          .evaluateAll(
            (rows, col) => rows.map((r) => r.cells[col].textContent.trim()),
            col,
          );
        check(
          JSON.stringify(actual) ===
            JSON.stringify(sorted.map((r) => format(r[metrics[i].key]))),
          "association mismatch " + metrics[i].key,
        );
        values += actual.length;
      }
    }
    for (const [index, count] of [
      [1, 28],
      [2, 24],
      [3, 9],
    ]) {
      await choose("association-type", index);
      check(
        (await page.locator("main .sample-code").count()) === count,
        "association type count",
      );
    }
    return { displayedValues: values };
  });
  await test("Recycled: all cycle means, block counts, indicators and source rows", async () => {
    const metrics = metadata.indicators.filter((i) =>
      i.scope.includes("recycled"),
    );
    let means = 0;
    for (const row of cycles) {
      const raw = details.filter(
        (d) => d.block_code === row.block_code && d.cycle_no === row.cycle_no,
      );
      check(raw.length === row.replicate_count, "replicate count mismatch");
      for (const m of metrics) {
        const v = raw.map((d) => d[m.key]).filter((v) => v != null);
        const mean = v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
        check(
          mean === null
            ? row[m.key] === null
            : Math.abs(mean - row[m.key]) < 1e-8,
          "cycle mean mismatch " + row.block_code + "/" + m.key,
        );
        means++;
      }
    }
    await go("/recycled");
    for (let i = 0; i < metrics.length; i++) {
      await choose("recycled-metric", i);
      const actual = await page
        .locator("main section table tbody tr")
        .evaluateAll((rows) => rows.map((r) => r.cells[1].textContent.trim()));
      check(
        JSON.stringify(actual) ===
          JSON.stringify(
            cycles
              .filter((r) => r.block_code === "G01")
              .map((r) => format(r[metrics[i].key], 3)),
          ),
        "recycled displayed metric mismatch",
      );
    }
    let records = 0;
    for (let i = 0; i < metadata.blocks.length; i++) {
      await choose("recycled-block", i);
      const expected = cycles.filter(
        (r) => r.block_code === metadata.blocks[i].block_code,
      );
      check(
        (await page.locator("main section table tbody tr").count()) ===
          expected.length,
        "block cycle count",
      );
      for (let j = 0; j < expected.length; j++) {
        await page.locator("main section table tbody button").nth(j).click();
        const raw = details.filter(
          (d) =>
            d.block_code === expected[j].block_code &&
            d.cycle_no === expected[j].cycle_no,
        );
        check(
          (await page.locator(".observations-dialog tbody tr").count()) ===
            raw.length,
          "raw observation count",
        );
        const body = await page.locator(".observations-dialog").innerText();
        for (const r of raw)
          check(
            body.includes("第 " + r.source_row + " 行"),
            "missing Excel source row",
          );
        records += raw.length;
        await page.keyboard.press("Escape");
      }
    }
    return { means, records };
  });
  await test("Sources: all rows across pagination and source-only records", async () => {
    await go("/sources");
    const seen = [];
    while (true) {
      seen.push(
        ...(await page
          .locator(".sources-table tbody tr td:first-child")
          .allTextContents()),
      );
      const next = page.getByRole("button", { name: "下一页", exact: true });
      if (await next.isDisabled()) break;
      await next.click();
      await page.waitForTimeout(35);
    }
    const expected = new Set(
      [...lineage, ...details].map((r) =>
        JSON.stringify([
          r.file_name,
          r.sheet_name,
          r.source_version,
          r.source_row,
        ]),
      ),
    ).size;
    check(
      seen.length === expected && new Set(seen).size === expected,
      "source pagination mismatch",
    );
    await go("/sources?q=data5%20Sheet1%202");
    await page
      .locator(".sources-table tbody tr")
      .filter({ hasText: "第 2 行" })
      .getByRole("button")
      .click();
    check(
      (await page.locator(".source-dialog").innerText()).includes(
        "当前没有关联到样本",
      ),
      "invented source-only association",
    );
    await page.keyboard.press("Escape");
    return { rows: seen.length };
  });
  await test("All six pages: 503 recovery and empty responses", async () => {
    for (const [path, endpoint] of [
      ["/", "samples"],
      ["/beating", "beating"],
      ["/blends", "blends"],
      ["/association", "fiber-paper"],
      ["/recycled", "recycled/cycles"],
      ["/sources", "lineage"],
    ]) {
      const pattern = `**/api/v1/${endpoint}?*`;
      try {
        await page.route(pattern, (r) =>
          r.fulfill({
            status: 503,
            contentType: "application/json",
            body: JSON.stringify({ error: { message: "验收模拟服务不可用" } }),
          }),
        );
        await page.goto(base + path);
        await page.locator("main [role=alert]").first().waitFor();
        await page.unroute(pattern);
        await page
          .getByRole("button", { name: "刷新数据", exact: true })
          .click();
        await page.locator("main table tbody tr").first().waitFor();
        check(
          !(await page.locator("main [role=alert]").count()),
          "error recovery failed " + path,
        );
        await page.route("**/api/v1/**", async (r) => {
          const response = await r.fetch();
          const body = await response.json();
          if (Array.isArray(body.data)) {
            body.data = [];
            body.pagination = { ...body.pagination, total: 0, total_pages: 0 };
          }
          await r.fulfill({ response, json: body });
        });
        await page.reload();
        await page
          .getByRole("button", { name: "刷新数据", exact: true })
          .waitFor();
        await page.waitForFunction(
          () => !document.querySelector(".page-heading button")?.disabled,
        );
        check(
          !(await page.locator("main [role=alert]").count()),
          "empty data error " + path,
        );
        check(
          !(await page.locator("main").innerText()).includes("NaN"),
          "empty data NaN " + path,
        );
      } finally {
        await page.unrouteAll({ behavior: "wait" });
      }
    }
    return { pages: 6 };
  });
  await test("Responsive layouts, mobile navigation and filter keyboard controls", async () => {
    let checked = 0;
    for (const width of [1440, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      for (const path of [
        "/",
        "/beating",
        "/blends",
        "/association",
        "/recycled",
        "/sources",
      ]) {
        await go(path);
        check(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
          ),
          "page horizontal overflow " + width + " " + path,
        );
        const trigger = page.getByRole("combobox").first();
        await trigger.focus();
        await page.keyboard.press("Enter");
        const list = page.getByRole("listbox");
        await list.waitFor();
        check(
          await list.evaluate((e) => {
            const r = e.getBoundingClientRect();
            return r.left >= 0 && r.right <= document.documentElement.clientWidth + 1;
          }),
          "filter outside viewport " + path + " " + width,
        );
        await page.keyboard.press("End");
        await page.keyboard.press("Home");
        await page.keyboard.press("Escape");
        check(
          await trigger.evaluate((e) => e === document.activeElement),
          "filter focus not returned",
        );
        if (width <= 390) {
          await page.getByRole("button", { name: "展开导航" }).click();
          await page.keyboard.press('Escape');
          check(!await page.locator('.sidebar').isVisible(), 'Escape does not close mobile navigation');
          check(await page.getByRole('button', {name:'展开导航'}).evaluate(e=>e===document.activeElement), 'navigation focus not restored');
          await page.getByRole("button", { name: "展开导航" }).click();
          await page.locator('.sidebar-bottom button').focus();
          await page.keyboard.press('Tab');
          check(await page.locator('.brand-link').evaluate(e=>e===document.activeElement), 'mobile navigation focus escapes');
          await page.locator('nav a[href="/sources"]').click();
          await page.locator(".sources-table").waitFor();
          check(
            !(await page.locator(".sidebar").isVisible()),
            "mobile navigation remains open",
          );
        }
        checked++;
      }
    }
    return { layouts: checked };
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await go("/");
  check(
    runtimeErrors.length === 0,
    "Browser runtime errors: " + runtimeErrors.join("; "),
  );
  console.log(
    JSON.stringify(
      { passed: results.every((r) => r.passed), results, runtimeErrors },
      null,
      2,
    ),
  );
  if (results.some((r) => !r.passed))
    throw new Error(JSON.stringify({ results, runtimeErrors }));
}
