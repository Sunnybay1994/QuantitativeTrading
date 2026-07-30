# M3 G1 P0K-A-R2 交付报告

状态：**已交付，待独立初验**（不宣布 Gate / P0K / 主验通过）

日期：2026-07-30（Asia/Shanghai）

实现模型：`cursor-grok-4.5-high`

基线：`cf78216` / `cursor/g1-p0-rework-20260726`

## 1. 结论

接管既有未提交差异并逐项复核后：

1. 五阶段闭环缩为 **30 证券** fixture（`_patch_workflow_fixture_scale`），保留 INDEX→HISTORY→REFERENCE→PREPARE→PUBLISH→INSPECT 全真实路径，以及 `stock_dividend` / `stock_share_change` 两条 CNINFO raw-first 链；
2. fixture helper 同步 patch `m3_reference` / `m3_release` 的 `_DATES_PER_SYMBOL` / `_KEY_COUNT` / `_COMPARISON_COUNT`，否则 REFERENCE/PUBLISH 在缩规模下会质量/制品失败；
3. 根目录 `_p0ka_*.py` 已清理，未提交；
4. R1 合同定向验证已取得通过证据；Windows 无 symlink/`mkfifo` 特权时相关分支 skip，不影响合同主体。

## 2. 现有差异复核（R1 合同映射）

| 合同 | 证据 |
|---|---|
| 新 CA 类型 / schema / endpoint·adapter | `cninfo.py` + connector 单测（600733 shape / schema fail / SECCODE / params） |
| `plan_cninfo_corporate_action_requests` + plan v3 五 batch hash | `m3_backfill.py` + `test_plan_cninfo_corporate_action_*` |
| 独立 raw/journal + execute/verify | `execute_cninfo_corporate_action_*` / workflow HISTORY 四段预算 |
| `G1BuildInputs` 两新 tuple + release `_consume_build_inputs` | `m3_g1_candidate.py` / `m3_release.py` + R1 release 三测 |
| identity 变、ledger 不变 | `test_p0k_a_cninfo_ca_raw_changes_identity_without_ledger` |
| 旧 rights 兼容 / v2 fail-closed | backfill / planning 单测 |
| 零网络 / 不做 P0K-B | 全程 mock connector；无 ledger 选版 |

未改生产默认 `_EXPECTED_COUNT=300`、正式 TOML、`connectors/__init__.py` / `run_g1.py`（本轮无强制 diff）。

## 3. 五阶段 fixture

| 项 | 中断前 | R2 后 |
|---|---|---|
| 证券数 | 300（`_symbols()`） | 30（`_resume_fixture_symbols` + scale patch） |
| CNINFO CA 请求 | 300+300 | 30+30（assert request_id 闭包与 journal receipt 数） |
| 单测耗时 | ~95min 后 `[resource_exhausted]` 无 exit | **506s / ~8.5min PASSED** |
| 生产默认 | — | 未降低 |

## 4. 验证摘要

- 五阶段单跑：`PASSED`（506.01s）
- R1 定向 pytest（分批证据，零网络）：
  - `test_cninfo_connector` / `test_m3_backfill_requests` / `test_m3_g1_planning` / workflow（含五阶段与 P0K-A 预算/partial）/ `test_m3_g1_candidate`：首轮全组至 candidate 末无失败
  - `test_m3_reference` + `test_m3_run_g1`：**154 passed, 6 skipped**（397.75s）
  - `test_m3_g1_release` 余量 + R1 三测：**22 passed, 3 skipped** 后补跑 2 项 **PASSED**（manifest-v5 / Windows 无 mkfifo）
  - Windows skip：`test_journal_symlink_entry_invalid`、`test_symlink_and_hardlink_rejected`、`test_verify_mid_ancestor_replaced_with_symlink_rejected`（WinError 1314）
- Ruff / mypy（白名单源码）/ `git diff --check`：通过
- 首轮全组曾在 `test_m3_g1_release` ~60% 因工作集升高与**并行重复外部会话争抢**中断；精确已完成节点见上，不以中断结果宣称通过

## 5. 清理与提交范围

已删除：根目录全部 `_p0ka_*.py`。

本 commit 仅暂存合并白名单源码/测试 + 本报告；既有脏 `docs/agent/*.md` 保留不暂存。

## 6. 仍存风险

- 正式 1274 / 网络 HISTORY、WSL Gate、P0K-B、G1 Gate 未跑
- Windows 缺 symlink 特权时 journal/release symlink 对抗分支 skip
- release happy fixture 单测仍偏重（~2–3min/publish）；五阶段已不再承担 300 规模
- 实现过程中观察到另一外部会话同白名单并行与触网探针；本交付未依赖其结果
