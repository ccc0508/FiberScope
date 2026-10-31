# 植物纤维数据入库预检报告

- 状态：PASS
- 生成时间（UTC）：2026-08-02T08:46:04.628541+00:00
- 数据目录：`C:\path\to\project\data`
- 阻断错误：0
- 告警：2

## 数量核对

| 对象 | 预期 | 实际 | 结果 |
|---|---:|---:|---|
| sample | 61 | 61 | 通过 |
| experiment_sample | 63 | 63 | 通过 |
| sample_component | 70 | 70 | 通过 |
| fiber_measurement | 61 | 61 | 通过 |
| paper_measurement | 61 | 61 | 通过 |
| data_source | 178 | 178 | 通过 |

## 来源文件

| 文件 | 版本 | 数据行 | SHA-256 |
|---|---|---:|---|
| 针叶木-打浆转数-打浆度(1).xlsx | 原始版 | 28 | `c712c20a369f5a56e446adf04ceb45eade7a5422e9fec1b0dcdf9c1144eca914` |
| 针叶木-打浆转数-纤维特性(1).xlsx | 原始版 | 28 | `334598b2ddcfb1fd3851643ce0413903ce122d034f11b4b5f2f15898de1c55e2` |
| 针叶木-打浆转数-纸张性能(1).xlsx | 原始版 | 28 | `191d86fda36e2c31523274f17cbaa24ef75cdd28e6651dee23185c65db93fdef` |
| data1-阔叶木-打浆转数-打浆度(1).xlsx | 原始版 | 24 | `729d4820415cd69c1495a0787dcd7ed0c4b3d14662b5785073fa2fab73c082ff` |
| data2-阔叶木-打浆转数-纤维特性(1).xlsx | 原始版 | 24 | `84d2559e5c78edcd8187228c1be64819aaa6f68c0b8d2bbeb52e5668cde6ac8a` |
| data3-阔叶木-打浆转数-纸张性能(1).xlsx | 原始版 | 24 | `705c12b6a9bddba2549c12e4b82ce3b8a32e33875cecfe1589115a81dc36cf93` |
| data4-针阔-复配-纤维特性0110(1).xlsx | 0110 | 11 | `5b3762913f2dea79a26c9649b1b321b81d23b63e741fd3a3c3a77d61d83e1a14` |
| data5-针阔-复配-纸张特性0110(1).xlsx | 0110 | 11 | `c7de273d78619c2474bee1c16c652eed251152870b8dc2f117be2d686ace7016` |

## 告警

- R016：透气度源表未标单位，数值原样保留，设计暂按μm/(Pa·s)记录
- R017：耐折度单位待确认，数值原样写入folding_endurance_raw

## 结论

8份正式来源通过只读预检，可以进入事务化正式入库。透气度和耐折度的单位状态不阻断数值入库。
