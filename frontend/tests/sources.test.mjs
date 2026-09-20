import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
const compiled = ts.transpile(
  readFileSync(new URL("../src/sources.ts", import.meta.url), "utf8"),
  {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
);
const { groupSources, matchesSource, usageLabel } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
const row = {
  source_id: 158,
  file_name: "复配.xlsx",
  sheet_name: "Sheet1",
  source_version: "0110",
  source_row: 3,
  canonical_code: "BLEND_SW010_HW090",
  display_name: "针叶木浆10%+阔叶木浆90%",
  usage_type: "experiment_sample",
  material_code: null,
  experiment_code: "BLEND",
  display_code: "zk19",
};
test("one Excel row retains four distinct uses, including both component materials", () => {
  const input = [
    row,
    { ...row, usage_type: "fiber_measurement" },
    { ...row, usage_type: "sample_component", material_code: "SW" },
    { ...row, usage_type: "sample_component", material_code: "HW" },
  ];
  const [source] = groupSources(input, []);
  assert.equal(groupSources(input, []).length, 1);
  assert.equal(source.usages.length, 4);
  assert.equal(new Set(source.usages.map(usageLabel)).size, 4);
  assert.ok(matchesSource(source, "blend_sw010 hw090"));
  assert.ok(matchesSource(source, "复配.xlsx 3"));
  assert.ok(!matchesSource(source, "G01"));
  assert.equal(input[0], row);
});
test("source coordinates include file, sheet, row and version and sort row numbers numerically", () => {
  const grouped = groupSources(
    [
      row,
      { ...row, source_row: 12 },
      { ...row, source_row: 2 },
      { ...row, sheet_name: "Sheet2" },
      { ...row, file_name: "另一文件.xlsx" },
      { ...row, source_version: "原始版" },
    ],
    [],
  );
  assert.equal(grouped.length, 6);
  assert.deepEqual(
    grouped
      .filter(
        (r) =>
          r.file_name === row.file_name &&
          r.sheet_name === "Sheet1" &&
          r.source_version === "0110",
      )
      .map((r) => r.source_row),
    [2, 3, 12],
  );
});
test("source-only rows stay unlinked; recycled rows preserve cycles, repetitions, nulls and zeros", () => {
  const sourceOnly = {
    ...row,
    canonical_code: null,
    display_name: null,
    usage_type: "source_only",
  };
  const observation = {
    file_name: "汇总.xlsx",
    sheet_name: "Sheet1",
    source_version: "正式汇总版",
    source_row: 2,
    block_code: "G01",
    cycle_no: 1,
    replicate_no: 1,
    tear_strength_mn: 0,
    burst_strength_kpa: null,
  };
  const grouped = groupSources([sourceOnly], [observation]);
  assert.equal(grouped.length, 2);
  const core = grouped.find((r) => r.usages.length);
  assert.equal(core.usages[0].canonical_code, null);
  assert.equal(usageLabel(core.usages[0]), "仅保留来源");
  const recycled = grouped.find((r) => r.observations.length);
  assert.deepEqual(recycled.observations, [observation]);
  assert.ok(matchesSource(recycled, "g01"));
  assert.ok(!matchesSource(recycled, "BLEND"));
  assert.deepEqual(groupSources([], []), []);
});
