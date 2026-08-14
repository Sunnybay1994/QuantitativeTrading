# M4 P8 RUN-0B2G-F1 R1 Formal LedgerContextProvider 任务单

状态：主 Agent 串行实现与 Windows 开发检查完成；缺 honest current G1 retained source，正式日历 Gate 仍开放。

## 1. 目标

从 fresh `VerifiedG1Release` 的 v5 `trade_calendar.parquet` 构造 formal A 股 ledger context provider，并绑定 RUN-0B2G-F0 OMS capability。它为既有 `ExecutionService` 提供每个 command 所需的 exact `SettlementRule`，不接受 caller 自报 sessions/source identity。

## 2. 契约

1. public loader 只接受 exact execution-store capability、exact `VerifiedG1Release` 与 aware UTC `now`；先 fresh 验真两者。
2. 只接受 `G1ManifestV5`，calendar path 只从 verified artifact map 派生；stable 双读，物理 `(market,date)` 严格有序唯一，Schema 与 manifest entry/bytes一致。
3. 只选择 SH/SZ open sessions；两市场 session 域必须 exact 相等、非空。source identity绑定 release id、manifest sha、calendar bytes/content sha与有序 sessions。
4. provider 是 process-local capability；`context_for(command)` 每次 fresh 验真 store/release/calendar，再按 command market构建既有 `SettlementRule`。仅 SH/SZ、CNY、settlement lag 0、sellable lag 1、不可复用卖出应收；selector exact取 formal policy `a_share_rule_selector`。
5. command session必须属于已验真域；无 FX。所有失败稳定为 `PAPER_FORMAL_LEDGER_CONTEXT_INVALID`，cause/context为空。

## 3. 边界

本包不选择 expected soak window，不创建 schedule/runner/service，不写文件，不读取 data root，不修改 ledger 公式或 G1 发布物。没有 honest retained/current G1 时只能表述为工程能力完成，不能宣称正式日历 Gate。

## 4. 白名单与检查

- 新 `src/quant/execution/paper_formal_ledger.py`
- `src/quant/execution/__init__.py` lazy export
- 新 `tests/unit/test_paper_formal_ledger.py`
- 本任务单与唯一交付报告

正常检查：focused unit、B2G-F0/gateway/service邻接、Ruff、mypy、cold import、diff-check。
