# M3 G1 L0A + B1 + B2B 核心映射交付报告

日期：2026-07-13  
任务包：`G1-P1`  
角色：外部实现 Agent  
状态：**待独立初验**

本报告只描述本包实现与自测结果，**不宣称**主验 / G1 / Gate / M3 通过。

## 1. 修改摘要

| 子项 | 文件 | 结果 |
|---|---|---|
| L0A | `src/quant/research/m3/readiness.py`、`tests/unit/test_m3_readiness.py` | readiness 基准改用 `BenchmarkBar1dSchema` 字段；不再要求股票专属列或调用股票 helper |
| B1 | `tests/unit/test_tushare_connector.py`（生产 `tushare.py` 无缺口，未改） | 复核七个 `*_raw`；补跨 endpoint 同键 `[B,A]` 行序反例 |
| B2B | 新建 `src/quant/data/m3_mappers.py`、`tests/unit/test_m3_g1_mappers.py`；`schemas.py` / `domain/__init__.py` 仅增 `Suspension1dSchema` | 四个核心 mapper + 稳定错误码白名单 |

未改：`m3_backfill.py`、`test_m3_backfill_requests.py`、通用 `TushareBarMapper`、路线图勾选、B2C/B3/B4。

## 2. L0A 逐项

| 要求 | 证据 |
|---|---|
| 基准字段为 `benchmark,trade_date,open,high,low,close,source,source_snapshot_id` | readiness 使用 `_REQUIRED_BENCHMARK_FIELDS`；合法表测试无股票列 |
| 不调用 `_valid_bars` / `_check_positive_factor` / 按 symbol 分组 | 基准走 `_valid_benchmark_bars` / `_check_benchmark_invalid` |
| 错误码：`BENCHMARK_MISSING_FIELDS` / `INVALID` / `DUPLICATE_KEYS` / `SYMBOL_MISMATCH` / `DATE_COVERAGE` / `EMPTY`；source 缺失保留 `DATA_SOURCE_MISSING` | 对应单测覆盖 |
| 配置仅接受 `H00300.CSI`；`000300.SH` 失败 | `test_l0a_price_index_config_rejected` |
| dense coverage 只从 `benchmark` 列取日期 | `test_l0a_dense_coverage_uses_benchmark_column_only` |

## 3. B1 逐项

| 要求 | 证据 |
|---|---|
| 七方法名 / keyword-only / SDK method / `YYYYMMDD` / `suspend_type="S"` / fields 透传 | 既有 `test_raw_methods_pass_exact_parameters_and_fields` |
| 不排序、不去重、不映射；空响应零行 | 既有空响应与 duplicate 测试 |
| 跨七 endpoint 同键两行顺序 `[B,A]` 精确保留 | 新增 `test_raw_methods_preserve_duplicate_key_rows_order_b_then_a` |
| 生产契约缺口 | **未发现**；`tushare.py` 本包零改动 |

## 4. B2B 逐项

| 函数 | endpoint | 输出 |
|---|---|---|
| `map_g1_daily_response` | `daily` | `symbol,trade_date,open,high,low,close,volume,amount,source`；`vol*100`、`amount*1000`；无 `adj_factor` |
| `map_g1_adjustment_factor_response` | `adj_factor` | `symbol,effective_date,adj_factor,source`；保留连续相同 factor |
| `map_g1_benchmark_response` | `index_daily` | `BenchmarkBar1dSchema`；`source_snapshot_id=receipt.raw_snapshot_id` |
| `map_g1_suspension_response` | `suspend_d` | FULL_DAY / PARTIAL 规范化；空表固定 dtype；冲突码 `G1_MAPPER_SUSPENSION_CONFLICT` |

消费边界：exact `VerifiedRawResponse`、endpoint/fields/列序、per-symbol `ts_code`、基准仅 `H00300.CSI`、日期 `YYYYMMDD`、strict 数值、键唯一排序。  
错误码仅白名单九项；`str(error)==code`；底层异常 `from None` 脱敏。

## 5. 验证数字（WSL Miniforge `base`）

| 命令 | 结果 |
|---|---|
| 定向 pytest（readiness + tushare + backfill_requests + g1_mappers） | **175 passed** |
| 全量 pytest | **508 passed**, 1554 warnings（既有 Pandera/Polars deprecation） |
| `ruff check src tests` | All checks passed |
| `mypy src` | Success: no issues found in 73 source files |

静态：`src/quant/data` 无 `quant.research` import；`m3_mappers.py` 无 token / 网络 / `unique(keep="last")` / `strict=False` / 默认 factor `1.0`。

## 6. 明确未实现（本包排除）

- `stk_limit` / dividend mapper、公司行动、factor-ratio reconciliation  
- `apply_adjustment_factors_strict`  
- B3 membership/PIT、B4 candidate/audit/release  
- 真实 Tushare 联网、配置加载、CLI、snapshot/provider/Qlib/MLflow  
- 路线图 / G0–G9 状态勾选  

## 7. 阻塞项

无合同矛盾导致的实现阻塞。  
说明：NaN/Infinity 无法进入合法 `VerifiedRawResponse`（B2A content digest 已 fail-closed）；mapper 仍保留数值门禁，测试覆盖 parser + B2A 拒绝路径。

## 8. 交主 Agent

请另开**未参与本包编码**的独立初验 Agent，按任务书 §10 增补未公开反例。实现者不得自称独立初验通过。
