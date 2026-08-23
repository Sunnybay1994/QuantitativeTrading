# M3 G1-P1 主 Agent 最终验收报告

日期：2026-07-14  
结论：**G1-P1 通过主 Agent 最终验收**  
边界：只通过 L0A readiness、B1 raw endpoint 复核、B2B 核心 mapper；不关闭 L0/B1/B2/G1/M3 或任何 Gate

## 1. 完整证据链

| 阶段 | 证据 |
|---|---|
| 原冻结任务 | [`M3_G1_L0A_B1_B2B核心映射外部闭环任务单.md`](M3_G1_L0A_B1_B2B核心映射外部闭环任务单.md) |
| 首次实现/独立初验 | [`M3_G1_L0A_B1_B2B核心映射交付报告.md`](M3_G1_L0A_B1_B2B核心映射交付报告.md)、[`M3_G1_L0A_B1_B2B核心映射独立初验报告.md`](M3_G1_L0A_B1_B2B核心映射独立初验报告.md) |
| 主验一次返工 | [`M3_G1_P1主验一次返工任务单.md`](M3_G1_P1主验一次返工任务单.md)及其两轮交付、[`M3_G1_P1主验一次返工独立复验报告.md`](M3_G1_P1主验一次返工独立复验报告.md) |
| 主验二次返工 | [`M3_G1_P1主验二次返工任务单.md`](M3_G1_P1主验二次返工任务单.md)、[`M3_G1_P1主验二次返工交付报告.md`](M3_G1_P1主验二次返工交付报告.md)、[`M3_G1_P1主验二次返工独立复验报告.md`](M3_G1_P1主验二次返工独立复验报告.md) |

职责分离成立：外部实现者与独立验收者不同；两次主验发现均回到外部实现—独立复验循环，没有由主 Agent
直接修改生产代码。

## 2. 最终源码结论

### L0A readiness

- benchmark 先做 required-column gate；extra column 保留 `BENCHMARK_INVALID`；
- 必需列投影先由生产 `BenchmarkBar1dSchema.validate` 验真；
- source、duplicate、identity 和 coverage 只消费 Schema 返回的 coerced frame；
- 不可 coercion 的 `source/benchmark/date` dtype 不向外抛 Polars/Pandera 异常；
- extra+合法投影仍能继续收集独立的日期覆盖错误；缺列不会触发二次字段访问。

### B1 raw endpoint

七个 `*_raw` endpoint 保持单次 API、原字段/行序/重复行，不在 raw 前映射、排序或去重。本轮返工未改 B1
生产实现，原 G1-P1 复核结论保持有效。

### B2B mapper

四个公开 mapper 在读取行值前统一重建 exact `VerifiedRawResponse`，重新证明 spec/receipt/hash/frame 内容
闭包；frame、receipt 或 parameters 构造后漂移均稳定拒绝为 `G1_MAPPER_RESPONSE_INVALID`，不泄露 cause、
路径或凭据。daily 单位换算、factor 逐日保留、benchmark 独立 Schema 和 suspension 规范化未退化。

## 3. 主 Agent 独立反例

本次未复用外部报告的精确 dtype：

| 反例 | 结果 |
|---|---|
| `source=Binary` | 不抛异常；由 Schema coercion 后进入正常 source/coverage 语义 |
| `benchmark=Binary` | 不抛异常；由 Schema coercion 后进入正常 identity/coverage 语义 |
| extra column + `trade_date=List[Date]` | 不抛异常；fail-closed 为 `BENCHMARK_INVALID` |
| 构造后修改 receipt `response_content_sha256` | `G1_MAPPER_RESPONSE_INVALID`，`__cause__ is None` |

原四个 `Int32/List` P1-C 反例、extra+coverage 双码和 mapper frame/receipt/spec drift 也由实现测试与独立
复验覆盖。

## 4. 主 Agent 验证结果

全部使用 WSL Miniforge base：

| 验证 | 结果 |
|---|---|
| readiness/connector/backfill/mappers 定向 | **197 passed** |
| 全量 `pytest -q` | **530 passed** |
| Ruff | **All checks passed** |
| mypy | **73 source files，0 issues** |
| 主 Agent 隐藏反例 | 全部通过 |

Pandera/Polars 产生 1989 条既有 deprecation warnings，不影响本次结果；Windows PowerShell profile 的本机
Conda hook 噪声发生在 WSL 命令完成之后，WSL 命令自身均为 exit 0。

## 5. 已知非阻断项

`BenchmarkBar1dSchema` 的唯一键检查现在先于 readiness 专用 duplicate helper，因此重复
`(benchmark,trade_date,source)` 仍会 fail-closed，但当前返回通用 `BENCHMARK_INVALID`，不再返回冻结任务中
更精确的 `BENCHMARK_DUPLICATE_KEYS`。这不允许坏数据进入研究链，也不改变信号、单位、血缘或交易结果，
按“抓大放小”记录为 **P2 诊断精度债务**，不阻塞 G1-P1；在 B4 统一质量报告/错误分类时恢复专用码并增加
回归测试。

## 6. 状态边界与下一依赖

本报告只把任务包 `G1-P1` 标为已通过。L0 仍需完整标签/真实数据链终验，B1 仍需真实范围接口证据，B2 仍
缺 B2C，G1 仍缺 B2C、B3、B4、真实全量抓取、跨源对账与 immutable release。因此路线图和 G0–G9 Gate
均不更新。下一主依赖按当前总览进入 B2C 规则 mapper、B3 PIT 与 B4 audit/release。

