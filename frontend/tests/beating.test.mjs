import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
const source = readFileSync(
  new URL("../src/beating.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpile(source, {
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ES2022,
});
const {
  sortedCurve,
  interpolateAt,
  firstReach,
  niceTicks,
  fiberPaths,
  mulberry32,
} = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
const curve = [
  { x: 2000, y: 20 },
  { x: 0, y: 10 },
  { x: 4000, y: 40 },
  { x: 1000, y: Number.NaN },
];

test("curve is sorted and drops non-finite points", () => {
  assert.deepEqual(
    sortedCurve(curve).map((p) => p.x),
    [0, 2000, 4000],
  );
});

test("interpolation stays inside measured range", () => {
  assert.equal(interpolateAt(curve, 2000), 20);
  assert.equal(interpolateAt(curve, 3000), 30);
  assert.equal(interpolateAt(curve, 1000), 15);
  assert.equal(interpolateAt(curve, -1), null);
  assert.equal(interpolateAt(curve, 4001), null);
  assert.equal(interpolateAt([], 0), null);
});

test("first reach interpolates the first crossing only", () => {
  assert.equal(firstReach(curve, 30), 3000);
  assert.equal(firstReach(curve, 5), 0);
  assert.equal(firstReach(curve, 41), null);
  const wavy = [
    { x: 0, y: 10 },
    { x: 10, y: 50 },
    { x: 20, y: 30 },
    { x: 30, y: 60 },
  ];
  assert.equal(firstReach(wavy, 40), 7.5);
});

test("nice ticks cover the range with round steps", () => {
  assert.deepEqual(niceTicks(0, 100, 5), [0, 20, 40, 60, 80, 100]);
  assert.deepEqual(niceTicks(11.5, 88, 5), [0, 20, 40, 60, 80, 100]);
  const t = niceTicks(0.31, 0.47, 4);
  assert.ok(t[0] <= 0.31 && t[t.length - 1] >= 0.47);
  assert.ok(niceTicks(5, 5).length >= 2);
});

test("fibre texture is deterministic and scales with area", () => {
  const a = fiberPaths(300, 300),
    b = fiberPaths(300, 300);
  assert.equal(a.length, 100);
  assert.deepEqual(a, b);
  assert.equal(fiberPaths(600, 300).length, 200);
  assert.match(a[0].d, /^M[\d.-]+,[\d.-]+ C/);
  const r = mulberry32(1);
  const v = [r(), r(), r()];
  assert.ok(v.every((x) => x >= 0 && x < 1));
});
