# M3 G1 L0A + B1 + B2B 核心映射独立初验报告

日期：2026-07-13  
任务包：`G1-P1`  
角色：**外部独立验收 Agent**（未参与本包任何编码）  
权威任务书：[`M3_G1_L0A_B1_B2B核心映射外部闭环任务单.md`](M3_G1_L0A_B1_B2B核心映射外部闭环任务单.md)  
实现线索（不作证明）：[`M3_G1_L0A_B1_B2B核心映射交付报告.md`](M3_G1_L0A_B1_B2B核心映射交付报告.md)  
SSOT：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.1、§4.10

## 结论

**G1-P1 外部闭环通过，可交主 Agent 终验**

本报告不宣称 L0 / B1 / B2 / G1 / M3 / Gate 最终通过。无未关闭 P0 / P1。

## 1. L0A 证据映射（readiness 基准契约）

| 任务书要求 | 源码证据 | 核验 |
|---|---|---|
| 基准字段精确为 `BenchmarkBar1dSchema` 列集 | `readiness.py` `_REQUIRED_BENCHMARK_FIELDS`（L33–42） | 通过 |
| 不要求 `symbol/volume/amount/adj_factor`；不调用股票 `_valid_bars` / `_check_positive_factor` / 按 symbol 分组 | 基准走 `_valid_benchmark_bars` / `_check_benchmark_invalid` / `_check_duplicate_benchmark_keys`；`_check_positive_factor` 仅作用于 `selected_bars` | 通过 |
| 错误码：`MISSING_FIELDS` / `INVALID` / `DUPLICATE_KEYS` / `SYMBOL_MISMATCH` / `DATE_COVERAGE` / `EMPTY`；source 缺失保留 `DATA_SOURCE_MISSING` | L94–165、L171–185、L498–505、L573–586 | 通过 |
| M3 v1 仅 `H00300.CSI`；`000300.SH` 配置失败 | `_M3_BENCHMARK` + L177–183；单测 `test_l0a_price_index_config_rejected` | 通过 |
| 混入另一 benchmark / 另一 source：按配置选择、不静默混用 | source 先过滤；选中源内混入 → `BENCHMARK_SYMBOL_MISMATCH` | 通过 |
| dense coverage 只从 `benchmark` 列取日期；训练 session 不回退股票 helper | `_check_dense_coverage`：`bench_dates` 来自 `_valid_benchmark_bars(...filter(benchmark==))`；`trainable` 要求 `day in bench_dates` | 通过 |
| 缺前置列跳过依赖检查、不向外抛 Polars/Pandera | `audit_m3_readiness` 结构化 issue 列表；契约错误路径不 raise | 通过 |

§10.7 对抗：合法基准表无股票专属列；区间外行（`2026-01-07`）不能补足区间内缺口（`2026-01-06`）→ 出现 `BENCHMARK_DATE_COVERAGE`。

## 2. B1 证据映射（七个 raw endpoint）

| 任务书要求 | 源码证据 | 核验 |
|---|---|---|
| 七方法名、keyword-only、SDK method 对应 | `tushare.py`：`fetch_index_weight_raw` / `fetch_daily_raw` / `fetch_adj_factor_raw` / `fetch_index_daily_raw` / `fetch_suspend_raw` / `fetch_stk_limit_raw` / `fetch_dividend_raw`（均 `*,` keyword-only） | 通过 |
| 日期 `YYYYMMDD`；`suspend_d` 固定 `suspend_type="S"`；`fields` 原串透传 | `_date()` → `%Y%m%d`；`suspend_d(..., suspend_type="S", fields=fields)` | 通过 |
| 不排序、不去重、不映射；空响应零行；ALLOW/REJECT 不在 connector | raw 直接 `_to_polars(client.*)`；既有空响应与 duplicate 单测 | 通过 |
| 跨七 endpoint 同键 `[B,A]` 行序精确保留 | `test_raw_methods_preserve_duplicate_key_rows_order_b_then_a`：七帧 `row_id==["B","A"]`，值/列序/行序相等，不要求同一对象引用 | 通过 |
| fake client 不初始化 token | 既有 connector 单测经 `pro_client=` 注入 | 通过 |

本包交付报告称 `tushare.py` 无契约缺口、零改动；独立验收按现源码与测试复核，未发现 B1 合同缺口。

## 3. B2B 证据映射（四核心 mapper）

| 任务书要求 | 源码证据 | 核验 |
|---|---|---|
| 仅公开四函数 + `M3G1MappingError`；只接受 exact `VerifiedRawResponse` | `m3_mappers.py`；`_prepare`：`type(response) is not VerifiedRawResponse` → `G1_MAPPER_RESPONSE_INVALID`；SimpleNamespace 拒绝（独立 spot-check） | 通过 |
| 输出列序 / key / sort / `source="tushare"` | `_DAILY_OUT` / `_FACTOR_OUT` / `_BENCH_OUT` / `_SUSP_OUT` + 对应 sort | 通过 |
| daily 无 `adj_factor`；`vol*100`、`amount*1000` | 输出列无 factor；spot-check `vol=1.5→150`、`amount=2.5→2500` | 通过 |
| factor 保留连续相同值；benchmark/suspension `source_snapshot_id=receipt.raw_snapshot_id` | `map_g1_adjustment_factor_response` 不去重因子；benchmark/suspension 写 `snapshot` | 通过 |
| 消费边界：endpoint/fields/列序、per-symbol `ts_code`、基准仅 `H00300.CSI`、日期 `YYYYMMDD`、strict 数值、键唯一 | `_prepare` / `_require_a_share` / `_parse_finite_number`（拒绝 str/bool/null/non-finite）/ `_reject_duplicate` | 通过 |
| suspension FULL/PARTIAL 规范化；冲突码；空表固定 dtype | `map_g1_suspension_response`；`Suspension1dSchema` 于 `schemas.py` 并自 `quant.domain` 导出 | 通过 |
| 九个稳定错误码；`str(error)==code`；`from None` 脱敏 | `_ERROR_CODES`；`_sanitize` 丢弃底层 message/cause | 通过 |
| 不 import `quant.research`；无 class hierarchy / 插件 | 模块仅 import `m3_backfill` + `domain` | 通过 |

## 4. §10 未公开变体对抗（真实 `VerifiedRawResponse`）

临时脚本：`/tmp/g1p1_s10_adversarial.py`（验收后已清理）。全部构造真实 `VerifiedRawResponse`，未使用 `SimpleNamespace`。

| # | 变体 | 结果 |
|---|---|---|
| 1 | per-symbol daily frame 混入第二合法 A 股 | **PASS** → `G1_MAPPER_REQUEST_SCOPE_MISMATCH` |
| 2 | benchmark 请求合法，frame 混入 `000300.SH` | **PASS** → `G1_MAPPER_REQUEST_SCOPE_MISMATCH` |
| 3 | 数值列为 decimal-looking string（`open="10.5"`） | **PASS** → `G1_MAPPER_VALUE_INVALID`（strict，不吞错） |
| 4 | suspension 两 partial detail 输入顺序相反 | **PASS** → 同为 `上午停牌 \| 下午停牌` |
| 5 | 全部 FULL 重复 raw 三行 | **PASS** → raw 高=3，映射 1 行 `FULL_DAY` |
| 6 | PolarsError message 注入绝对路径/token/行内容 | **PASS** → `str/repr/code/format` + traceback 无泄露；`__cause__ is None` |
| 7 | 合法基准无股票列；区间外行不补区间内缺口 | **PASS** → `BENCHMARK_DATE_COVERAGE` |
| 8 | import spy：无 `quant.research` 反向依赖、无 token/网络 | **PASS** |

合计：**8 passed, 0 failed**。

## 5. 静态检查

| 检查项 | 结果 |
|---|---|
| `src/quant/data` 不 import `quant.research` | **通过**（`rg` 无匹配） |
| `m3_mappers.py` 无 `strict=False` | **通过** |
| `m3_mappers.py` 无默认 `adj_factor=1.0` | **通过** |
| `m3_mappers.py` 无 `unique(keep="last")` | **通过** |
| 异常脱敏（§10.6 + 实现单测路径） | **通过** |
| 无 token / `configs/tushare` / 网络调用侧写 | **通过**（§10.8） |

说明：既有通用 `mappers.py` / `connect_market.py` 中的 `strict=False` 不在本包 B2B 边界内，未计入本包失败。

## 6. §11 命令表（WSL Miniforge `base`）

| 命令 | 退出码 | 真实数字 |
|---|---|---|
| `pytest tests/unit/test_m3_readiness.py tests/unit/test_tushare_connector.py tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_g1_mappers.py -q` | **0** | **175 passed**, 375 warnings |
| `pytest -q`（全量） | **0** | **508 passed**, 1554 warnings |
| `ruff check src tests` | **0** | All checks passed |
| `mypy src` | **0** | Success: no issues found in **73** source files |

Warnings 主要为既有 Pandera/Polars `how='horizontal'` deprecation，非本包回归失败。

## 7. 已知限制（非阻塞）

1. 本包明确排除 B2C/B3/B4、真实联网 Tushare、CLI/release、路线图勾选；独立验收未扩大范围。
2. NaN/Infinity 无法进入合法 `VerifiedRawResponse`（B2A content digest fail-closed）；mapper 仍保留数值门禁；§10.3 以 decimal-looking string 验证 strict 拒绝路径。
3. readiness 对基准以列契约 + `_check_benchmark_invalid` 实现门禁，不直接调用 `BenchmarkBar1dSchema.validate()`；与任务书错误码语义及 L0A 单测一致。
4. 未宣称 L0/B1/B2/G1/M3/Gate 最终通过；主 Agent 仍须复核源码、未公开反例、全量回归与跨模块不变量。

## 8. 缺陷分级

无未关闭 P0 / P1 / P2 / P3。

## 9. 交主 Agent

请主 Agent 按任务书 §12 做最终复核。独立初验允许声明仅为本句：

**G1-P1 外部闭环通过，可交主 Agent 终验**
