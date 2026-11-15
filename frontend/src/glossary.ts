export type TermCategory = "process" | "fiber" | "paper" | "mechanism";

export const termCategories: { key: TermCategory; label: string; description: string }[] = [
  { key: "process", label: "打浆与回用", description: "理解处理条件与循环过程" },
  { key: "fiber", label: "纤维形态", description: "读懂长度、粗度与形变" },
  { key: "paper", label: "纸张性能", description: "区分强度、指数与结构指标" },
  { key: "mechanism", label: "机理与方法", description: "理解结合、测量与适用边界" },
];

export interface FiberTerm {
  id: string;
  name: string;
  english: string;
  category: TermCategory;
  aliases: string[];
  definition: string;
  reading: string;
  caution: string;
  unit?: string;
  unitStatus?: "tentative" | "unconfirmed";
  formula?: string;
  example?: string;
  metricKeys?: string[];
  related: string[];
}

export const fiberTerms: FiberTerm[] = [
  {
    id: "beating-degree", name: "打浆度", english: "Schopper–Riegler number", category: "process", aliases: ["肖伯尔打浆度", "肖伯尔度", "SR", "滤水性能"], unit: "°SR",
    definition: "用肖伯尔法表征纸浆悬浮液滤水性能的指标，是观察机械处理后浆料变化的常用读数。",
    reading: "在相同测试条件下，较高的 °SR 通常表示滤水较慢。纤维润胀、细纤维化及细小组分等都可能影响结果。",
    caution: "打浆度是滤水读数，不能直接换算为打浆转数、能耗或纸张强度；比较时还要核对浆种和测试条件。",
    metricKeys: ["beating_degree_sr"], related: ["beating-revolutions", "pfi-refining", "fibrillation-length", "fines"],
  },
  {
    id: "beating-revolutions", name: "打浆转数", english: "Beating revolutions", category: "process", aliases: ["累计转数", "PFI转数", "打浆次数"], unit: "转",
    definition: "打浆过程中设备累计完成的旋转圈数，用来描述该次处理的机械作用水平。",
    reading: "在设备、负荷、浆浓和浆种等条件相同时，可用转数比较不同处理水平。",
    caution: "平台记录的是累计转数，不是每分钟转速 rpm。转数加倍不能直接解释为电耗、打浆度或强度加倍。",
    metricKeys: ["beating_revolutions"], related: ["beating-degree", "pfi-refining", "medium-consistency-refining"],
  },
  {
    id: "pfi-refining", name: "PFI打浆", english: "PFI mill refining", category: "process", aliases: ["PFI磨", "PFI磨浆", "实验室打浆"],
    definition: "用 PFI 磨进行的实验室纸浆机械处理方法，通过辊与磨室之间的作用改变纤维及浆料性能。",
    reading: "实验记录通常需同时交代浆浓、负荷或作用力、间隙、处理转数及浆种。",
    caution: "PFI 是处理方法，不是一个强度指标。相同转数在不同浆料和设备条件下不保证产生相同效果。",
    related: ["beating-revolutions", "beating-degree", "fiber-morphology"],
  },
  {
    id: "medium-consistency-refining", name: "中浓打浆", english: "Medium-consistency refining", category: "process", aliases: ["中浓磨浆", "浆料浓度", "浆浓"],
    definition: "在相应工艺所称的中等浆料浓度范围内进行的机械处理。浆浓一般以绝干纤维质量占浆料总质量的百分比表示。",
    reading: "浆浓会影响纤维间作用、流动状态和处理效果，需要与设备类型一起理解。",
    caution: "“中浓”的数值范围依工艺和资料而异；本页不将某个浓度区间套用于所有设备，也不据此补填缺失条件。",
    related: ["pfi-refining", "beating-degree"],
  },
  {
    id: "recycling", name: "回用（循环回用）", english: "Fiber recycling", category: "process", aliases: ["再生纸浆", "废纸回收", "循环次数", "回用次数"],
    definition: "纸或纤维经再制浆及后续处理重新用于成纸的过程；循环回用关注多次处理后纤维与纸张性能的变化。",
    reading: "循环中可能同时发生干燥再润湿、纤维损失、形态变化和组分变化，需要按实际流程解释趋势。",
    caution: "变化方向取决于原料与处理过程。平台再生数据块的部分处理条件尚未确认，不能只凭循环编号推断具体工艺。",
    related: ["fibrillation-ability", "fiber-length-distribution", "inter-fiber-bonding"],
  },
  {
    id: "fiber-morphology", name: "纤维形貌", english: "Fiber morphology", category: "fiber", aliases: ["纤维形态", "形态参数", "纤维特性"],
    definition: "纤维长度、宽度、粗度、弯曲、扭结及表面分丝帚化等形态特征的统称。",
    reading: "平台用多项形态指标描述同一样本，适合结合起来观察，而不是用单个数值代替整体纤维状态。",
    caution: "形态与成纸性能的关联受材料、结合和成纸条件影响；相关关系不能直接当作作用机制的证明。",
    related: ["fiber-length", "fiber-width", "fiber-coarseness", "kink-angle"],
  },
  {
    id: "fiber-length", name: "纤维长度", english: "Fiber length", category: "fiber", aliases: ["平均纤维长度", "长度尺寸"], unit: "mm",
    definition: "单根纤维的长度尺寸。描述一批纤维时，通常报告某种平均长度以及长度分布。",
    reading: "算术平均与长度加权平均采用不同权重，平台将两种读数分别保存。",
    caution: "比较前先核对权重、检测范围及是否计入细小纤维。长纤维并不保证所有纸张强度指标都更高。",
    related: ["fiber-length-arithmetic", "fiber-length-weighted", "fiber-length-distribution"],
  },
  {
    id: "fiber-length-arithmetic", name: "纤维长度（算术平均）", english: "Arithmetic mean fiber length", category: "fiber", aliases: ["算数平均长", "算术平均长", "数均长度"], unit: "mm",
    definition: "对参与统计的每根纤维赋予相同权重，再计算得到的平均长度。",
    formula: "算术平均长度 = 各纤维长度之和 ÷ 参与统计的纤维根数",
    reading: "由于每根纤维权重相同，短纤维数量变化会明显影响这一读数。",
    caution: "公式中的统计集合应与仪器设置一致，不能把排除细小组分的结果与全组分结果直接比较。",
    metricKeys: ["fiber_length_arithmetic_mm"], related: ["fiber-length-weighted", "fiber-length-distribution", "fines"],
  },
  {
    id: "fiber-length-weighted", name: "纤维长度（长度加权）", english: "Length-weighted mean fiber length", category: "fiber", aliases: ["长度加权长", "重均纤维长度", "长度加权平均长度"], unit: "mm",
    definition: "以纤维本身的长度作为权重计算的平均长度，较长纤维在结果中占更大权重。",
    formula: "长度加权平均长度 = Σ（纤维长度²）÷ Σ（纤维长度）",
    reading: "与算术平均相比，它对长纤维更敏感；应同时参考长度分布来理解纤维组成。",
    caution: "这里是长度权重，不应未经确认就解释为质量权重。不同仪器的有效纤维范围可能不同。",
    metricKeys: ["fiber_length_weighted_mm"], related: ["fiber-length-arithmetic", "fiber-length-distribution"],
  },
  {
    id: "fiber-width", name: "纤维宽度", english: "Fiber width", category: "fiber", aliases: ["横向尺寸", "宽度"], unit: "μm",
    definition: "纤维横向尺寸的测量值，通常由图像分析等方法获得并按设定方式汇总。",
    reading: "宽度与细胞壁、管腔、纤维塌陷和原料类型有关，可与粗度一起描述纤维特征。",
    caution: "投影宽度不能直接替代细胞壁厚度，也不能单独决定纸页致密程度或强度。",
    metricKeys: ["fiber_width_um"], related: ["fiber-coarseness", "fiber-morphology"],
  },
  {
    id: "fiber-coarseness", name: "纤维粗度", english: "Fiber coarseness", category: "fiber", aliases: ["粗度", "线密度", "mg/100m", "μg/m"], unit: "mg/m",
    definition: "单位长度纤维的质量，用来描述纤维的质量与长度关系。平台采用 mg/m。",
    formula: "粗度 = 纤维质量 ÷ 纤维总长度",
    example: "10 mg/100m = 0.10 mg/m = 100 μg/m。单位不同，数值不能直接并列比较。",
    reading: "粗度受细胞壁与管腔结构等影响，常与柔顺性、单位质量可形成的纤维网络有关。",
    caution: "粗度是线密度，纤维宽度是几何尺寸，两者不能互相替代；文献与平台比较前需换算单位。",
    metricKeys: ["fiber_coarseness_mg_m"], related: ["fiber-width", "density", "inter-fiber-bonding"],
  },
  {
    id: "kink-angle", name: "扭结角", english: "Kink angle", category: "fiber", aliases: ["纤维扭结角", "局部弯折角"], unit: "°",
    definition: "描述纤维局部急剧改变方向时的角度，是观察局部形变的一种参数。",
    reading: "它描述局部折弯，与整根纤维的连续卷曲不同；通常需结合扭结数量或发生比例阅读。",
    caution: "识别阈值与角度算法随仪器而异。扭结角变化不等于已经直接测得纤维强度变化。",
    metricKeys: ["kink_angle_deg"], related: ["kinked-fiber-ratio", "kink-index", "curl-index"],
  },
  {
    id: "kinked-fiber-ratio", name: "扭结纤维比例", english: "Kinked fiber proportion", category: "fiber", aliases: ["扭结纤维", "扭结纤维占比", "扭结纤维比"], unit: "%",
    definition: "按指定识别规则，具有扭结特征的纤维在统计纤维中所占的比例。",
    reading: "它回答“有多少纤维被识别为扭结”，与平均扭结角和每单位长度的扭结数量分别描述不同信息。",
    caution: "百分比需要明确分母和识别规则。平台比例采用 0—100 口径，不能直接当作 0—1 小数。",
    metricKeys: ["kinked_fiber_pct"], related: ["kink-angle", "kink-index", "curved-fiber-ratio"],
  },
  {
    id: "curved-fiber-ratio", name: "弯曲纤维比例", english: "Curved fiber proportion", category: "fiber", aliases: ["弯曲", "弯曲（%）", "弯曲纤维占比"], unit: "%",
    definition: "平台沿用的弯曲形态百分比指标，用于观察纤维偏离伸直状态的情况。",
    reading: "可结合扭结角、平均长度和处理条件，查看形变是否随处理水平发生变化。",
    caution: "原表的“弯曲（%）”仍需结合仪器算法理解；不能只凭名称就确认它是根数占比或平均卷曲指数。",
    metricKeys: ["curved_fiber_pct"], related: ["curl-index", "kinked-fiber-ratio", "fiber-morphology"],
  },
  {
    id: "curl-index", name: "卷曲指数", english: "Curl index", category: "fiber", aliases: ["卷曲程度", "curl", "形状因子"],
    definition: "量化纤维整体弯曲或卷曲程度的指标，常通过轮廓长度与端点距离等几何关系构建。",
    reading: "用于描述整根纤维的形状，可辅助理解伸展、网络结构和纸页变形行为。",
    caution: "卷曲指数与形状因子可能采用相反方向的定义；比较前核对公式，不能直接套用平台的弯曲百分比。",
    related: ["curved-fiber-ratio", "kink-angle", "fiber-length"],
  },
  {
    id: "kink-index", name: "扭结指数", english: "Kink index", category: "fiber", aliases: ["扭结频率", "kink index", "扭结程度"],
    definition: "对局部扭结特征进行汇总的指标；具体算法可包含角度、频次或长度归一化等信息。",
    reading: "它与扭结纤维比例、平均扭结角可互相补充，反映形变的不同侧面。",
    caution: "不同报告中的同名指数未必采用同一算法，必须核对定义和单位。该概念不代表平台已有独立实测字段。",
    related: ["kink-angle", "kinked-fiber-ratio"],
  },
  {
    id: "fibrillation-length", name: "分丝帚化长度比", english: "Fibrillation length proportion", category: "fiber", aliases: ["分丝帚化", "细纤维化", "表面起毛", "fibrillation"], unit: "%",
    definition: "按相应测量算法，用比例描述纤维表面可识别的分丝、起毛等细纤维化特征。",
    reading: "分丝帚化可能增加有效接触与结合的机会，是打浆后常关注的纤维变化之一。",
    caution: "长度比、周长比和面积比不是同一口径；平台沿用原始长度比名称，不能换称为细小纤维含量。",
    metricKeys: ["fibrillation_length_pct"], related: ["fibrillation-ability", "inter-fiber-bonding", "fines"],
  },
  {
    id: "broken-fiber-ratio", name: "折断纤维比", english: "Broken fiber proportion", category: "fiber", aliases: ["折断纤维", "纤维切断", "折断率"], unit: "%",
    definition: "按仪器的识别规则，反映被判定为折断纤维的相对比例。",
    reading: "与平均长度和长度分布一起阅读，有助于观察机械处理后的纤维变化。",
    caution: "短纤维不一定都是处理中新折断的纤维；根数比、长度比等分母应以原始报告为准。",
    metricKeys: ["broken_fiber_pct"], related: ["fiber-length-distribution", "fines", "tear-index"],
  },
  {
    id: "fines", name: "细小纤维含量", english: "Fines content", category: "fiber", aliases: ["细小纤维", "细小组分", "fines", "0.2 mm"], unit: "%（依统计口径）",
    definition: "按筛分或图像测量规则识别的细小纤维与碎片组分所占的比例。部分长度法采用约 0.2 mm 的分界。",
    reading: "细小组分可能影响结合、滤水、留着与成纸结构，作用取决于性质、含量及成纸条件。",
    caution: "分界与分母依方法而异。长度比、长度加权比、面积比和数量比不能混用。",
    related: ["fines-length", "fines-weighted-length", "fines-area", "beating-degree"],
  },
  {
    id: "fines-length", name: "细小纤维长度比", english: "Fines length proportion", category: "fiber", aliases: ["细小纤维长度占比", "细小长度比"], unit: "%",
    definition: "以长度统计口径描述细小组分相对含量的指标，平台与长度加权比、面积比分别保存。",
    reading: "用于查看细小组分在相应长度统计中的占比变化。",
    caution: "应核对仪器的细小组分阈值及具体分母；“长度比”和“长度加权比”不能仅因名称接近就视为相同。",
    metricKeys: ["fines_length_pct"], related: ["fines", "fines-weighted-length", "fines-area"],
  },
  {
    id: "fines-weighted-length", name: "细小纤维长度加权比", english: "Length-weighted fines proportion", category: "fiber", aliases: ["细小纤维（长度加权比%）", "细小纤维加权长度比", "细小长度加权比"], unit: "%",
    definition: "按长度加权的统计规则报告细小组分含量的指标。平台保留原始结果，不与其他细小比例合并。",
    reading: "权重会影响不同长度组分对结果的贡献，解释时应与仪器报告的统计定义一致。",
    caution: "当前资料不足以仅凭列名重建完整计算式；请勿把它直接解释为细小纤维根数占比。",
    metricKeys: ["fines_weighted_length_pct"], related: ["fines-length", "fines-area", "fiber-length-weighted"],
  },
  {
    id: "fines-area", name: "细小纤维面积比", english: "Fines area proportion", category: "fiber", aliases: ["细小纤维面积占比", "投影面积比"], unit: "%",
    definition: "按面积口径统计的细小组分比例，通常与图像中识别到的投影面积有关。",
    reading: "从面积维度描述细小组分，可与长度类比例对照观察。",
    caution: "投影面积不等于真实比表面积，也不等于已形成的纤维结合面积；不能据此直接计算结合力。",
    metricKeys: ["fines_area_pct"], related: ["fines", "fines-length", "fines-weighted-length"],
  },
  {
    id: "fiber-length-distribution", name: "纤维长度分布", english: "Fiber length distribution", category: "fiber", aliases: ["长度分级", "长度区间", "长度分布百分比"], unit: "%（依统计口径）",
    definition: "将纤维按长度区间分组，再报告各区间占比，用于描述长短纤维的组成。",
    reading: "相比单一平均值，分布可以揭示短纤维增加、长纤维减少等组成变化。",
    caution: "先核对区间边界、权重与是否包含细小组分。原始分布异常不应通过自动归一化掩盖。",
    metricKeys: ["length_0_2_0_3_pct", "length_0_3_0_45_pct", "length_0_45_0_67_pct", "length_0_67_1_pct", "length_1_1_5_pct", "length_1_5_2_24_pct", "length_2_24_3_35_pct", "length_3_35_5_01_pct", "length_5_01_7_5_pct", "length_gt_7_5_pct"],
    related: ["fiber-length-arithmetic", "fiber-length-weighted", "fines"],
  },
  {
    id: "fibrillation-ability", name: "纤维分丝帚化能力", english: "Fiber fibrillation potential", category: "fiber", aliases: ["帚化能力", "细纤维化能力", "再打浆能力"],
    definition: "纤维在机械处理下形成分丝、起毛等细纤维化特征的能力。",
    reading: "可通过规定处理前后的形态、滤水和成纸变化进行综合研究。",
    caution: "它是材料响应能力的概念，单次分丝帚化长度比读数不能独立代表这种能力。",
    related: ["fibrillation-length", "recycling", "inter-fiber-bonding"],
  },
  {
    id: "basis-weight", name: "定量", english: "Grammage / basis weight", category: "paper", aliases: ["克重", "坪量", "gsm"], unit: "g/m²",
    definition: "单位面积纸或纸板的质量，也称克重，是比较纸张性能时的重要基础指标。",
    formula: "定量 = 试样质量 ÷ 试样面积",
    reading: "它参与抗张指数、耐破指数、撕裂指数及表观密度等计算。",
    caution: "定量是单位面积质量，厚度是尺寸。相同定量的纸张仍可能具有不同厚度和结构。",
    metricKeys: ["basis_weight_g_m2"], related: ["thickness", "density", "tensile-index"],
  },
  {
    id: "thickness", name: "厚度", english: "Paper thickness / caliper", category: "paper", aliases: ["纸张厚度", "纸页厚度"], unit: "μm",
    definition: "在规定测量压力下，纸页两个表面之间的距离。单张厚度与叠层测得的厚度需区分。",
    reading: "与定量一起可用于计算表观密度；也与纸页结构和压缩特性有关。",
    caution: "测量压力、调湿和单张或叠层方法都会影响结果，比较时应保持方法一致。",
    metricKeys: ["thickness_um"], related: ["basis-weight", "density", "porosity"],
  },
  {
    id: "tensile-index", name: "抗张指数", english: "Tensile index", category: "paper", aliases: ["抗张强度指数", "拉伸指数"], unit: "N·m/g",
    definition: "纸张抗张强度按定量归一化后的指标，用于在考虑单位面积质量的基础上比较抗张表现。",
    formula: "抗张指数 [N·m/g] = 1000 × 抗张强度 [kN/m] ÷ 定量 [g/m²]",
    example: "若抗张强度为 3 kN/m、定量为 60 g/m²，则抗张指数为 50 N·m/g。此处仅为计算示例。",
    reading: "综合受到纤维自身性质、纤维间结合、排列与成纸条件影响。",
    caution: "指数归一化不代表完全消除了定量和结构的影响。核心库的抗张指数与再生库的抗张强度不可直接混用。",
    metricKeys: ["tensile_index"], related: ["tensile-strength", "basis-weight", "zero-span", "inter-fiber-bonding"],
  },
  {
    id: "burst-index", name: "耐破指数", english: "Burst index", category: "paper", aliases: ["耐破强度指数", "耐破度指数"], unit: "kPa·m²/g",
    definition: "纸张耐破强度除以定量得到的指标，描述按定量归一化后的耐破表现。",
    formula: "耐破指数 [kPa·m²/g] = 耐破强度 [kPa] ÷ 定量 [g/m²]",
    reading: "可辅助比较纸页在规定试验中承受局部增压破坏的能力。",
    caution: "需要核对测试方法、纸页方向及状态；耐破指数与原始耐破强度单位不同。",
    metricKeys: ["burst_index"], related: ["burst-strength", "basis-weight", "paper-strength"],
  },
  {
    id: "tear-index", name: "撕裂指数", english: "Tear index", category: "paper", aliases: ["撕裂度指数", "抗撕裂指数"], unit: "mN·m²/g",
    definition: "纸张撕裂强度除以定量所得的指标，描述按定量归一化后的抗撕裂表现。",
    formula: "撕裂指数 [mN·m²/g] = 撕裂强度 [mN] ÷ 定量 [g/m²]",
    reading: "与纤维长度、纤维强度、结合和拔出等因素共同相关。",
    caution: "撕裂与抗张对应不同破坏过程，不能由抗张指数提高直接推出撕裂指数也提高。",
    metricKeys: ["tear_index"], related: ["tear-strength", "fiber-length", "tensile-index"],
  },
  {
    id: "zero-span", name: "零距抗张强度", english: "Zero-span tensile strength", category: "paper", aliases: ["零距抗张", "零跨度抗张", "zero span"], unit: "N/cm",
    definition: "将试样夹具的初始间距调至零距条件后测得的抗张强度，可在规定方法下辅助评价纤维群体的强度特征。",
    reading: "常与普通抗张结果对照，用于研究纤维强度与纤维间结合的作用。干态、湿态及再润湿状态需分别记录。",
    caution: "零距结果仍是试样与方法条件下的间接指标，不能等同于直接测得单根纤维的固有强度，也不能认为结合影响已完全消除。",
    metricKeys: ["zero_span_tensile"], related: ["individual-fiber-strength", "inter-fiber-bonding", "tensile-index"],
  },
  {
    id: "surface-roughness", name: "表面粗糙度", english: "Surface roughness", category: "paper", aliases: ["粗糙度", "Bendtsen", "PPS", "Bekk", "平滑度"], unit: "ml/min",
    definition: "描述纸面凹凸或表面泄漏特征的指标，具体数值与所用测量方法有关。平台原始目录使用 ml/min。",
    reading: "在同一种空气泄漏粗糙度方法内，较大流量通常对应较粗糙的表面。",
    caution: "Bendtsen 流量、PPS 粗糙度和 Bekk 平滑度的单位与方向不同。仅凭 ml/min 不能确认原实验采用了哪种仪器。",
    metricKeys: ["surface_roughness"], related: ["air-permeance", "density", "fiber-width"],
  },
  {
    id: "air-permeance", name: "透气度", english: "Air permeance", category: "paper", aliases: ["空气透过", "透气性", "air permeability", "μm/(Pa·s)"], unit: "μm/(Pa·s)", unitStatus: "tentative",
    definition: "表征空气在规定压差和面积条件下通过纸页的能力。报告可能采用归一化透过率、流量或通过时间等不同形式。",
    reading: "通常与纸页孔隙结构和成纸状态有关，解释数值方向前必须先确认方法与单位。",
    caution: "平台透气度单位仍为暂定。流量、透过率与阻力时间不能直接比较，也不能在缺少面积和压差时换算。",
    metricKeys: ["air_permeability"], related: ["porosity", "density", "surface-roughness"],
  },
  {
    id: "folding-endurance", name: "耐折度", english: "Folding endurance / fold number", category: "paper", aliases: ["耐折次数", "双折次数", "耐折强度", "log10"], unitStatus: "unconfirmed",
    definition: "描述纸条在规定张力和折叠方式下抵抗反复折叠断裂的表现。报告可能使用双折次数或其对数形式。",
    reading: "受试验仪器、张力、方向和湿度等影响，适合在方法一致的条件下比较。",
    caution: "平台单位及报告形式尚未确认，不能统一标成“次”，也不能未经核对就作对数或反对数转换。",
    metricKeys: ["folding_endurance_raw"], related: ["paper-strength", "individual-fiber-strength"],
  },
  {
    id: "paper-strength", name: "纸张强度", english: "Paper strength properties", category: "paper", aliases: ["机械强度", "抗张、耐破、撕裂", "纸张性能"],
    definition: "纸页在不同破坏方式下承受作用的能力。抗张、耐破、撕裂和耐折等分别对应不同试验。",
    reading: "需要明确具体指标，再讨论“变强”或“变弱”；不同指标可能呈现不同变化方向。",
    caution: "“强度”和“指数”要按各自定义区分，单项提高也不代表全部机械性能提高。",
    related: ["tensile-strength", "burst-strength", "tear-strength", "folding-endurance"],
  },
  {
    id: "tensile-strength", name: "抗张强度", english: "Tensile strength", category: "paper", aliases: ["抗张", "拉伸强度", "抗拉强度"], unit: "kN/m",
    definition: "在规定试验条件下，纸页断裂前承受的最大拉力除以试样宽度所得的值。",
    reading: "平台再生纸浆数据保存此类强度读数；按定量归一化后才得到抗张指数。",
    caution: "不同于以 MPa 表示的拉伸应力，也不同于 N·m/g 表示的抗张指数。",
    metricKeys: ["tensile_strength_kn_m"], related: ["tensile-index", "zero-span", "paper-strength"],
  },
  {
    id: "burst-strength", name: "耐破强度", english: "Bursting strength", category: "paper", aliases: ["耐破度", "耐破", "破裂压力"], unit: "kPa",
    definition: "在规定耐破试验中，使纸样破裂所需的最大压力。",
    reading: "与抗张、撕裂一起描述不同破坏方式下的纸张表现。",
    caution: "耐破强度是压力读数；除以定量后才是耐破指数，两者不应按原始数值直接比较。",
    metricKeys: ["burst_strength_kpa"], related: ["burst-index", "basis-weight", "paper-strength"],
  },
  {
    id: "tear-strength", name: "撕裂强度", english: "Tearing resistance", category: "paper", aliases: ["撕裂度", "抗撕裂力", "撕裂"], unit: "mN",
    definition: "在规定试验中，扩展已有切口、撕裂纸样所需的力学读数。",
    reading: "反映与缺口扩展有关的破坏表现，可按定量计算撕裂指数。",
    caution: "它不是拉断完整纸条所需的力；与撕裂指数比较时需先核对定量与单位。",
    metricKeys: ["tear_strength_mn"], related: ["tear-index", "fiber-length", "paper-strength"],
  },
  {
    id: "density", name: "紧度（表观密度）", english: "Apparent sheet density", category: "paper", aliases: ["紧度", "密度", "纸张密度", "松厚度", "比容"], unit: "g/cm³",
    definition: "以纸页整体体积计算的单位体积质量，包含纸页孔隙的影响，造纸中常称紧度。",
    formula: "表观密度 [g/cm³] = 定量 [g/m²] ÷ 厚度 [μm]",
    example: "定量 60 g/m²、厚度 100 μm，对应表观密度 0.60 g/cm³。此处仅为计算示例。",
    reading: "同一定量下，较厚的纸页通常具有较低表观密度；其倒数可表示比容，常称松厚度。",
    caution: "表观密度不等于纤维材料的真实密度。厚度测量方法和压力应一致，不能仅用紧度反推出孔隙率。",
    related: ["basis-weight", "thickness", "porosity", "air-permeance"],
  },
  {
    id: "porosity", name: "孔隙率", english: "Porosity", category: "paper", aliases: ["孔隙体积比", "孔隙结构", "空隙率"], unit: "%",
    definition: "纸页中孔隙体积占纸页总体积的比例，用来描述其多孔结构。",
    reading: "与孔径、连通性等共同影响空气和液体通过纸页的行为。",
    caution: "相同孔隙率可以具有不同孔隙连通性和透气表现。孔隙率不等于透气度，当前平台也没有独立孔隙率实测字段。",
    related: ["density", "air-permeance", "thickness"],
  },
  {
    id: "inter-fiber-bonding", name: "纤维间结合力", english: "Inter-fiber bonding", category: "mechanism", aliases: ["氢键", "结合强度", "结合面积", "纤维结合"],
    definition: "纤维接触后形成的结合及其抵抗分离的能力，与接触面积、表面性质和多种界面作用有关。",
    reading: "分丝帚化、纤维柔顺性、压榨与干燥等可能改变有效结合及纸页网络。",
    caution: "氢键并非唯一相关因素；从相关曲线或分丝帚化比例不能直接求出实际结合力。",
    related: ["fibrillation-length", "individual-fiber-strength", "tensile-index", "weakest-link"],
  },
  {
    id: "individual-fiber-strength", name: "纤维自身强度", english: "Individual fiber strength", category: "mechanism", aliases: ["单根纤维强度", "固有强度", "纤维本体强度"],
    definition: "单根纤维在规定受力与测试条件下抵抗破坏的能力，与细胞壁结构、缺陷和化学组成等有关。",
    reading: "可通过单纤维试验研究；零距抗张提供与纤维群体强度相关的间接信息。",
    caution: "纸页变强可能来自结合改善，不能据此断言单根纤维变强。纸张与单纤维的单位和受力方式也需区分。",
    related: ["zero-span", "inter-fiber-bonding", "weakest-link"],
  },
  {
    id: "weakest-link", name: "短板效应", english: "Limiting-factor concept", category: "mechanism", aliases: ["木桶效应", "限制因素", "强度瓶颈"],
    definition: "用于说明整体表现可能受到某些关键薄弱环节限制的概念，可辅助思考纤维强度、结合和网络结构的共同作用。",
    reading: "适合提出“当前更可能受哪个环节限制”的研究问题，再用实验或模型检验。",
    caution: "这是一种解释框架，不是把几个不同单位的指标取最小值就能得到纸张强度的计算公式。",
    related: ["individual-fiber-strength", "inter-fiber-bonding", "paper-strength"],
  },
  {
    id: "fiber-staining", name: "纤维染色试剂", english: "Fiber staining reagent", category: "mechanism", aliases: ["赫氏染色剂", "Herzberg", "碘-碘化钾", "显微染色"],
    definition: "用于增强纤维显微观察对比、辅助识别原料或制浆特征的试剂。",
    reading: "染色结果需与形态观察及规定的鉴别方法共同解释。",
    caution: "颜色受试剂、处理和观察条件影响，单一颜色不能独立确定全部纤维来源或力学性能。",
    related: ["fiber-morphology", "fiber-width"],
  },
];

function normalize(value: string): string {
  return value.normalize("NFKC").toLocaleLowerCase().replace(/[µμ]/g, "u").replace(/\s+/g, " ").trim();
}

export function matchesFiberTerm(term: FiberTerm, query: string): boolean {
  const words = normalize(query).split(" ").filter(Boolean);
  const text = normalize([term.name, term.english, ...term.aliases, term.unit ?? "", term.definition,
    term.reading, term.caution, term.formula ?? "", ...(term.metricKeys ?? [])].join(" "));
  return words.every((word) => text.includes(word));
}

export function termLinks(term: FiberTerm): { to: string; label: string }[] {
  const metric = term.metricKeys?.[0];
  if (term.id === "recycling" || metric?.startsWith("length_") || ["tensile-strength", "burst-strength", "tear-strength"].includes(term.id)) {
    return [{ to: "/recycled", label: "查看再生纸浆循环" }];
  }
  if (term.category === "process") return [{ to: "/beating", label: "查看打浆分析" }];
  if (metric) return [{ to: "/association", label: "查看纤维—纸张关联" }, { to: "/beating", label: "查看打浆分析" }];
  return [];
}
