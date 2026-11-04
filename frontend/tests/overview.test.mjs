import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
const source = readFileSync(
  new URL("../src/overview.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpile(source, {
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ES2022,
});
const { buildSpokes, buildDots, groupBlocks, spokeStart, sweepStart } =
  await import(
    `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
  );

const sample = (code, type, revs, sr, sw = type === "softwood" ? 100 : 0) => ({
  code,
  name: code,
  type,
  sw,
  revs,
  sr,
});

test("spokes are grouped by material and ordered clockwise", () => {
  const { spokes, slots, sector } = buildSpokes(
    [
      sample("SW_2", "softwood", 2000, 14),
      sample("HW_0", "hardwood", 0, 11),
      sample("SW_0", "softwood", 0, 12),
      sample("BL_70", "blend", null, null, 70),
      sample("BL_30", "blend", null, null, 30),
    ],
    3,
  );
  assert.equal(slots, 5 + 9);
  assert.deepEqual(
    spokes.map((p) => p.sample.code),
    ["SW_0", "SW_2", "HW_0", "BL_30", "BL_70"],
  );
  for (let i = 1; i < spokes.length; i++)
    assert.ok(spokes[i].angle > spokes[i - 1].angle);
  const [a0, a1] = sector("softwood");
  assert.ok(a0 < spokes[0].angle && spokes[1].angle < a1);
  assert.equal(sector("missing"), null);
});

test("dots sit in their block ring and cycle sector", () => {
  const obs = [];
  for (const [block, cycles, reps] of [
    ["G01", 3, 5],
    ["G10", 4, 1],
  ])
    for (let c = 1; c <= cycles; c++)
      for (let r = 1; r <= reps; r++)
        obs.push({
          block,
          cycle: c,
          replicate: r,
          grade: null,
          row: obs.length + 2,
          fl: 1,
          review: false,
        });
  const { dots, blocks, cycles, sector, has } = buildDots(obs);
  assert.deepEqual(blocks, ["G01", "G10"]);
  assert.equal(cycles, 4);
  assert.equal(dots.length, 19);
  assert.ok(!has("G01", 4) && has("G10", 4));
  for (const d of dots) {
    const start = -Math.PI / 2 + (d.obs.cycle - 1) * sector;
    assert.ok(d.angle > start && d.angle < start + sector);
  }
});

test("block groups merge neighbours with the same structure", () => {
  const obs = [];
  for (const [block, cycles, reps] of [
    ["G01", 3, 5],
    ["G02", 3, 5],
    ["G03", 3, 3],
    ["G04", 4, 1],
  ])
    for (let c = 1; c <= cycles; c++)
      for (let r = 1; r <= reps; r++)
        obs.push({ block, cycle: c, replicate: r });
  assert.deepEqual(groupBlocks(obs), [
    { blocks: ["G01", "G02"], cycles: 3, replicates: 5, count: 30 },
    { blocks: ["G03"], cycles: 3, replicates: 3, count: 9 },
    { blocks: ["G04"], cycles: 4, replicates: 1, count: 4 },
  ]);
});

test("intro timing increases around the dial", () => {
  assert.ok(spokeStart(0, 10) < spokeStart(9, 10));
  assert.ok(sweepStart(-Math.PI / 2 + 0.1) < sweepStart(Math.PI / 2));
  assert.ok(Math.abs(sweepStart(-Math.PI / 2) - 0.25) < 1e-9);
});
