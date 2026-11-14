<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileSpreadsheet,
  RefreshCw,
  Search,
  TriangleAlert,
  X,
} from "lucide-vue-next";
import {
  get,
  number,
  typeKeys,
  typeNames,
  type ListResult,
  type Metadata,
  type SampleType,
} from "../api";
import {
  groupSources,
  matchesSource,
  provenance,
  sourceKind,
  sourceTargets,
  usageLabel,
  type MaterialCounts,
  type SourceKind,
  type SourceObservation,
  type SourceRow,
  type SourceUsage,
} from "../sources";
import FilterSelect from "../components/FilterSelect.vue";
import PageHeader from "../components/PageHeader.vue";
import { isGarden, reducedMotion } from "../mode";
import { vSeg, vTilt } from "../motion";

const PAGE_SIZE = 25;
const route = useRoute(),
  router = useRouter();
const metadata = ref<Metadata | null>(null),
  rows = ref<SourceRow[]>([]),
  loading = ref(true),
  error = ref("");
const selected = ref<SourceRow | null>(null),
  dialog = ref<HTMLDialogElement>(),
  records = ref<HTMLElement>(),
  whyInner = ref<HTMLElement>();
const query = computed(() =>
  typeof route.query.q === "string" ? route.query.q.slice(0, 150) : "",
);
const search = ref(query.value);
const file = computed(() =>
  typeof route.query.file === "string" ? route.query.file : "",
);
const scope = computed(() =>
  ["core", "recycled"].includes(String(route.query.scope))
    ? String(route.query.scope)
    : "",
);

/* ---------------------------------------------------------------- files */
const fileSummary = computed(() => {
  const files = new Map<
    string,
    {
      name: string;
      sheets: Set<string>;
      count: number;
      samples: Set<string>;
      blocks: Set<string>;
      rows: SourceRow[];
    }
  >();
  for (const r of rows.value) {
    let f = files.get(r.file_name);
    if (!f) {
      f = {
        name: r.file_name,
        sheets: new Set(),
        count: 0,
        samples: new Set(),
        blocks: new Set(),
        rows: [],
      };
      files.set(r.file_name, f);
    }
    f.sheets.add(r.sheet_name);
    f.count++;
    f.rows.push(r);
    r.usages.forEach((u) => {
      if (u.canonical_code) f!.samples.add(u.canonical_code);
    });
    r.observations.forEach((o) => f!.blocks.add(o.block_code));
  }
  const list = [...files.values()];
  const max = Math.max(1, ...list.map((f) => f.count));
  return list.map((f, i) => ({
    name: f.name,
    sheets: [...f.sheets].join("、"),
    count: f.count,
    links: f.samples.size
      ? `${f.samples.size} 个关联样本`
      : `${f.blocks.size} 个数据块`,
    index: `S${String(i + 1).padStart(2, "0")}`,
    kind: sourceKind(f.rows),
    /* polarized specimen disc (area ∝ rows) and garden bar (length ∝ rows) */
    disc: Math.sqrt(f.count / max).toFixed(3),
    share: `${((f.count / max) * 100).toFixed(1)}%`,
  }));
});

/* ---------------------------------------------------------------- records */
const matching = computed(() =>
  rows.value.filter(
    (r) =>
      (!file.value || r.file_name === file.value) &&
      matchesSource(r, query.value),
  ),
);
const scopeCounts = computed(() => ({
  "": matching.value.length,
  core: matching.value.filter((r) => r.usages.length).length,
  recycled: matching.value.filter((r) => r.observations.length).length,
}));
const scopes = [
  { value: "", label: "全部数据" },
  { value: "core", label: "核心实验" },
  { value: "recycled", label: "再生纸浆" },
] as const;
const filtered = computed(() =>
  matching.value.filter(
    (r) =>
      !scope.value ||
      (scope.value === "core" ? r.usages.length : r.observations.length),
  ),
);
const pages = computed(() =>
  Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)),
);
const page = computed(() => {
  const n = Number(route.query.page);
  return Number.isInteger(n) && n > 0 ? Math.min(n, pages.value) : 1;
});
const visible = computed(() =>
  filtered.value
    .slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE)
    .map((r) => ({ row: r, targets: sourceTargets(r), uses: usages(r) })),
);
const coreSources = computed(
  () => rows.value.filter((r) => r.usages.length).length,
);
const recycledSources = computed(
  () => rows.value.filter((r) => r.observations.length).length,
);
const usages = (r: SourceRow) =>
  [
    ...new Set(r.usages.map(usageLabel)),
    ...(r.observations.length ? ["循环原始观测"] : []),
  ].join("、");

/* ---------------------------------------------------------------- counts (这些数量为什么不同) */
const counts = computed(() => metadata.value?.counts ?? {});
const fmt = (value: number | null | undefined) => number(value ?? null);
const displayPoints = computed(() =>
  counts.value.beating != null && counts.value.blends != null
    ? counts.value.beating + counts.value.blends
    : null,
);
const prov = computed(() => provenance(rows.value));
const sum = (c: MaterialCounts) => c.softwood + c.hardwood + c.blend;
const reusedEnds = computed(
  () => prov.value.blend.softwood + prov.value.blend.hardwood,
);
const dotCount = computed(() =>
  Math.min(240, Math.max(0, counts.value["recycled/cycles"] ?? 0)),
);
const sumHolds = computed(
  () => coreSources.value + recycledSources.value === rows.value.length,
);

/* flow (garden): unique samples per material → experiment display points */
const curve = (x1: number, y1: number, x2: number, y2: number) =>
  `M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`;
const flow = computed(() => {
  const p = prov.value;
  const groups = [
    { key: "beating" as const, y: 27, n: sum(p.beating), label: "打浆展示点" },
    { key: "blend" as const, y: 73, n: sum(p.blend), label: "复配展示点" },
  ];
  const left = typeKeys.map((t, i) => ({
    type: t,
    y: i * 46,
    n: p.samples[t],
    label: typeNames[t],
  }));
  const max = Math.max(
    1,
    ...groups.flatMap((g) => typeKeys.map((t) => p[g.key][t])),
  );
  const links = left
    .flatMap((l) =>
      groups.map((g) => {
        const n = p[g.key][l.type];
        const native = (g.key === "blend") === (l.type === "blend");
        return {
          key: `${l.type}-${g.key}`,
          n,
          native,
          type: l.type,
          d: curve(118, l.y + 19, 196, g.y + 19),
          w: (1.2 + (n / max) * 4.6).toFixed(2),
        };
      }),
    )
    .filter((l) => l.n > 0)
    .sort((a, b) => Number(a.native) - Number(b.native));
  return { left, groups, links };
});
const flowLabel = computed(() => {
  const p = prov.value;
  return (
    typeKeys.map((t) => `${typeNames[t]} ${p.samples[t]}`).join("、") +
    ` 个唯一样本，合计 ${sum(p.samples)} 个；打浆展示点 ${sum(p.beating)}、复配展示点 ${sum(p.blend)}，` +
    `合计 ${sum(p.beating) + sum(p.blend)} 个，含 ${reusedEnds.value} 个复用纯浆端点；` +
    `${fmt(counts.value["recycled/details"])} 条原始观测汇总为 ${fmt(counts.value["recycled/cycles"])} 个循环点，` +
    `${metadata.value?.blocks.length ?? "—"} 个数据块`
  );
});

/* hero signature (garden): source rows → core / recycled → samples, points, cycles */
const sig = computed(() => {
  if (!metadata.value) return null;
  const tot = rows.value.length;
  const width = (n: number) =>
    (tot ? Math.max(1.5, (n / tot) * 26) : 1.5).toFixed(1);
  return {
    tot: fmt(tot),
    core: fmt(coreSources.value),
    rec: fmt(recycledSources.value),
    wCore: width(coreSources.value),
    wRec: width(recycledSources.value),
    samples: fmt(counts.value.samples),
    points: fmt(displayPoints.value),
    cycles: fmt(counts.value["recycled/cycles"]),
  };
});
/* label x after a mono number in a signature node */
const after = (x: number, n: string) => x + 11 + n.length * 7.6 + 5;

/* ---------------------------------------------------------------- detail drawer */
const relatedIndicators = computed(
  () =>
    metadata.value?.indicators.filter(
      (i) =>
        i.scope.includes("core") &&
        selected.value?.usages.some(
          (u) =>
            (u.usage_type === "fiber_measurement" && i.group === "fiber") ||
            (u.usage_type === "paper_measurement" && i.group === "paper"),
        ),
    ) ?? [],
);
const recycledIndicators = computed(
  () =>
    metadata.value?.indicators.filter((i) => i.scope.includes("recycled")) ??
    [],
);
const kindOf = (type: SampleType | null | undefined): SourceKind =>
  type ?? "other";

/* ---------------------------------------------------------------- url state */
function update(key: string, value: string) {
  router.replace({
    query: { ...route.query, [key]: value || undefined, page: undefined },
  });
}
function goPage(value: number) {
  router.replace({
    query: { ...route.query, page: value === 1 ? undefined : String(value) },
  });
}
function reset() {
  search.value = "";
  router.replace({ query: {} });
}
/* a pointer click on a file card filters the records and brings them into view
   (v1); keyboard activation (detail 0) keeps the reader where the focus is */
async function chooseFile(name: string, event: MouseEvent) {
  const next = file.value === name ? "" : name;
  update("file", next);
  if (!next || event.detail === 0) return;
  await nextTick();
  const el = records.value;
  if (el && el.getBoundingClientRect().top > window.innerHeight * 0.62)
    el.scrollIntoView({
      behavior: reducedMotion.value ? "auto" : "smooth",
      block: "start",
    });
}
function close() {
  dialog.value?.close();
  selected.value = null;
}
async function show(row: SourceRow) {
  selected.value = row;
  await nextTick();
  dialog.value?.showModal();
}
watch(
  () => route.fullPath,
  () => {
    search.value = query.value;
    close();
  },
);

/* garden: the count tile's content follows the reader down the records (sticky inside
   its stretched tile); a panel taller than the viewport scrolls until its end is in view */
let whyObserver: ResizeObserver | undefined;
watch(whyInner, (el) => {
  whyObserver?.disconnect();
  if (!el) return;
  whyObserver = new ResizeObserver(([entry]) => {
    if (entry) el.style.setProperty("--why-h", `${Math.ceil(entry.borderBoxSize?.[0]?.blockSize ?? el.offsetHeight)}px`);
  });
  whyObserver.observe(el);
});

/* ---------------------------------------------------------------- loading */
let controller: AbortController | undefined;
async function all<T>(path: string, signal: AbortSignal) {
  const first = await get<ListResult<T>>(path, { page_size: 500 }, signal);
  const data = [...first.data];
  for (let p = 2; p <= first.pagination.total_pages; p++)
    data.push(
      ...(await get<ListResult<T>>(path, { page_size: 500, page: p }, signal))
        .data,
    );
  return data;
}
async function load() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = "";
  close();
  try {
    const [m, u, o] = await Promise.all([
      get<Metadata>("metadata", {}, current.signal),
      all<SourceUsage>("lineage", current.signal),
      all<SourceObservation>("recycled/details", current.signal),
    ]);
    if (current.signal.aborted) return;
    metadata.value = m;
    rows.value = groupSources(u, o);
  } catch (e) {
    if (!current.signal.aborted)
      error.value = e instanceof Error ? e.message : "来源读取失败。";
  } finally {
    if (!current.signal.aborted) loading.value = false;
  }
}
onBeforeUnmount(() => {
  controller?.abort();
  whyObserver?.disconnect();
});
load();
</script>

<template>
  <div class="sources-page overview">
    <PageHeader description="从分析结果回到原始记录，了解每一行数据的用途。">
      <template #actions>
        <span class="connection" :class="{ offline: !!error }" role="status"
          ><span></span
          >{{ loading ? "正在读取" : error ? "连接待检查" : "数据已连接" }}</span
        ><button class="button" :disabled="loading" @click="load">
          <RefreshCw :size="15" :class="{ spinning: loading }" />刷新数据
        </button>
      </template>
      <template v-if="isGarden" #visual>
        <figure class="src-sig">
          <svg
            v-if="sig"
            viewBox="0 0 420 132"
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
            focusable="false"
          >
            <path class="sig-link core" :d="curve(96, 66, 150, 30)" :stroke-width="sig.wCore" />
            <path class="sig-link rec" :d="curve(96, 66, 150, 102)" :stroke-width="sig.wRec" />
            <path class="sig-link core" :d="curve(262, 30, 292, 30)" stroke-width="6" />
            <path class="sig-link rec" :d="curve(262, 102, 292, 102)" stroke-width="5" />
            <g>
              <rect class="sig-node" x="0" y="49" width="96" height="34" rx="13" />
              <text class="sig-v" x="11" y="71">{{ sig.tot }}</text>
              <text class="sig-t" :x="after(0, sig.tot)" y="71">来源行</text>
            </g>
            <g>
              <rect class="sig-node tint" x="150" y="13" width="112" height="34" rx="13" />
              <text class="sig-v" x="161" y="35">{{ sig.core }}</text>
              <text class="sig-t" :x="after(150, sig.core)" y="35">核心来源</text>
            </g>
            <g>
              <rect class="sig-node tint" x="150" y="85" width="112" height="34" rx="13" />
              <text class="sig-v" x="161" y="107">{{ sig.rec }}</text>
              <text class="sig-t" :x="after(150, sig.rec)" y="107">再生观测</text>
            </g>
            <g>
              <rect class="sig-node" x="292" y="2" width="128" height="56" rx="15" />
              <text class="sig-v" x="303" y="25">{{ sig.samples }}</text>
              <text class="sig-t" :x="after(292, sig.samples)" y="25">唯一样本</text>
              <text class="sig-v" x="303" y="47">{{ sig.points }}</text>
              <text class="sig-t" :x="after(292, sig.points)" y="47">实验展示点</text>
            </g>
            <g>
              <rect class="sig-node" x="292" y="85" width="128" height="34" rx="13" />
              <text class="sig-v" x="303" y="107">{{ sig.cycles }}</text>
              <text class="sig-t" :x="after(292, sig.cycles)" y="107">循环汇总点</text>
            </g>
          </svg>
          <div v-else class="src-sig-empty skeleton" aria-hidden="true"></div>
          <figcaption>
            <span class="nw"><b>{{ loading || error ? "—" : fileSummary.length }}</b> 个文件 ·</span> 同一行可服务多个用途，所以四个数字口径不同
          </figcaption>
        </figure>
      </template>
    </PageHeader>

    <p v-if="loading" class="card source-state" role="status">
      正在读取来源记录…
    </p>
    <div v-else-if="error" class="card source-state" role="alert">
      <TriangleAlert :size="24" />
      <p>{{ error }}</p>
      <button class="button" @click="load">重新加载</button>
    </div>
    <template v-else>
      <!-- 来源文件：偏光为玻片（编号 + 标本圆 + 名称），花园为染色小砖（图标 + 名称 + 行数条） -->
      <details class="card src-files" open>
        <summary>
          <span class="src-files-title">已入库来源文件</span>
          <span class="count-badge"><span class="nw">{{ fileSummary.length }} 个文件 ·</span> <span class="nw">{{ rows.length }} 条来源行</span></span>
          <ChevronDown class="src-files-chevron" :size="18" aria-hidden="true" />
        </summary>
        <p class="src-note">
          <span class="nw">{{ coreSources }} 条核心实验来源行 +</span> <span class="nw">{{ recycledSources }} 条再生纸浆观测。</span>仅统计已入库的来源，不代表 Excel 的全部行。点击文件筛选下方记录。
        </p>
        <ul class="src-file-grid">
          <li v-for="f in fileSummary" :key="f.name">
            <button
              v-tilt
              type="button"
              class="src-file"
              :class="`k-${f.kind}`"
              :aria-pressed="file === f.name"
              :style="{ '--disc': f.disc, '--share': f.share }"
              @click="chooseFile(f.name, $event)"
            >
              <span class="src-file-label" aria-hidden="true"
                ><span>{{ f.index }}</span><span>{{ f.count }}</span></span
              >
              <span class="src-file-spec" aria-hidden="true"><i></i></span>
              <span class="src-file-icon" aria-hidden="true"
                ><FileSpreadsheet :size="19"
              /></span>
              <span class="src-file-body">
                <strong class="src-file-name">{{ f.name }}</strong>
                <span class="src-file-meta">
                  <span class="nw"
                    >{{ f.sheets }} · <b>{{ f.count }}</b> 条来源行</span
                  >
                  <span class="src-file-links"
                    ><i class="src-mk" aria-hidden="true"></i>{{ f.links }}</span
                  >
                </span>
              </span>
              <span class="src-file-bar" aria-hidden="true"><i></i></span>
            </button>
          </li>
        </ul>
      </details>

      <section
        ref="records"
        class="card src-records"
        aria-labelledby="source-list-title"
      >
        <div class="src-head">
          <div class="src-title-row">
            <h2 id="source-list-title">来源记录</h2>
            <span class="count-badge" aria-live="polite"
              >{{ filtered.length }} 条来源行</span
            >
          </div>
          <p class="src-note">
            同一文件、工作表、版本和源行合并展示，用途在详情中展开。
          </p>
        </div>
        <div class="src-toolbar">
          <div class="src-file-filter">
            <FilterSelect
              id="source-file"
              :model-value="file"
              :options="[
                { value: '', label: '全部来源文件' },
                ...fileSummary.map((f) => ({
                  value: f.name,
                  label: f.name,
                  count: f.count,
                })),
              ]"
              label="筛选来源文件"
              @update:model-value="update('file', $event)"
            />
          </div>
          <div v-seg class="seg src-scope" role="group" aria-label="筛选数据范围">
            <button
              v-for="s in scopes"
              :key="s.value"
              type="button"
              :aria-pressed="scope === s.value"
              @click="update('scope', s.value)"
            >
              {{ s.label }}<span class="cnt">{{ scopeCounts[s.value] }}</span>
            </button>
          </div>
          <form
            class="src-search"
            role="search"
            @submit.prevent="update('q', search.trim())"
          >
            <label class="search-field"
              ><Search :size="16" aria-hidden="true" /><input
                v-model="search"
                aria-label="搜索来源"
                placeholder="样本编号、G01、文件名或源行"
                maxlength="150"
            /></label>
            <button class="button" type="submit">搜索</button>
          </form>
          <button
            v-if="file || scope || query"
            type="button"
            class="text-button src-clear"
            @click="reset"
          >
            清除筛选
          </button>
        </div>
        <p v-if="query" class="src-query">
          <span class="src-query-k">搜索：</span>{{ query }}
        </p>
        <div class="table-scroll src-table-scroll">
          <table class="sources-table">
            <thead>
              <tr>
                <th scope="col">Excel 来源</th>
                <th scope="col">关联样本 / 数据块</th>
                <th scope="col">用途</th>
                <th scope="col" class="src-col-act">查看</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="v in visible" :key="v.row.key">
                <td class="src-cell-file">
                  <strong>{{ v.row.file_name }}</strong
                  ><small
                    >{{ v.row.sheet_name }} · 第 {{ v.row.source_row }} 行 ·
                    {{ v.row.source_version }}</small
                  >
                </td>
                <td class="src-cell-target" data-l="关联样本 / 数据块">
                  <span v-if="v.targets.length" class="src-targets"
                    ><template v-for="(t, i) in v.targets" :key="t.label"
                      ><span v-if="i" class="sr-only">、</span
                      ><span class="src-target" :class="`k-${t.kind}`"
                        ><i class="src-mk" aria-hidden="true"></i
                        >{{ t.label }}</span
                      ></template
                    ></span
                  >
                  <span v-else class="src-none">未关联样本</span>
                </td>
                <td class="src-cell-use" data-l="用途">{{ v.uses }}</td>
                <td class="src-cell-act">
                  <button
                    type="button"
                    class="src-view"
                    :aria-label="`查看${v.row.file_name}第${v.row.source_row}行的用途`"
                    @click="show(v.row)"
                  >
                    查看用途
                  </button>
                </td>
              </tr>
              <tr v-if="!visible.length" class="src-empty-row">
                <td colspan="4">
                  <div class="source-state">
                    <span>没有匹配的来源记录。</span>
                    <button type="button" class="text-button" @click="reset">
                      清除筛选
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="src-foot">
          <span><span class="nw">每页 {{ PAGE_SIZE }} 行 ·</span> <span class="nw">第 {{ page }} / {{ pages }} 页</span></span>
          <div class="src-pager">
            <button
              class="icon-button"
              aria-label="上一页"
              :disabled="page <= 1"
              @click="goPage(page - 1)"
            >
              <ChevronLeft :size="18" />
            </button>
            <span class="src-pager-n" aria-hidden="true"
              >{{ page }}<span> / {{ pages }}</span></span
            >
            <button
              class="icon-button"
              aria-label="下一页"
              :disabled="page >= pages"
              @click="goPage(page + 1)"
            >
              <ChevronRight :size="18" />
            </button>
          </div>
        </div>
      </section>

      <section class="card src-why" aria-labelledby="count-title">
        <div ref="whyInner" class="src-why-inner">
          <div class="src-why-head">
            <p class="eyebrow src-why-eyebrow" aria-hidden="true">
              Why the numbers differ
            </p>
            <h2 id="count-title">这些数量为什么不同？</h2>
            <span class="src-why-kicker" aria-hidden="true"
              >Four apertures, four counts</span
            >
          </div>

          <!-- 花园：唯一样本 → 实验展示点的流向（数据来自来源用途） -->
          <figure class="src-flow">
            <svg viewBox="0 0 340 214" role="img" :aria-label="flowLabel">
              <path
                v-for="l in flow.links"
                :key="l.key"
                class="flow-link"
                :class="l.native ? `k-${l.type}` : 'reuse'"
                :d="l.d"
                :stroke-width="l.w"
              />
              <g v-for="l in flow.left" :key="l.type" :class="`k-${l.type}`">
                <rect class="flow-node tint" x="4" :y="l.y" width="114" height="38" rx="14" />
                <text x="16" :y="l.y + 24"><tspan class="mono">{{ l.n }}</tspan> {{ l.label }}</text>
              </g>
              <g v-for="g in flow.groups" :key="g.key">
                <rect class="flow-node" x="196" :y="g.y" width="140" height="38" rx="14" />
                <text x="208" :y="g.y + 24"><tspan class="mono">{{ g.n }}</tspan> {{ g.label }}</text>
              </g>
              <text class="flow-cap" x="4" y="156">↑ 合计 {{ sum(prov.samples) }} 个唯一样本</text>
              <text class="flow-cap" x="196" y="132">合计 {{ sum(prov.beating) + sum(prov.blend) }} 个展示点</text>
              <text class="flow-cap" x="196" y="148">（含 {{ reusedEnds }} 个复用纯浆端点）</text>
              <path class="flow-link rc" :d="curve(118, 189, 196, 189)" stroke-width="2.4" />
              <g class="k-recycled">
                <rect class="flow-node tint" x="4" y="170" width="114" height="38" rx="14" />
                <text x="16" y="194"><tspan class="mono">{{ fmt(counts["recycled/details"]) }}</tspan> 原始观测</text>
                <rect class="flow-node tint" x="196" y="170" width="140" height="38" rx="14" />
                <text x="208" y="194"><tspan class="mono">{{ fmt(counts["recycled/cycles"]) }}</tspan> 循环点 · {{ metadata?.blocks.length ?? "—" }} 块</text>
              </g>
            </svg>
          </figure>

          <div class="src-why-grid">
            <div class="src-why-item">
              <span class="src-why-n">{{ fmt(counts.samples) }}</span>
              <div class="src-why-text">
                <b>个核心样本</b>
                <p>去重后的物理样本，同一个样本可以出现在不同实验中。</p>
              </div>
              <div class="src-stack" aria-hidden="true">
                <i
                  v-for="t in typeKeys"
                  :key="t"
                  :class="`k-${t}`"
                  :style="{ flexGrow: prov.samples[t] }"
                ></i>
              </div>
              <p class="src-stack-l">
                <template v-for="(t, i) in typeKeys" :key="t"><span class="nw">{{ typeNames[t] }} {{ prov.samples[t] }}{{ i < typeKeys.length - 1 ? " +" : "" }}</span>{{ i < typeKeys.length - 1 ? " " : "" }}</template>
              </p>
            </div>
            <div class="src-why-item">
              <span class="src-why-n">{{ fmt(displayPoints) }}</span>
              <div class="src-why-text">
                <b>个实验展示点</b>
                <p>
                  打浆实验 {{ fmt(counts.beating) }} 个，加复配实验
                  {{ fmt(counts.blends) }} 个。复配两端复用纯浆样本。
                </p>
              </div>
              <div class="src-stack" aria-hidden="true">
                <i class="beat" :style="{ flexGrow: counts.beating ?? 0 }"></i
                ><i class="k-blend" :style="{ flexGrow: counts.blends ?? 0 }"></i>
              </div>
              <p class="src-stack-l">
                <span class="nw">打浆 {{ fmt(counts.beating) }} +</span> <span class="nw">复配 {{ fmt(counts.blends) }}</span><span class="nw">（含 {{ reusedEnds }} 个复用端点）</span>
              </p>
            </div>
            <div class="src-why-item">
              <span class="src-why-n">{{ fmt(counts["recycled/details"]) }}</span>
              <div class="src-why-text">
                <b>条原始观测</b>
                <p>
                  再生纸浆逐行测量记录，独立于核心样本；同一循环可有多次重复观测。
                </p>
              </div>
              <div class="src-stack" aria-hidden="true">
                <i class="k-recycled" :style="{ flexGrow: 1 }"></i>
              </div>
              <p class="src-stack-l">
                <span class="nw">{{ metadata?.blocks.length ?? "—" }} 个数据块 ·</span> <span class="nw">逐行</span>
              </p>
            </div>
            <div class="src-why-item">
              <span class="src-why-n">{{ fmt(counts["recycled/cycles"]) }}</span>
              <div class="src-why-text">
                <b>个循环汇总点</b>
                <p>
                  {{ metadata?.blocks.length ?? "—" }}
                  个数据块按循环次数分别汇总。每项指标取该组非空观测的平均值。
                </p>
              </div>
              <div class="src-stack dots" aria-hidden="true">
                <i v-for="n in dotCount" :key="n"></i>
              </div>
              <p class="src-stack-l">
                <span class="nw"
                  >{{ fmt(counts["recycled/details"]) }} →
                  {{ fmt(counts["recycled/cycles"]) }}</span
                >
              </p>
            </div>
          </div>
          <p class="src-why-sum">
            <span class="nw">{{ rows.length }} 条来源行</span>
            <span class="op">{{ sumHolds ? "=" : "·" }}</span>
            <span class="nw">{{ coreSources }} 核心实验</span>
            <span class="op">{{ sumHolds ? "+" : "·" }}</span>
            <span class="nw">{{ recycledSources }} 再生纸浆观测</span>
          </p>
          <p class="caveat src-why-note">
            来源行数、用途数量与样本数是不同口径。同一行同时用于实验展示、纤维测量和原料组分时，只算一条来源行。
          </p>
        </div>
      </section>
    </template>

    <dialog
      ref="dialog"
      class="source-dialog detail-drawer"
      aria-labelledby="source-detail-title"
      @close="selected = null"
      @click="$event.target === dialog && close()"
    >
      <div v-if="selected" class="drawer-content">
        <div class="dialog-heading">
          <div>
            <span class="eyebrow">原始记录的对应关系</span>
            <h2 id="source-detail-title">{{ selected.file_name }}</h2>
          </div>
          <button class="icon-button" aria-label="关闭来源详情" @click="close">
            <X :size="20" />
          </button>
        </div>
        <dl class="src-coords">
          <div>
            <dt>工作表</dt>
            <dd>{{ selected.sheet_name }}</dd>
          </div>
          <div>
            <dt>源行</dt>
            <dd>第 {{ selected.source_row }} 行</dd>
          </div>
          <div>
            <dt>版本</dt>
            <dd>{{ selected.source_version }}</dd>
          </div>
        </dl>
        <template v-if="selected.usages.length">
          <p class="src-dialog-note">
            这是一条来源行，以下为它在数据库中记录的
            {{ selected.usages.length }} 项用途。
          </p>
          <ul class="usage-list">
            <li v-for="(u, index) in selected.usages" :key="index">
              <strong>{{ usageLabel(u) }}</strong>
              <span v-if="u.canonical_code" class="usage-sample"
                ><RouterLink
                  :class="`k-${kindOf(u.sample_type)}`"
                  :to="{ path: '/', query: { q: u.canonical_code } }"
                  ><i class="src-mk" aria-hidden="true"></i
                  >{{ u.canonical_code }}</RouterLink
                ><small>{{ u.display_name }}</small></span
              >
              <p v-else>保留原始来源，当前没有关联到样本，不计为新增样本。</p>
              <small v-if="u.experiment_code" class="usage-exp"
                >实验 {{ u.experiment_code }} · 展示编号
                {{ u.display_code ?? "—" }}</small
              >
            </li>
          </ul>
          <div v-if="relatedIndicators.length" class="caveat indicator-note">
            <h3>该来源提供的指标</h3>
            <p>{{ relatedIndicators.map((i) => i.name).join("、") }}。</p>
            <small
              >这里只列出用途对应的指标类别；测量值请从关联样本进入分析页面查看。</small
            >
          </div>
        </template>
        <section
          v-for="o in selected.observations"
          :key="`${o.block_code}-${o.cycle_no}-${o.replicate_no}`"
          class="observation-section"
        >
          <h3>
            <i class="src-mk k-recycled" aria-hidden="true"></i
            >{{ o.block_code }} · 第 {{ o.cycle_no }} 次循环 · 重复
            {{ o.replicate_no }}
          </h3>
          <p>
            此记录参与 {{ o.block_code }} 第
            {{ o.cycle_no }}
            次循环的各项指标平均值计算；空值不参与相应指标的平均。
          </p>
          <RouterLink
            class="text-button"
            :to="{ path: '/recycled', query: { block: o.block_code } }"
            >查看所在数据块的循环趋势 →</RouterLink
          >
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">原始观测指标</th>
                  <th scope="col" class="num-col">数值</th>
                  <th scope="col">单位</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="i in recycledIndicators" :key="i.key">
                  <td>{{ i.name }}</td>
                  <td class="numeric">
                    {{
                      number(
                        typeof o[i.key] === "number"
                          ? (o[i.key] as number)
                          : null,
                        4,
                      )
                    }}
                  </td>
                  <td>{{ i.unit ?? "未确认" }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </dialog>
  </div>
</template>

<style scoped>
/* ================================================================ page frame */
.sources-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: start;
  gap: 24px;
}
.sources-page > * {
  grid-column: 1 / -1;
  min-width: 0;
}
.nw {
  white-space: nowrap;
}
.src-note {
  font-size: 13px;
  line-height: 1.75;
  color: var(--text-2);
}
.source-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 40px 24px;
  text-align: center;
  color: var(--text-2);
}

/* material identity: colour + shape (softwood circle, hardwood square, blend triangle,
   recycled ring) for markers, chips, tiles and bars */
.k-softwood {
  --row-c: var(--sw);
  --row-ink: var(--sw-ink);
  --row-tint: var(--sw-tint);
}
.k-hardwood {
  --row-c: var(--hw);
  --row-ink: var(--hw-ink);
  --row-tint: var(--hw-tint);
}
.k-blend {
  --row-c: var(--bl);
  --row-ink: var(--bl-ink);
  --row-tint: var(--bl-tint);
}
.k-recycled {
  --row-c: var(--rc);
  --row-ink: var(--rc-ink);
  --row-tint: var(--rc-tint);
}
.k-other {
  --row-c: var(--text-3);
  --row-ink: var(--text-2);
  --row-tint: var(--surface-2);
}
.src-mk {
  display: inline-block;
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--row-c);
}
.k-hardwood .src-mk,
.src-mk.k-hardwood {
  border-radius: 2px;
}
.k-blend .src-mk,
.src-mk.k-blend {
  width: 9px;
  height: 9px;
  border-radius: 0;
  clip-path: polygon(50% 0, 100% 100%, 0 100%);
}
.k-recycled .src-mk,
.src-mk.k-recycled {
  background: none;
  box-shadow: inset 0 0 0 2px var(--row-c);
}

/* ================================================================ garden hero signature */
.src-sig {
  position: relative;
  margin: 0;
  width: 420px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.src-sig svg {
  display: block;
  width: 100%;
  height: auto;
  max-height: 142px;
  overflow: visible;
}
.src-sig-empty {
  width: 100%;
  aspect-ratio: 420 / 132;
}
.src-sig figcaption {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-2);
}
.src-sig figcaption b {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text);
}
.sig-link {
  fill: none;
  stroke-linecap: round;
  stroke-opacity: 0.5;
}
.sig-link.core {
  stroke: var(--accent);
  stroke-opacity: 0.32;
}
.sig-link.rec {
  stroke: var(--rc);
}
.sig-node {
  fill: var(--surface);
  stroke: var(--surface);
}
.sig-node.tint {
  fill: var(--accent-tint);
}
.sig-v {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 500;
  fill: var(--text);
}
.sig-t {
  font-family: var(--font-body);
  font-size: 11.5px;
  fill: var(--text-2);
}

/* ================================================================ source files */
.src-files {
  padding: 22px 22px 24px;
}
.src-files summary {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding-right: 34px;
  cursor: pointer;
  list-style: none;
  border-radius: var(--radius-xs);
}
.src-files summary::-webkit-details-marker {
  display: none;
}
.src-files-title {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--text);
}
.src-files-chevron {
  position: absolute;
  right: 4px;
  top: 3px;
  color: var(--text-2);
  transition: transform 0.25s var(--ease);
}
.src-files:not([open]) .src-files-chevron {
  transform: rotate(-90deg);
}
.src-files > .src-note {
  margin-top: 8px;
}
.src-file-grid {
  list-style: none;
  margin: 16px 0 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.src-file-grid > li {
  min-width: 0;
  display: flex;
}
.src-file {
  width: 100%;
  min-width: 0;
  display: grid;
  text-align: left;
  color: var(--text);
  transition:
    border-color 0.2s,
    box-shadow 0.25s,
    background 0.2s;
}
.src-file-label,
.src-file-spec,
.src-file-icon,
.src-file-bar {
  display: none;
}
.src-file-body {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.src-file-name {
  font-size: 13.5px;
  font-weight: 500;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.src-file-meta {
  min-width: 0;
  font-size: 12px;
  color: var(--text-2);
}
.src-file-meta b {
  font-weight: 500;
  color: var(--text);
}
.src-file-links {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.src-file-links .src-mk {
  display: none;
}

/* ================================================================ records */
.src-records {
  padding: 22px 0 0;
}
.src-head {
  padding: 0 22px;
}
.src-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}
.src-title-row h2 {
  font-size: 17px;
  color: var(--text);
}
.src-head .src-note {
  margin-top: 6px;
}
.src-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 12px;
  padding: 16px 22px 14px;
}
.src-file-filter {
  min-width: 200px;
  max-width: 340px;
}
.src-search {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1 1 300px;
  min-width: 0;
}
.src-search .search-field {
  flex: 1;
  width: auto;
  min-width: 0;
}
.src-search > .button {
  flex-shrink: 0;
}
.src-clear {
  white-space: nowrap;
}
.src-query {
  padding: 0 22px 12px;
  font-size: 12.5px;
  color: var(--text);
  overflow-wrap: anywhere;
}
.src-query-k {
  color: var(--text-2);
}
.sources-table {
  min-width: 600px;
}
.sources-table th.src-col-act,
.sources-table td.src-cell-act {
  text-align: right;
  width: 1%;
  white-space: nowrap;
}
.sources-table td {
  height: auto;
  vertical-align: top;
  white-space: normal;
  line-height: 1.6;
  padding-top: 11px;
  padding-bottom: 11px;
}
.sources-table th:first-child,
.sources-table td:first-child {
  padding-left: 22px;
}
.sources-table th:last-child,
.sources-table td:last-child {
  padding-right: 22px;
}
.src-cell-file {
  min-width: 220px;
}
.src-cell-file strong {
  display: block;
  font-size: 13px;
  font-weight: 500;
  overflow-wrap: anywhere;
}
.src-cell-file small {
  display: block;
  margin-top: 2px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
}
.src-targets {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
}
.src-target {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text);
  white-space: nowrap;
}
.src-none {
  font-size: 12.5px;
  color: var(--text-2);
}
.src-cell-use {
  font-size: 13px;
  color: var(--text);
}
.src-view {
  font-size: 13px;
  white-space: nowrap;
}
.src-empty-row td {
  padding: 0 !important;
}
.src-empty-row:hover td {
  background: none;
}
.src-empty-row .source-state {
  gap: 8px;
  padding: 44px 22px;
}
.src-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 16px;
  padding: 14px 22px;
  border-top: 1px solid var(--line-soft);
  font-size: 12.5px;
  color: var(--text-2);
}
.src-pager {
  display: flex;
  align-items: center;
  gap: 10px;
}
.src-pager-n {
  min-width: 56px;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text);
}
.src-pager-n span {
  color: var(--text-2);
}

/* ================================================================ counts */
.src-why {
  padding: 22px;
  container-type: inline-size;
}
.src-why-head h2 {
  font-size: 17px;
  color: var(--text);
}
.src-why-eyebrow,
.src-why-kicker,
.src-flow,
.src-stack,
.src-stack-l,
.src-why-sum {
  display: none;
}
.src-why-grid {
  display: grid;
}
.src-why-item {
  min-width: 0;
}
.src-why-n {
  font-family: var(--font-display);
  font-variant-numeric: tabular-nums;
  line-height: 1;
  color: var(--text);
}
.src-why-text b {
  display: block;
  font-weight: 700;
  color: var(--text);
}
.src-why-text p {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
}
.src-why-note {
  margin-top: 16px;
}

/* ================================================================ drawer */
.source-dialog h2 {
  font-family: var(--font-body);
  overflow-wrap: anywhere;
}
.src-coords {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 18px 0 4px;
}
.src-coords > div {
  min-width: 0;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  border: 1px solid var(--line-soft);
}
.src-coords dt {
  font-size: 11.5px;
  color: var(--text-2);
}
.src-coords dd {
  margin: 2px 0 0;
  font-family: var(--font-mono);
  font-size: 13.5px;
  color: var(--text);
  overflow-wrap: anywhere;
}
.src-dialog-note {
  margin-top: 18px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-2);
}
.usage-list {
  list-style: none;
  padding: 0;
  margin: 12px 0 18px;
  display: grid;
  gap: 8px;
}
.usage-list li {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  border: 1px solid var(--line-soft);
  font-size: 13px;
}
.usage-list strong {
  font-weight: 500;
  color: var(--text);
}
.usage-sample {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
}
.usage-sample a {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--accent-ink);
  overflow-wrap: anywhere;
  text-decoration: underline;
  text-decoration-color: var(--line-strong);
  text-underline-offset: 4px;
}
.usage-sample a:hover {
  text-decoration-color: currentColor;
}
.usage-sample small,
.usage-exp {
  font-size: 12px;
  color: var(--text-2);
}
.usage-list p {
  margin: 0;
  color: var(--text-2);
}
.indicator-note h3,
.observation-section h3 {
  font-size: 14px;
  color: var(--text);
}
.indicator-note p {
  margin: 6px 0;
  color: var(--text);
}
.indicator-note small {
  font-size: 12px;
  color: var(--text-2);
}
.observation-section {
  margin-top: 24px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-2);
}
.observation-section h3 {
  display: flex;
  align-items: center;
  gap: 8px;
}
.observation-section p {
  margin: 6px 0 8px;
}
.observation-section .table-scroll {
  margin-top: 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--line-soft);
}
.observation-section table {
  min-width: 420px;
}
.observation-section th {
  position: static;
}
.observation-section th.num-col {
  text-align: right;
}

/* ================================================================ 偏光 · polarized (v1 sources) */
:root[data-mode="polarized"] .src-files-title,
:root[data-mode="polarized"] .src-title-row h2,
:root[data-mode="polarized"] .src-why-head h2 {
  font-size: 17px;
  font-weight: 700;
}
/* file slides: mono S0x index column, a specimen disc sized by rows, then the name */
:root[data-mode="polarized"] .src-file {
  grid-template-columns: 40px 64px minmax(0, 1fr);
  grid-template-areas: "label spec body";
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: linear-gradient(100deg, var(--surface-hover), var(--surface-2) 40%);
}
:root[data-mode="polarized"] .src-file:hover {
  border-color: var(--line-strong);
}
:root[data-mode="polarized"] .src-file[aria-pressed="true"] {
  border-color: var(--accent);
  box-shadow: 0 0 30px -12px var(--accent);
}
:root[data-mode="polarized"] .src-file-label {
  grid-area: label;
  display: grid;
  gap: 2px;
  align-self: stretch;
  align-content: center;
  justify-items: center;
  padding: 6px 0;
  border-radius: 6px;
  background: color-mix(in srgb, var(--text) 7%, transparent);
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-2);
}
:root[data-mode="polarized"] .src-file-label span:last-child {
  font-size: 13px;
  color: var(--text);
}
:root[data-mode="polarized"] .src-file-spec {
  grid-area: spec;
  display: block;
  position: relative;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  overflow: hidden;
  background: color-mix(in srgb, var(--text) 3%, transparent);
  box-shadow: inset 0 0 0 1px var(--line);
}
:root[data-mode="polarized"] .src-file-spec i {
  position: absolute;
  inset: calc((1 - var(--disc)) * 50% + 4px);
  border-radius: 50%;
  background: var(--ifc);
  filter: blur(1px);
  opacity: 0.85;
  transition: opacity 0.25s;
}
:root[data-mode="polarized"] .src-file[aria-pressed="true"] .src-file-spec i,
:root[data-mode="polarized"] .src-file:hover .src-file-spec i {
  opacity: 1;
}
:root[data-mode="polarized"] .src-file-body {
  grid-area: body;
}
:root[data-mode="polarized"] .src-file-meta {
  display: grid;
  gap: 2px;
}
:root[data-mode="polarized"] .src-file-meta > :first-child {
  font-family: var(--font-mono);
  font-size: 11px;
}
:root[data-mode="polarized"] .src-file-meta b {
  font-weight: 400;
  color: inherit;
}
:root[data-mode="polarized"] .src-file-links {
  color: var(--text-3);
}
/* records: v1 toolbar and hairline table */
:root[data-mode="polarized"] .src-toolbar {
  padding-top: 18px;
}
:root[data-mode="polarized"] .src-search .search-field {
  height: 38px;
}
/* the count on the lit (pressed) chip steps up to stay ≥4.5:1 on its lighter fill */
:root[data-mode="polarized"] .src-scope > button[aria-pressed="true"] .cnt {
  color: var(--text-2);
}
:root[data-mode="polarized"] .src-cell-file small {
  color: var(--text-3);
}
:root[data-mode="polarized"] .src-view {
  padding: 4px 0;
  color: var(--accent-ink);
}
:root[data-mode="polarized"] .src-view:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}
:root[data-mode="polarized"] .src-foot {
  font-family: var(--font-body);
  border-top-color: var(--line);
}
/* counts: four apertures in one strip, huge thin numerals, composition bars, the sum */
:root[data-mode="polarized"] .src-why-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 16px;
  padding-bottom: 14px;
}
:root[data-mode="polarized"] .src-why-kicker {
  display: inline;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-3);
}
:root[data-mode="polarized"] .src-why-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-top: 1px solid var(--line);
}
:root[data-mode="polarized"] .src-why-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 22px 20px 16px;
  border-right: 1px solid var(--line-soft);
}
:root[data-mode="polarized"] .src-why-item:first-child {
  padding-left: 0;
}
:root[data-mode="polarized"] .src-why-item:last-child {
  border-right: 0;
  padding-right: 0;
}
:root[data-mode="polarized"] .src-why-n {
  font-weight: 200;
  font-size: clamp(48px, 5vw, 76px);
  letter-spacing: -0.05em;
  margin-bottom: 8px;
}
:root[data-mode="polarized"] .src-why-text {
  flex: 1;
}
:root[data-mode="polarized"] .src-stack {
  display: flex;
  gap: 2px;
  height: 6px;
  margin-top: 10px;
  border-radius: 3px;
  overflow: hidden;
}
:root[data-mode="polarized"] .src-stack i {
  display: block;
  height: 100%;
  flex-basis: 0;
  background: var(--row-c);
}
:root[data-mode="polarized"] .src-stack i.beat {
  background: linear-gradient(90deg, var(--sw), var(--hw));
}
:root[data-mode="polarized"] .src-stack.dots {
  height: auto;
  flex-wrap: wrap;
  gap: 3px;
  border-radius: 0;
}
:root[data-mode="polarized"] .src-stack.dots i {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--rc);
}
:root[data-mode="polarized"] .src-stack-l {
  display: block;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-3);
}
:root[data-mode="polarized"] .src-why-sum {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
  margin: 18px 0 14px;
  padding: 12px 16px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--text) 3%, transparent);
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text);
}
:root[data-mode="polarized"] .src-why-sum .op {
  color: var(--text-3);
}
:root[data-mode="polarized"] .src-why-note {
  margin-top: 0;
}
/* drawer: v1 dr-hero (mono eyebrow, the file name as the 22px / 900 title) */
:root[data-mode="polarized"] .source-dialog h2 {
  margin-top: 10px;
  font-family: var(--font-body);
  font-size: 22px;
  font-weight: 900;
  line-height: 1.3;
  letter-spacing: 0.01em;
  color: var(--text);
}
:root[data-mode="polarized"] .src-coords > div,
:root[data-mode="polarized"] .usage-list li {
  background: color-mix(in srgb, var(--text) 3%, transparent);
  border-color: var(--line-soft);
}
:root[data-mode="polarized"] .src-coords dt {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.08em;
  color: var(--text-3);
}

/* ================================================================ 纤维花园 · garden (v4 sources) */
:root[data-mode="garden"] .sources-page {
  gap: 18px;
  grid-template-columns: minmax(0, 1fr) clamp(320px, 28vw, 400px);
}
:root[data-mode="garden"] .src-records {
  grid-column: 1;
}
:root[data-mode="garden"] .src-why {
  grid-column: 2;
  align-self: stretch;
}
:root[data-mode="garden"] .src-files,
:root[data-mode="garden"] .src-why {
  padding: 22px 24px;
}
:root[data-mode="garden"] .src-records {
  padding-top: 22px;
}
:root[data-mode="garden"] .src-head,
:root[data-mode="garden"] .src-toolbar,
:root[data-mode="garden"] .src-query {
  padding-left: 24px;
  padding-right: 24px;
}
:root[data-mode="garden"] .src-files-title,
:root[data-mode="garden"] .src-title-row h2 {
  font-size: 19px;
  font-weight: 500;
  letter-spacing: 0.03em;
}
/* v4 .t-head .n: the count is plain mono beside the title */
:root[data-mode="garden"] .src-files .count-badge,
:root[data-mode="garden"] .src-title-row .count-badge {
  padding: 0;
  background: none;
  box-shadow: none;
  font-size: 14px;
  font-weight: 400;
  color: var(--text-2);
}
:root[data-mode="garden"] .src-file-grid {
  gap: 14px;
}
/* file tiles: stained icon, name, meta row, a bar as long as the file's row count */
:root[data-mode="garden"] .src-file {
  grid-template-columns: 34px minmax(0, 1fr);
  grid-template-areas:
    "icon name"
    "meta meta"
    "bar bar";
  align-items: start;
  gap: 10px 12px;
  padding: 16px 18px;
  border-radius: 24px;
  background: linear-gradient(
    160deg,
    color-mix(in srgb, var(--surface) 94%, transparent),
    color-mix(in srgb, var(--surface) 82%, transparent)
  );
  box-shadow:
    inset 0 0 0 1px var(--surface),
    var(--shadow-sm);
}
:root[data-mode="garden"] .src-file:hover {
  background: var(--surface);
}
:root[data-mode="garden"] .src-file[aria-pressed="true"] {
  box-shadow:
    inset 0 0 0 2px var(--row-c),
    var(--shadow-sm);
}
:root[data-mode="garden"] .src-file-icon {
  grid-area: icon;
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 12px;
  background: var(--row-tint);
  color: var(--row-ink);
}
:root[data-mode="garden"] .src-file-body {
  display: contents;
}
:root[data-mode="garden"] .src-file-name {
  grid-area: name;
  align-self: center;
}
:root[data-mode="garden"] .src-file-meta {
  grid-area: meta;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 4px 10px;
  font-size: 12.5px;
}
:root[data-mode="garden"] .src-file-links .src-mk {
  display: inline-block;
}
:root[data-mode="garden"] .src-file-bar {
  grid-area: bar;
  display: block;
  height: 6px;
  border-radius: 9px;
  overflow: hidden;
  background: color-mix(in srgb, var(--text) 6%, transparent);
}
:root[data-mode="garden"] .src-file-bar i {
  display: block;
  width: var(--share);
  height: 100%;
  border-radius: 9px;
  /* a touch of the ink keeps every stain ≥3:1 on the track (sage alone is 2.99:1) */
  background: color-mix(in oklab, var(--row-c) 80%, var(--row-ink));
}
/* records toolbar: pill controls */
:root[data-mode="garden"] .src-search .search-field {
  height: 38px;
}
:root[data-mode="garden"] .sources-table th {
  background: var(--surface-2);
}
:root[data-mode="garden"] .sources-table th:first-child,
:root[data-mode="garden"] .sources-table td:first-child {
  padding-left: 24px;
}
:root[data-mode="garden"] .sources-table th:last-child,
:root[data-mode="garden"] .sources-table td:last-child {
  padding-right: 24px;
}
:root[data-mode="garden"] .src-cell-file strong {
  font-weight: 400;
}
:root[data-mode="garden"] .src-cell-file small {
  font-family: var(--font-body);
  font-size: 12px;
}
:root[data-mode="garden"] .src-target {
  padding: 2px 10px 2px 8px;
  border-radius: 999px;
  background: var(--row-tint);
  font-size: 12.5px;
}
:root[data-mode="garden"] .src-view {
  padding: 5px 13px;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text);
  background: color-mix(in srgb, var(--surface) 85%, transparent);
  box-shadow:
    inset 0 0 0 1px var(--surface),
    var(--shadow-sm);
  transition:
    transform 0.35s var(--spring),
    background 0.25s;
}
:root[data-mode="garden"] .src-view:hover {
  background: var(--surface);
}
:root[data-mode="garden"] .src-view:active {
  transform: scale(0.96);
}
:root[data-mode="garden"] .src-foot {
  border-top: 0;
  padding: 14px 24px 18px;
}
/* counts tile: eyebrow, flow of samples into display points, four big numerals.
   The content is sticky inside the stretched tile; when it is taller than the space
   between the bars it scrolls until its end is in view, then holds. */
:root[data-mode="garden"] .src-why-inner {
  position: sticky;
  top: min(
    calc(var(--chrome-top) + 16px),
    calc(100vh - var(--chrome-bottom) - var(--why-h, 0px) - 16px)
  );
}
:root[data-mode="garden"] .src-why-eyebrow {
  display: inline-flex;
}
:root[data-mode="garden"] .src-why-head h2 {
  margin: 4px 0 14px;
  font-size: 22px;
  font-weight: 500;
  line-height: 1.35;
}
:root[data-mode="garden"] .src-flow {
  display: block;
  margin: 0 0 14px;
}
.src-flow svg {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}
.src-flow text {
  font-family: var(--font-body);
  font-size: 12px;
  fill: var(--text);
}
.src-flow .mono {
  font-family: var(--font-mono);
  font-weight: 500;
}
.src-flow .flow-cap {
  font-size: 11px;
  fill: var(--text-2);
}
.flow-node {
  fill: color-mix(in srgb, var(--surface) 80%, transparent);
  stroke: var(--surface);
}
.flow-node.tint {
  fill: var(--row-tint);
}
.flow-link {
  fill: none;
  stroke: var(--row-c);
  stroke-linecap: round;
  stroke-opacity: 0.75;
}
.flow-link.reuse {
  stroke: var(--rc);
  stroke-opacity: 0.45;
  stroke-dasharray: 3 4;
}
.flow-link.rc {
  stroke: var(--rc);
  stroke-opacity: 0.55;
}
:root[data-mode="garden"] .src-why-grid {
  gap: 12px;
}
:root[data-mode="garden"] .src-why-item {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  border-radius: 20px;
  background: color-mix(in srgb, var(--surface) 60%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--surface) 80%, transparent);
}
:root[data-mode="garden"] .src-why-n {
  font-size: 46px;
  font-weight: 380;
  font-variation-settings:
    "SOFT" 100,
    "WONK" 0,
    "opsz" 144;
  font-variant-numeric: lining-nums tabular-nums;
  letter-spacing: -0.035em;
  text-align: right;
}
:root[data-mode="garden"] .src-why-text b {
  font-weight: 500;
}
:root[data-mode="garden"] .src-why-text p {
  margin-top: 2px;
  line-height: 1.6;
}
/* drawer (v4 sheet) */
:root[data-mode="garden"] .source-dialog h2 {
  font-size: 22px;
  line-height: 1.35;
}
:root[data-mode="garden"] .src-coords > div,
:root[data-mode="garden"] .usage-list li {
  border: 0;
  background: color-mix(in srgb, var(--surface) 70%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}
:root[data-mode="garden"] .usage-sample a {
  color: var(--text);
  text-decoration-color: var(--row-c);
}
:root[data-mode="garden"] .observation-section .table-scroll {
  border: 0;
  background: color-mix(in srgb, var(--surface) 60%, transparent);
  box-shadow: inset 0 0 0 1px var(--surface);
}

/* ================================================================ responsive */
@container (max-width: 800px) {
  :root[data-mode="polarized"] .src-why-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  :root[data-mode="polarized"] .src-why-item {
    padding: 18px 14px 16px 0 !important;
    border-right: 0;
    border-bottom: 1px solid var(--line-soft);
  }
}
/* garden, full-width tile (the side column has dropped under the records) */
@container (min-width: 600px) and (max-width: 739px) {
  :root[data-mode="garden"] .src-why-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@container (min-width: 740px) {
  :root[data-mode="garden"] .src-why-inner {
    display: grid;
    grid-template-columns: minmax(0, 380px) minmax(0, 1fr);
    align-items: center;
    column-gap: 32px;
  }
  :root[data-mode="garden"] .src-why-head,
  :root[data-mode="garden"] .src-why-note {
    grid-column: 1 / -1;
  }
  :root[data-mode="garden"] .src-flow {
    margin: 0;
  }
}
@media (max-width: 1100px) {
  .src-file-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
/* garden: the counts tile drops under the records */
@media (max-width: 1060px) {
  :root[data-mode="garden"] .sources-page {
    grid-template-columns: minmax(0, 1fr);
  }
  :root[data-mode="garden"] .src-records,
  :root[data-mode="garden"] .src-why {
    grid-column: 1 / -1;
  }
  :root[data-mode="garden"] .src-why-inner {
    position: static;
  }
  :root[data-mode="garden"] .src-flow {
    max-width: 440px;
  }
}
@media (max-width: 720px) {
  .sources-page {
    gap: 16px;
  }
  .src-file-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .src-files,
  .src-why {
    padding: 18px 16px !important;
  }
  .src-records {
    padding-top: 18px !important;
  }
  .src-head,
  .src-toolbar,
  .src-query {
    padding-left: 16px !important;
    padding-right: 16px !important;
  }
  .src-file-filter,
  .src-scope,
  .src-search {
    flex: 1 1 100%;
    max-width: none;
    min-width: 0;
  }
  .src-scope {
    flex-wrap: nowrap;
    gap: 4px;
  }
  .src-scope > button {
    flex: 1 1 auto;
    justify-content: center;
    gap: 5px;
    padding: 0 8px;
    font-size: 13px;
  }
  .src-foot {
    padding: 12px 16px 16px !important;
  }
  .src-coords {
    gap: 6px;
  }
  .src-coords > div {
    padding: 8px 10px;
  }
  /* the 3-column observation table fits a phone drawer once its names may wrap */
  .observation-section table {
    min-width: 0;
    white-space: normal;
  }
  .observation-section th,
  .observation-section td {
    padding-left: 10px;
    padding-right: 10px;
  }
  .observation-section td.numeric {
    white-space: nowrap;
  }
  :root[data-mode="garden"] .src-why-item {
    grid-template-columns: 76px minmax(0, 1fr);
    gap: 12px;
    padding: 12px 14px;
  }
  :root[data-mode="garden"] .src-why-n {
    font-size: 38px;
  }
  /* phones: each source row becomes a compact card (v1 tbl-stack): the file on top
     without a label, the targets and uses labelled below, the action full width; the
     list scrolls in its own box so the page stays short */
  .src-table-scroll {
    max-height: min(620px, 72vh);
    padding: 0 12px 12px;
    overscroll-behavior-y: auto;
  }
  .sources-table {
    display: block;
    min-width: 0;
  }
  .sources-table thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
  .sources-table tbody {
    display: grid;
    gap: 10px;
  }
  .sources-table tbody tr {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 10px 14px;
    padding: 12px 14px;
    border: 1px solid var(--line);
    border-radius: 14px;
    background: var(--surface-2);
  }
  .sources-table tbody td {
    display: block;
    height: auto;
    padding: 0 !important;
    border: 0;
    background: none !important;
    text-align: left !important;
    width: auto !important;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .sources-table td[data-l]::before {
    content: attr(data-l);
    display: block;
    margin-bottom: 3px;
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.04em;
    color: var(--text-2);
  }
  .sources-table td.src-cell-file,
  .sources-table td.src-cell-act {
    grid-column: 1 / -1;
  }
  .src-cell-file {
    min-width: 0;
  }
  .src-target {
    white-space: normal;
  }
  .src-view {
    display: flex;
    width: 100%;
    min-height: 38px;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
  }
  :root[data-mode="polarized"] .src-view {
    border: 1px solid var(--line-strong);
    background: color-mix(in srgb, var(--text) 3%, transparent);
  }
  .sources-table tr.src-empty-row {
    display: block;
  }
  .sources-table tr.src-empty-row td {
    text-align: center !important;
  }
  .src-empty-row .source-state {
    padding: 28px 12px;
  }
  :root[data-mode="garden"] .src-table-scroll {
    padding: 2px 12px 12px;
  }
  :root[data-mode="garden"] .sources-table tbody tr {
    border: 0;
    border-radius: 20px;
    background: color-mix(in srgb, var(--surface) 75%, transparent);
    box-shadow:
      inset 0 0 0 1px var(--surface),
      var(--shadow-sm);
  }
}
@media (max-width: 420px) {
  .sources-table tbody tr {
    grid-template-columns: minmax(0, 1fr);
  }
  .src-search > .button {
    padding: 0 12px;
  }
}
</style>
