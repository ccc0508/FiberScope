<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { Calculator, Download, FlaskConical, TriangleAlert, X } from "lucide-vue-next";
import PageHeader from "../components/PageHeader.vue";
import FilterSelect from "../components/FilterSelect.vue";
import { ApiError, get, number } from "../api";
import { predict, predictionCsv, predictionNumber, validatePredictionInput, type Mode, type Species, type PredictionMetadata, type PredictionResult } from "../prediction";

const metadata = ref<PredictionMetadata | null>(null);
const metadataLoading = ref(true), metadataError = ref("");
const species = ref<Species>("softwood"), mode = ref<Mode>("fiber");
const degree = ref<number | string>("");
const features = ref<Record<string, number | string>>({});
const result = ref<PredictionResult | null>(null);
const busy = ref(false), error = ref("");
const form = ref<HTMLFormElement>();
const attempted = ref(false), toast = ref("");
const model = computed(() => metadata.value?.species.find((item) => item.key === species.value));
const speciesOptions = computed(() => (metadata.value?.species ?? []).map((item) => ({
  value: item.key, label: item.name, marker: item.key,
})));
function chooseSpecies(value: string) {
  const next = metadata.value?.species.find((item) => item.key === value);
  if (next) species.value = next.key;
}
const fieldErrors = computed(() => attempted.value
  ? validatePredictionInput(mode.value, model.value?.features ?? [], degree.value, features.value) : {});
const rangeText = (bounds: [number, number]) => `${bounds[0]}–${bounds[1]}`;
const present = (value: number | string | undefined): value is number =>
  typeof value === "number" && Number.isFinite(value);
const outside = (value: number | string | undefined, range: [number, number]) =>
  present(value) && (value < range[0] || value > range[1]);
const hasOutside = computed(() => model.value && (mode.value === "degree"
  ? outside(degree.value, model.value.degree_range)
  : model.value.features.some((field) => outside(features.value[field.key], field.range))));
let metadataController: AbortController | undefined;
let predictionController: AbortController | undefined;

function invalidate() {
  predictionController?.abort();
  busy.value = false;
  result.value = null;
  error.value = "";
  toast.value = "";
}
watch([mode, species], () => {
  attempted.value = false;
  features.value = {};
  degree.value = "";
}, { flush: "sync" });
watch([mode, species, degree, features], invalidate, { deep: true, flush: "sync" });

async function load() {
  metadataController?.abort();
  const current = new AbortController();
  metadataController = current;
  metadataLoading.value = true;
  metadataError.value = "";
  try {
    const value = await get<PredictionMetadata>("prediction/metadata", {}, current.signal);
    if (!current.signal.aborted) metadata.value = value;
  } catch (e) {
    if (!current.signal.aborted) metadataError.value = e instanceof Error ? e.message : "模型信息读取失败";
  } finally {
    if (!current.signal.aborted) metadataLoading.value = false;
  }
}
function example() {
  if (!model.value) return;
  if (mode.value === "degree") degree.value = model.value.example.degree;
  else features.value = { ...model.value.example.features };
}
async function submit() {
  invalidate();
  if (!model.value) return;
  attempted.value = true;
  const invalid = Object.keys(fieldErrors.value);
  if (invalid.length) {
    showError(invalid.length === 1 ? fieldErrors.value[invalid[0]!]! : `有${invalid.length}项输入需要检查，请查看红框处的说明。`);
    await nextTick();
    const first = form.value?.querySelector<HTMLInputElement>("input[aria-invalid='true']");
    first?.focus();
    first?.reportValidity();
    return;
  }
  const values: Record<string, number> = {};
  if (mode.value === "fiber") {
    for (const field of model.value.features) {
      const value = features.value[field.key];
      if (present(value)) values[field.key] = value;
    }
  }
  const current = new AbortController();
  predictionController = current;
  busy.value = true;
  try {
    const input = mode.value === "degree"
      ? { species: species.value, degree: degree.value as number }
      : { species: species.value, features: values };
    const value = await predict(mode.value, input, current.signal);
    if (!current.signal.aborted) result.value = value;
  } catch (e) {
    if (!current.signal.aborted) showError(e instanceof ApiError && e.requestId
      ? `${e.message}（请求编号：${e.requestId}）` : e instanceof Error ? e.message : "预测失败，请重试。");
  } finally {
    if (!current.signal.aborted) busy.value = false;
  }
}
function showError(message: string) {
  error.value = message;
  toast.value = message;
}
function download() {
  if (!result.value) return;
  const url = URL.createObjectURL(new Blob([predictionCsv(result.value)], { type: "text/csv;charset=utf-8;" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `性能预测_${result.value.species}_${result.value.mode}.csv`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
void load();
onBeforeUnmount(() => { metadataController?.abort(); predictionController?.abort(); });
</script>

<template>
  <div class="overview prediction-page">
    <PageHeader description="用实测纤维指标估算纸张性能，或从打浆度开始探索。" />
    <div v-if="metadataLoading" class="card prediction-message" role="status">正在读取预测模型…</div>
    <div v-else-if="metadataError" class="card prediction-message" role="alert">
      <p>{{ metadataError }}</p><button class="button" @click="load">重新加载模型</button>
    </div>
    <template v-else-if="model && metadata">
      <div class="prediction-workbench">
        <form ref="form" class="card prediction-form" novalidate @submit.prevent="submit">
          <h2>填写预测条件</h2>
          <div class="prediction-modes" role="group" aria-label="预测方式">
            <button type="button" :aria-pressed="mode === 'fiber'" :class="{ selected: mode === 'fiber' }" @click="mode = 'fiber'">实测纤维指标</button>
            <button type="button" :aria-pressed="mode === 'degree'" :class="{ selected: mode === 'degree' }" @click="mode = 'degree'">只有打浆度</button>
          </div>
          <p class="prediction-help">{{ mode === 'fiber' ? '使用已测得的纤维指标直接预测。带 * 的指标为必填，其余可留空。' : '先预测纤维指标，再预测纸张性能；两步误差会叠加，整链结果仅供参考。' }}</p>
          <div class="prediction-field">
            <label for="prediction-species">树种</label>
            <FilterSelect id="prediction-species" label="树种" block :model-value="species" :options="speciesOptions" @update:model-value="chooseSpecies" />
          </div>
          <div class="prediction-input-heading"><span>训练样本 {{ model.sample_count }} 个</span><button type="button" class="text-button" @click="example"><FlaskConical :size="14" /> 填入示例</button></div>
          <div v-if="mode === 'fiber'" class="prediction-field-grid">
            <label v-for="field in model.features" :key="field.key" class="prediction-field" :for="`prediction-${field.key}`">
              <span>{{ field.name }}<span v-if="field.required" aria-hidden="true"> *</span><small v-else>（选填）</small></span>
              <div class="prediction-input" :class="{ outside: outside(features[field.key], field.range), invalid: !!fieldErrors[field.key] }">
                <input :id="`prediction-${field.key}`" v-model.number="features[field.key]" type="number" step="any" min="0" :max="field.unit === '%' ? 100 : field.unit === '°' ? 180 : undefined" :required="field.required" :aria-invalid="!!fieldErrors[field.key]" :aria-describedby="`range-${field.key}${fieldErrors[field.key] ? ` error-${field.key}` : ''}`" />
                <span>{{ field.unit }}</span>
              </div>
              <small :id="`range-${field.key}`" :class="{ 'prediction-outside': outside(features[field.key], field.range) }">训练范围 {{ rangeText(field.range) }}{{ outside(features[field.key], field.range) ? ' · 超出范围' : '' }}</small>
              <small v-if="fieldErrors[field.key]" :id="`error-${field.key}`" class="prediction-field-error">{{ fieldErrors[field.key] }}</small>
            </label>
          </div>
          <label v-else class="prediction-field" for="prediction-degree">
            <span>打浆度 *</span>
            <div class="prediction-input" :class="{ outside: outside(degree, model.degree_range), invalid: !!fieldErrors.degree }"><input id="prediction-degree" v-model.number="degree" type="number" step="any" min="0" max="100" required :aria-invalid="!!fieldErrors.degree" :aria-describedby="`prediction-degree-range${fieldErrors.degree ? ' error-degree' : ''}`" /><span>°SR</span></div>
            <small id="prediction-degree-range">训练范围 {{ rangeText(model.degree_range) }} °SR；这里填写打浆度，不是打浆转数。</small>
            <small v-if="fieldErrors.degree" id="error-degree" class="prediction-field-error">{{ fieldErrors.degree }}</small>
          </label>
          <p v-if="hasOutside" class="prediction-outside" role="status">输入超出训练范围，相关结果将标为外推参考。</p>
          <p v-if="error" class="prediction-error">{{ error }}</p>
          <button class="button primary prediction-submit" type="submit" :disabled="busy"><Calculator :size="16" />{{ busy ? '正在预测…' : '开始预测' }}</button>
          <p class="prediction-help">预测计算不修改实验数据。</p>
        </form>

        <section class="prediction-results" aria-labelledby="prediction-results-title" :aria-busy="busy">
          <div class="prediction-result-heading"><div><h2 id="prediction-results-title">纸张性能预测</h2><p>{{ result ? `${result.species_name} · ${result.mode === 'degree' ? `打浆度 ${result.input.degree} °SR` : '实测纤维指标'}` : '9项性能，分别展示模型适用性' }}</p></div><button v-if="result" class="button" @click="download"><Download :size="15" /> 导出结果</button></div>
          <div v-if="!result" class="card prediction-empty" role="status">
            <Calculator :size="34" /><h3>{{ busy ? '正在计算预测结果' : error ? '本次预测未完成' : '从左侧填写一组条件' }}</h3>
            <p>{{ error || '可以先填入示例了解预测结果。结果会同时保留可靠性和超出训练范围的提示。' }}</p>
          </div>
          <template v-else>
            <div v-if="result.warnings.length" class="prediction-notice" role="status"><TriangleAlert :size="18" /><ul><li v-for="warning in result.warnings" :key="warning">{{ warning }}</li></ul></div>
            <div class="prediction-paper-grid">
              <article v-for="item in result.paper" :key="item.key" class="card prediction-paper" :class="{ reference: item.reference_only }">
                <div class="prediction-paper-title"><h3>{{ item.name }}</h3><span class="prediction-status" :class="{ usable: !item.reference_only }">{{ item.status }}</span></div>
                <p class="prediction-reading">{{ predictionNumber(item.value) }}<small>{{ item.unit ?? '单位未确认' }}{{ item.unit_status === 'tentative' ? '（暂定）' : '' }}</small></p>
                <p v-if="Math.abs(item.value) >= 1e9" class="prediction-result-note prediction-outside">结果数量级很大，已用科学记数法显示；请核对输入和单位，外推结果不宜用于定量判断。</p>
                <p class="prediction-score">实测纤维模型 R² <strong>{{ number(item.nested_r2, 2) }}</strong></p>
                <p v-for="note in item.notes" :key="note" class="prediction-result-note">{{ note }}</p>
              </article>
            </div>
            <p class="prediction-help prediction-score-help">R²为实测纤维→纸张模型的嵌套交叉验证值，不是准确率，也不是本次预测的置信度。低于0.4标为仅供参考；负值表示该验证下表现差于用均值预测。</p>
            <details v-if="result.fiber.length" class="card prediction-fibers" open>
              <summary>中间结果：打浆度预测的12项纤维指标</summary>
              <div class="prediction-table-wrap"><table><thead><tr><th scope="col">纤维指标</th><th scope="col">预测值</th><th scope="col">单步R²</th><th scope="col">适用性</th></tr></thead><tbody><tr v-for="item in result.fiber" :key="item.key"><th scope="row">{{ item.name }}</th><td>{{ predictionNumber(item.value, 4) }} {{ item.unit }}</td><td>{{ number(item.cv_r2, 2) }}</td><td>{{ !item.in_range ? '外推参考' : item.model_reliable ? '单步可参考' : '可靠性不足' }}</td></tr></tbody></table></div>
            </details>
            <p class="prediction-help">模型版本 {{ result.model_version }} · 训练样本 {{ result.sample_count }} 个</p>
          </template>
        </section>
      </div>
      <details class="card prediction-limitations"><summary>模型适用范围与使用说明</summary><ul><li v-for="note in metadata.notes" :key="note">{{ note }}</li></ul></details>
    </template>
    <div v-if="toast" class="prediction-toast" role="alert" aria-live="assertive" aria-atomic="true">
      <TriangleAlert :size="20" /><p>{{ toast }}</p><button type="button" class="icon-button" aria-label="关闭错误提示" @click="toast = ''"><X :size="18" /></button>
    </div>
  </div>
</template>

<style scoped>
.prediction-workbench { display: grid; grid-template-columns: minmax(310px, 380px) minmax(0, 1fr); gap: 24px; align-items: start; }
.prediction-form { padding: 24px; display: grid; gap: 18px; }
.prediction-modes { display: flex; border: 1px solid var(--border-strong); padding: 3px; gap: 3px; }
.prediction-modes button { flex: 1; padding: 10px 6px; font-size: 13px; }
.prediction-modes .selected { background: var(--accent); color: var(--accent-contrast); }
.prediction-help { color: var(--muted); font-size: 12px; line-height: 1.8; }
.prediction-field { display: grid; gap: 6px; min-width: 0; font-size: 13px; }
.prediction-field small { font-size: 11px; color: var(--muted); }
.prediction-input { background: var(--paper); border: 1px solid var(--border-strong); border-radius: var(--radius); min-height: 40px; }
.prediction-field > label { width: fit-content; cursor: pointer; }
.prediction-input { display: flex; align-items: center; padding-right: 9px; }
.prediction-input input { width: 100%; min-width: 0; border: 0; background: transparent; padding: 10px; color: var(--ink); font-variant-numeric: tabular-nums; }
.prediction-input > span { flex-shrink: 0; color: var(--muted); font-size: 12px; }
.prediction-input.outside { border-color: var(--warn); }
.prediction-input.invalid { border: 2px solid var(--bad); background: var(--bad-tint); }
.prediction-field small.prediction-field-error { color: var(--bad); line-height: 1.7; }
.prediction-toast { position: fixed; bottom: calc(var(--chrome-bottom) + 16px); right: 16px; z-index: 60; width: min(440px, calc(100vw - 32px)); display: flex; align-items: flex-start; gap: 10px; padding: 16px; background: var(--surface); color: var(--bad); border: 1px solid var(--bad); box-shadow: var(--shadow-sm); font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.prediction-toast p { flex: 1; }
.prediction-toast .icon-button { flex-shrink: 0; }
.prediction-field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 14px; }
.prediction-input-heading { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; color: var(--muted); align-items: center; }
.prediction-submit { width: 100%; justify-content: center; }
.prediction-error { color: var(--bad); font-size: 13px; }
.prediction-outside, .prediction-field small.prediction-outside { color: var(--warn); font-size: 12px; }
.prediction-results { min-width: 0; }
.prediction-result-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 4px 0 20px; }
.prediction-result-heading p { color: var(--muted); font-size: 12px; margin-top: 7px; }
.prediction-empty { min-height: 360px; padding: 50px 28px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: 18px; }
.prediction-empty svg { color: var(--signal); }
.prediction-empty p { max-width: 300px; color: var(--muted); line-height: 1.9; font-size: 13px; }
.prediction-paper-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.prediction-paper { padding: 18px; border-top: 3px solid var(--signal); }
.prediction-paper.reference { border-top-color: var(--border-strong); }
.prediction-paper-title { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.prediction-status { font-size: 11px; color: var(--muted); background: var(--canvas); padding: 3px 6px; }
.prediction-status.usable { background: var(--signal-tint); color: var(--signal-ink); }
.prediction-reading { font-family: var(--font-mono); font-size: 27px; margin: 18px 0 12px; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.prediction-reading small { display: block; font: 12px var(--font-body); color: var(--muted); margin-top: 4px; }
.prediction-score { border-top: 1px solid var(--border); padding-top: 10px; font-size: 11px; color: var(--muted); }
.prediction-score strong { color: var(--ink-2); font-family: var(--font-mono); margin-left: 4px; }
.prediction-result-note { font-size: 11px; margin-top: 8px; color: var(--muted); line-height: 1.7; }
.prediction-score-help { margin: 16px 0; }
.prediction-notice { display: flex; align-items: flex-start; gap: 10px; background: var(--warn-tint); border: 1px solid var(--line-strong); padding: 14px; margin-bottom: 16px; color: var(--warn); font-size: 12px; line-height: 1.8; }
.prediction-notice ul { margin: 0; padding-left: 17px; }
.prediction-fibers { margin: 18px 0; }
.prediction-fibers summary, .prediction-limitations summary { padding: 16px 18px; cursor: pointer; font-weight: 500; }
.prediction-table-wrap { overflow-x: auto; }
.prediction-fibers table { width: 100%; border-collapse: collapse; font-size: 12px; text-align: left; }
.prediction-fibers th, .prediction-fibers td { padding: 11px 14px; border-top: 1px solid var(--border); white-space: nowrap; font-weight: 400; }
.prediction-fibers thead { background: var(--canvas); }
.prediction-fibers tbody th { position: static; }
.prediction-limitations { margin-top: 24px; }
.prediction-limitations ul { padding: 0 34px 18px; margin: 0; color: var(--muted); line-height: 1.9; font-size: 13px; }
.prediction-message { padding: 28px; }
.prediction-message .button { margin-top: 16px; }
@media (min-width: 1500px) { .prediction-paper-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 1100px) { .prediction-workbench { grid-template-columns: minmax(0, 1fr); } .prediction-field-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 600px) { .prediction-form { padding: 18px; } .prediction-field-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .prediction-paper-grid { grid-template-columns: minmax(0, 1fr); } .prediction-result-heading { flex-wrap: wrap; } .prediction-empty { min-height: 260px; } }
</style>
