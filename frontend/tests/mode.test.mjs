import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = ts.transpile(readFileSync(new URL("../src/modeResolve.ts", import.meta.url), "utf8"),
  { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 });
const { resolveMode, isMode, MODES } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

test("a ?mode= link wins over the stored choice and the colour scheme", () => {
  assert.deepEqual(resolveMode("garden", "polarized", true), { mode: "garden", source: "query" });
  assert.deepEqual(resolveMode("polarized", "garden", false), { mode: "polarized", source: "query" });
});

test("a stored choice wins over the colour scheme; invalid values are ignored", () => {
  assert.deepEqual(resolveMode(null, "polarized", false), { mode: "polarized", source: "storage" });
  assert.deepEqual(resolveMode("dark", "garden", true), { mode: "garden", source: "storage" });
  assert.deepEqual(resolveMode("", "light", true), { mode: "polarized", source: "system" });
});

test("without a choice, dark schemes get polarized and light schemes get garden", () => {
  assert.equal(resolveMode(null, null, true).mode, "polarized");
  assert.equal(resolveMode(undefined, undefined, false).mode, "garden");
});

test("only the two known modes are valid", () => {
  assert.deepEqual([...MODES], ["polarized", "garden"]);
  assert.equal(isMode("garden"), true);
  assert.equal(isMode("Garden"), false);
  assert.equal(isMode(undefined), false);
});

test("the inline pre-paint script in index.html follows the same order", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1] ?? "";
  const q = script.indexOf('get("mode")'), s = script.indexOf("localStorage.getItem"), m = script.indexOf("prefers-color-scheme: dark");
  assert.ok(q > 0 && s > q && m > s, "query → storage → colour scheme");
  assert.match(script, /fiberscope-mode/);
});
