// 数据总览刻度盘的纯计算：辐条角度、观测点位置和清单分组。不涉及绘制。

export type DialMaterial = "softwood" | "hardwood" | "blend";
export const dialMaterials: DialMaterial[] = ["softwood", "hardwood", "blend"];

export interface DialSample {
  code: string;
  name: string;
  type: DialMaterial;
  sw: number; // 针叶质量比，0–100
  revs: number | null; // 纯浆的打浆转数；复配为 null
  sr: number | null; // 纯浆的打浆度；复配为 null
}

export interface DialObservation {
  block: string;
  cycle: number;
  replicate: number;
  grade: string | null;
  row: number;
  fl: number | null; // 长度加权纤维长度
  review: boolean;
}

export interface Spoke {
  sample: DialSample;
  type: DialMaterial;
  angle: number;
  index: number; // 含扇区间空位的槽位序号，决定开场生长顺序
}

const TOP = -Math.PI / 2;

// 样本盘：按材料分三个扇区，扇区之间空出 gap 个槽位；纯浆按转数、复配按针叶比例顺时针排开
export function buildSpokes(samples: DialSample[], gap = 3) {
  const ordered = dialMaterials.map((t) =>
    samples
      .filter((s) => s.type === t)
      .sort((a, b) =>
        t === "blend"
          ? a.sw - b.sw
          : (a.revs ?? 0) - (b.revs ?? 0) || a.code.localeCompare(b.code),
      ),
  );
  const slots = samples.length + gap * dialMaterials.length;
  const step = (Math.PI * 2) / slots;
  const spokes: Spoke[] = [];
  let k = 0;
  dialMaterials.forEach((type, i) => {
    for (const sample of ordered[i]!) {
      spokes.push({ sample, type, angle: TOP + (k + 0.5) * step, index: k });
      k++;
    }
    k += gap;
  });
  const sector = (t: DialMaterial): [number, number] | null => {
    const list = spokes.filter((p) => p.type === t);
    return list.length
      ? [list[0]!.angle - step / 2, list[list.length - 1]!.angle + step / 2]
      : null;
  };
  return { spokes, slots, step, sector, ordered };
}

// 观测盘：每个数据块一圈，每次循环一个扇区；同一格内按重复次数均匀排开
export function buildDots(observations: DialObservation[], sectorGap = 0.08) {
  const blocks = [...new Set(observations.map((o) => o.block))].sort();
  const cycles = Math.max(1, ...observations.map((o) => o.cycle));
  const maxRep = new Map(
    blocks.map((b) => [
      b,
      Math.max(
        ...observations.filter((o) => o.block === b).map((o) => o.replicate),
      ),
    ]),
  );
  const sector = (Math.PI * 2) / cycles;
  const dots = observations.map((o) => {
    const n = maxRep.get(o.block)!,
      start = TOP + (o.cycle - 1) * sector + sectorGap / 2;
    return {
      obs: o,
      ring: blocks.indexOf(o.block),
      angle: start + ((sector - sectorGap) * (o.replicate - 0.5)) / n,
    };
  });
  const has = (block: string, cycle: number) =>
    observations.some((o) => o.block === block && o.cycle === cycle);
  return { dots, blocks, cycles, sector, sectorGap, has };
}

// 清单分组：循环次数与重复次数相同的相邻数据块合并成一行
export function groupBlocks(observations: DialObservation[]) {
  const blocks = [...new Set(observations.map((o) => o.block))].sort();
  const groups: {
    blocks: string[];
    cycles: number;
    replicates: number;
    count: number;
  }[] = [];
  for (const b of blocks) {
    const rows = observations.filter((o) => o.block === b);
    const cycles = new Set(rows.map((o) => o.cycle)).size,
      replicates = Math.max(...rows.map((o) => o.replicate));
    const last = groups[groups.length - 1];
    if (last && last.cycles === cycles && last.replicates === replicates) {
      last.blocks.push(b);
      last.count += rows.length;
    } else groups.push({ blocks: [b], cycles, replicates, count: rows.length });
  }
  return groups;
}

// 开场时间表（秒）：辐条按槽位依次生长；观测点在扫描线经过时出现
export const spokeStart = (index: number, slots: number) =>
  0.2 + (index / slots) * 1.6;
export function sweepStart(angle: number) {
  let u = (angle - TOP) / (Math.PI * 2);
  u = ((u % 1) + 1) % 1;
  return 0.25 + u * 1.7;
}
