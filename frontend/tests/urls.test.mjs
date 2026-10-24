import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = ts.transpile(readFileSync(new URL("../src/urls.ts", import.meta.url), "utf8"),
  { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 });
const { appPath, apiPath } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

test("root deployment keeps existing API and asset paths", () => {
  assert.equal(apiPath("samples?page=2"), "/api/v1/samples?page=2");
  assert.equal(appPath("favicon.svg", "/"), "/favicon.svg");
});

test("mounted deployment retains downloads, page anchors and query parameters", () => {
  assert.equal(apiPath("literature/documents/id/pdf#page=5", "/fiberscope/"),
    "/fiberscope/api/v1/literature/documents/id/pdf#page=5");
  assert.equal(apiPath("literature/extractions/id/confirmed?format=csv", "/fiberscope/"),
    "/fiberscope/api/v1/literature/extractions/id/confirmed?format=csv");
  assert.equal(appPath("/favicon.svg", "/fiberscope/"), "/fiberscope/favicon.svg");
});
