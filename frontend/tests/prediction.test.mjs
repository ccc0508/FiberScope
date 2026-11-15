import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

function moduleUrl(file, replacements = {}) {
  let source = ts.transpile(readFileSync(new URL(`../src/${file}`, import.meta.url), "utf8"),
    { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 });
  for (const [path, url] of Object.entries(replacements)) source = source.replaceAll(`from "${path}"`, `from "${url}"`);
  return `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
}
const urls = moduleUrl("urls.ts");
const api = moduleUrl("api.ts", { "./urls": urls });
const { predict, predictionCsv, predictionNumber, validatePredictionInput } = await import(moduleUrl("prediction.ts", { "./api": api, "./urls": urls }));

test("degree validation rejects 150, blank, zero and nonfinite values, while permitting physical boundary values", () => {
  for (const value of [150, "", undefined, 0, -1, Infinity, NaN, "bad"])
    assert.match(validatePredictionInput("degree", [], value, {}).degree, /不超过100/);
  for (const value of [0.00000001, 50, 100])
    assert.deepEqual(validatePredictionInput("degree", [], value, {}), {});
});

test("all required fields are highlighted at once; optional blanks and out-of-training-range inputs remain allowed", () => {
  const fields = [
    { key: "length", name: "长度", unit: "mm", range: [0.8, 1.5], required: true },
    { key: "pct", name: "比例", unit: "%", range: [10, 60], required: true },
    { key: "angle", name: "角度", unit: "°", range: [130, 139], required: false },
  ];
  assert.deepEqual(Object.keys(validatePredictionInput("fiber", fields, "", {})), ["length", "pct"]);
  assert.deepEqual(validatePredictionInput("fiber", fields, "", { length: 5, pct: 50, angle: "" }), {});
  assert.deepEqual(Object.keys(validatePredictionInput("fiber", fields, "", { length: -1, pct: 101, angle: 181 })), ["length", "pct", "angle"]);
});

test("extreme predictions use scientific notation without clipping or hiding underflow; ordinary values retain precision", () => {
  assert.equal(predictionNumber(743141474799419), "7.431e+14");
  assert.equal(predictionNumber(-743141474799419), "-7.431e+14");
  assert.equal(predictionNumber(0.00000000012), "1.200e-10");
  assert.equal(predictionNumber(54.2938), "54.294");
  assert.equal(predictionNumber(0), "0.000");
  assert.equal(predictionNumber(Infinity), "数值不可用");
});

test("CSV retains inputs, units, model version, low reliability and chain caveats", () => {
  const csv = predictionCsv({ species_name: "针叶木", species: "softwood", mode: "degree",
    model_version: "abc123", input: { degree: 50 }, warnings: ['整链未经验证，包含"参考"结果'],
    paper: [{ name: "透气度", value: 2.3, unit: "μm/(Pa·s)", unit_status: "tentative",
      status: "整链参考", nested_r2: 0.94, notes: ["依赖低可靠性纤维"] }],
    fiber: [{ name: "扭结角", value: 137, unit: "°", model_reliable: false, in_range: true, cv_r2: -0.01 }],
  });
  assert.ok(csv.startsWith("\uFEFF"));
  for (const expected of ["abc123", "degree", "50", "整链参考", "依赖低可靠性纤维", "单位暂定", "仅供参考", '""参考""'])
    assert.ok(csv.includes(expected), expected);
  assert.equal(csv.split("\r\n").length, 3);
});

test("prediction sends JSON to the existing API and reads its result", async (t) => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/v1/prediction/degree");
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), { species: "softwood", degree: 50 });
    return { ok: true, json: async () => ({ mode: "degree", paper: [] }) };
  });
  globalThis.window = globalThis;
  const result = await predict("degree", { species: "softwood", degree: 50 }, new AbortController().signal);
  assert.equal(result.mode, "degree");
});

test("backend validation errors retain the message and request number", async (t) => {
  globalThis.window = globalThis;
  t.mock.method(globalThis, "fetch", async () => ({ ok: false,
    json: async () => ({ error: { message: "请填写必需指标", request_id: "trace-123" } }) }));
  await assert.rejects(predict("fiber", { species: "softwood", features: {} }, new AbortController().signal),
    (error) => error.message === "请填写必需指标" && error.requestId === "trace-123");
});

test("HTTP 422 without a readable body still gives a visible error message", async (t) => {
  globalThis.window = globalThis;
  t.mock.method(globalThis, "fetch", async () => ({ ok: false, status: 422, json: async () => { throw new Error("Invalid JSON"); } }));
  await assert.rejects(predict("degree", { species: "softwood", degree: 150 }, new AbortController().signal),
    (error) => error.message === "预测失败，请检查输入后重试。");
});

test("canceled predictions abort the network request", async (t) => {
  globalThis.window = globalThis;
  const controller = new AbortController();
  t.mock.method(globalThis, "fetch", async (_, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  }));
  const pending = predict("degree", { species: "softwood", degree: 50 }, controller.signal);
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
});
