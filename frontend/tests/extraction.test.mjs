import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
const compiled = ts.transpile(
  readFileSync(new URL("../src/extraction.ts", import.meta.url), "utf8"),
  { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
);
const { currentReview, groups } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
const original = {
  record_id: "r1",
  raw_material: "bagasse",
  metric: "fiber_length",
  measurement_state: "raw_material",
  raw_value: "1.20",
  value: 1.2,
  raw_unit: "mm",
};
test("unreviewed extraction keeps printed precision and does not imply training approval", () => {
  const r = currentReview({ reviews: {} }, original);
  assert.equal(r.current.raw_value, "1.20");
  assert.equal(r.status, "pending");
  assert.equal(r.suitability, "unassessed");
  assert.equal(r.approved_for_training, false);
  r.current.raw_value = "9";
  assert.equal(original.raw_value, "1.20");
});
test("grouping keeps original sample association and distinct measurement states", () => {
  const refined = {
    ...original,
    record_id: "r2",
    measurement_state: "refined",
  };
  const second = { ...original, record_id: "r3", raw_material: "bamboo" };
  const input = [original, refined, second];
  const result = groups(input);
  assert.equal(result.length, 2);
  assert.deepEqual(result[0].records, [original, refined]);
  assert.equal(input.length, 3);
  const reviewed = {
    revision: 1,
    status: "confirmed",
    suitability: "unassessed",
    current: { ...original, raw_value: "1.40" },
    approved_for_training: false,
  };
  assert.equal(
    currentReview({ reviews: { r1: reviewed } }, original).current.raw_value,
    "1.40",
  );
  assert.equal(original.raw_value, "1.20");
});
