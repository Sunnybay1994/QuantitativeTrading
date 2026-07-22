# M3 G1-P3 B2C 执行事实交付报告

日期：2026-07-14  
角色：外部实现 Agent（非独立初验）  
实际模型标识：`cursor-grok-4.5-high`  
任务书：[`M3_G1_P3_B2C执行事实外部闭环任务单.md`](M3_G1_P3_B2C执行事实外部闭环任务单.md)  
状态：**实现与自测完成，待独立初验**（不得视为 B2/P3/G1/Gate 通过）

## 1. 范围与边界

本交付只实现 G1 B2C 执行事实层：

- `stk_limit` → suspension-aware 涨跌停映射与持仓延续覆盖域；
- `dividend` 先按 `ex_date` 裁剪 `HistoryWindow`，再做实施事件选版；
- 以 verified `daily.pre_close` 为主门禁的 factor reconciliation（三类 MATCHED + NO_EVENT）；
- 收紧 `CorporateActionLedgerSchema`，新增 selection/reconciliation Schema；
- C0 `factor_ratio_rtol` 上限 `0.01`。

未启动 P4/G2；未更新路线图或 Gate；未修改 P2/B2A/B2B 已验收生产代码；未读取 `_old/` 或 token
配置；未联网。

## 2. 修改文件清单

| 文件 | 变更 |
|---|---|
| `src/quant/data/m3_execution_facts.py` | **新增** B2C 纯函数、result、错误码与版本常量 |
| `src/quant/domain/schemas.py` | 收紧 ledger；新增 selection/reconciliation Schema |
| `src/quant/data/__init__.py` | 仅新增 B2C 导出 |
| `src/quant/domain/__init__.py` | 仅新增两个 Schema 导出 |
| `src/quant/research/m3/config.py` | `factor_ratio_rtol` 增加 `maximum=0.01` |
| `tests/unit/test_m3_execution_facts.py` | **新增** 实现者测试矩阵 |
| `tests/unit/test_schemas.py` | ledger 收紧与新 Schema 回归 |
| `tests/unit/test_m3_config.py` | rtol 上界回归 |
| `docs/M3_G1_P3_B2C执行事实交付报告.md` | 本报告 |

## 3. 冻结签名与行为要点

版本常量：

- `G1_PRICE_LIMIT_METHOD_VERSION = "tushare_stk_limit_suspension_aware_v1"`
- `G1_CORPORATE_ACTION_SELECTION_VERSION = "tushare_dividend_implemented_latest_v1"`
- `G1_CORPORATE_ACTION_RECONCILIATION_VERSION = "tushare_factor_daily_preclose_v1"`

公开接口：

- `map_g1_price_limit_response` / `require_g1_price_limit_coverage`
- `select_g1_corporate_actions` / `verify_corporate_action_selection_result`
- `reconcile_g1_corporate_actions` / `verify_corporate_action_reconciliation_result`
- `CorporateActionSelectionResult` / `CorporateActionReconciliationResult`
- `M3G1ExecutionFactError`

关键不变量：

1. 读值前重建 `VerifiedRawResponse`（及全部 daily responses）；Schema `validate` 返回 frame 写回 result；
2. null/zero `pre_close` sentinel 不进 clean；coverage 仅 FULL_DAY 豁免；mapper 永不发
   `has_price_limit=False`；
3. dividend 先裁范围再验结算；空窗合法空 ledger/evidence；null ann/imp total order；同 rank 冲突失败；
4. reconciliation 主门禁用 raw `pre_close`；三类 MATCHED + `NO_EVENT_STABLE_FACTOR`；digest 复用 P2
   `clean_table_content_sha256`。

## 4. 实现者自测覆盖

`tests/unit/test_m3_execution_facts.py` 覆盖任务书第 13 节矩阵要点：identity drift、列/scope/sentinel、
coverage（next session / FULL_DAY / PARTIAL / delist / false）、窗口内外 dividend、选版顺序/重复/冲突、
event/candidate identity、result frame/hash drift、declared/market/no-market-reference、无事件 jump、
gap 事件、rtol 边界、daily identity、digest 行序稳定、脱敏与 import 隔离。

## 5. 验证结果（WSL Miniforge `base`）

全部经 `wsl.exe` → `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` →
`/home/mabw/miniforge3/bin/conda run -n base`；禁止 Windows Python/conda。

| 命令 | 结果 |
|---|---|
| 定向 pytest（execution_facts/schemas/config/backfill/mappers/membership/identity） | **305 passed** |
| 全量 `python -m pytest -q` | **595 passed**，3921 条既有 Pandera/Polars deprecation warnings |
| `python -m ruff check src tests` | **All checks passed** |
| `python -m mypy src` | **76 source files，0 issues** |

C0：示例 `factor_ratio_rtol=0.001` 仍合法；`0.011` 被 config validator 拒绝。

## 6. Import 隔离、联网与脱敏

- `m3_execution_facts.py` 无 `quant.research`、无 `qlib`、无网络客户端、无配置路径读写；
- 本次未联网、未读 token/ignored 凭据配置、未写 raw/clean；
- `str/repr/__cause__` 仅为稳定错误码；恶意路径/`token=` 字符串不进入公开消息。

## 7. 已知限制与未实现项

- 未实现 B4 candidate/audit/release、跨源 BaoStock、Qlib、标签、回测或交易；
- 自包含 result verifier 不能单独证明“另一套内部自洽替换仍来自原 response”；B4 须从冻结输入重算；
- 未宣称价格限制历史完备或差异化分红逐公告分类；`MATCHED_EVENT_MARKET_REFERENCE` 仅留痕。

## 8. 交付声明

本报告只证明：冻结范围内实现已完成，且实现者自测与任务书验证命令通过。

**待未参与实现的独立初验 Agent 审查并出具**
[`M3_G1_P3_B2C执行事实独立初验报告.md`](M3_G1_P3_B2C执行事实独立初验报告.md)。

**不宣称 B2 / P3 / G1 / 任一 Gate 通过。**
