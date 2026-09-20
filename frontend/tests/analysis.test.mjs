import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
const source = readFileSync(
  new URL("../src/analysis.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpile(source, {
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ES2022,
});
const { pearson, axisDomain } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
test("Pearson handles positive, negative and uncorrelated data", () => {
  assert.equal(
    pearson([
      [0, 0],
      [1, 2],
      [2, 4],
    ]),
    1,
  );
  assert.equal(
    pearson([
      [0, 4],
      [1, 2],
      [2, 0],
    ]),
    -1,
  );
  assert.equal(
    pearson([
      [-1, 1],
      [0, -2],
      [1, 1],
    ]),
    0,
  );
  assert.ok(
    Math.abs(
      pearson([
        [1, 1],
        [2, 3],
        [3, 2],
      ]) - 0.5,
    ) < 1e-12,
  );
});
test("Pearson excludes nonfinite pairs and rejects insufficient or constant data", () => {
  assert.equal(
    pearson([
      [1, 2],
      [2, 3],
    ]),
    null,
  );
  assert.equal(
    pearson([
      [1, 2],
      [1, 3],
      [1, 4],
    ]),
    null,
  );
  assert.equal(
    pearson([
      [1, 2],
      [2, 2],
      [3, 2],
    ]),
    null,
  );
  assert.equal(
    pearson([
      [0, 0],
      [1, 2],
      [2, 4],
      [NaN, 1],
      [1, Infinity],
    ]),
    1,
  );
});
test("Axes contain observations including constant zero and negative values", () => {
  for (const values of [
    [0, 0, 0],
    [2, 2, 2],
    [-8, -5, -1],
    [-1, 0, 1],
  ]) {
    const [min, max] = axisDomain(values);
    assert.ok(min < max);
    assert.ok(values.every((v) => v >= min && v <= max));
  }
  assert.deepEqual(axisDomain([]), [0, 1]);
});
