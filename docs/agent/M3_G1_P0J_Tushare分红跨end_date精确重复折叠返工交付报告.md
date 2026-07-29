# M3 G1 P0J：Tushare 分红跨 end_date 精确重复折叠返工 — 交付报告

## 结果

- 状态：已交付（实现 + 自测；**不宣称 Gate / 主验 / 独立初验通过**）
- 实现基线：`0683bdc`（Freeze G1 P0J cross-end dividend duplicate fold）
- 角色：外部实现 Agent；不兼任独立初验
- 修改文件及目的：
  - `src/quant/data/m3_execution_facts.py`：在进入既有 economic `groups` 前增加跨 `end_date` 精确重复折叠；canonical `end_date=max`；`raw_row_count` 累计全部原始行；selection version 升级为 v6
  - `tests/unit/test_m3_execution_facts.py`：覆盖 §8 最小复现、阻断折叠、600930 双事件修订、对账只累加一次、v5 钉扎失败
  - `docs/agent/M3_G1_P0J_Tushare分红跨end_date精确重复折叠返工交付报告.md`：本报告
- 明确未修改：任务书、Schema、candidate/planning/release/workflow/CLI/config/connector、正式 data/raw/receipt/journal、ignored artifacts、其他 docs

## 设计与合同证据

| 成功标准 | 实现 / 测试证据 |
| --- | --- |
| 仅 `end_date` 不同的精确重复折为一事件，canonical=`max(end_date)`，`raw_row_count` 为总行数 | `_fold_dividend_cross_end_exact_duplicates` + `test_dividend_cross_end_exact_fold_600733_shape` / `_three_ends_order_independent` / `_with_same_end_duplicates_counts_all` |
| `ann_date` 等任一正式字段不同不折叠（600930 形状） | 修订 `test_dividend_distinct_end_dates_same_ex_fields_pass_closure`；`test_dividend_cross_end_exact_fold_blocked_by_provenance_fields` |
| 输入顺序不影响 digest | 三端点正序/逆序/乱序 digest 相等 |
| 送股只计一次并通过 declared 对账 | `test_dividend_cross_end_exact_fold_reconcile_stock_once` → `MATCHED_EVENT_DECLARED_FORMULA`，`event_count=1`，`stock_ratio=2.5` |
| selection version 精确 v6，旧 v5 不能冒充 | 常量 `..._cross_end_exact_fold_v6`；`test_version_constants` 正向等于 v6 且不等于 v5 |
| 哈希字段公式/标签不变；既有分组、冲突、closure 路径保留 | `_economic_event_key_sha256` / `_candidate_id_sha256` / `_event_id_sha256` 未改标签；折叠后仍走 `_fold_identical_candidates` 与既有 rank/conflict |

关键假设确认：

- 精确身份在 selector 内以窄 helper 表达全部正式字段（除 `end_date`），不另建 endpoint 字段 SSOT 副本。
- 决策腿仍用 `_parse_dividend_leg_amount`；身份数值用 `_parse_strict_scalar(allow_null=True)`，`null`≠`0`。
- 未发现与冻结 fingerprint / Schema 的冲突，无需停止扩大。

与原计划不同之处：无。任务书正文写实现基线 `f34e3c6`，本轮按主 Agent 冻结提交 `0683bdc` 执行。

## 验证

Windows 反馈环：`D:\Miniforge3\python.exe`；默认零网络；未运行正式 full status。

| 命令或检查 | 结果 | 证据摘要 |
| --- | --- | --- |
| `pytest tests/unit/test_m3_execution_facts.py -k "dividend or corporate_action_selection or reconciliation or version_constants" -q` | 通过 | `21 passed, 107 deselected` |
| `ruff check src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py` | 通过 | All checks passed |
| `mypy src/quant/data/m3_execution_facts.py` | 通过 | Success: no issues found in 1 source file |
| `git diff --check`（本轮白名单三文件） | 通过 | 无 whitespace 错误 |

## 清理与范围审查

- 无临时代码、诊断脚本或第二套 selection 路径
- 工作区既有其他 modified docs **保留且未暂存**
- 范围外改动：无（仅三白名单文件）

## 风险与交接

- 已知限制：未跑正式 637-response 零网络 selection/status；未跑 WSL Gate；不对下一正式首败做裁定
- 安全 / 回滚：纯派生选择语义；raw/receipt/journal 未改写；回滚即还原本提交三文件
- 下一步：未参与实现的外部独立初验 Agent 写 `M3_G1_P0J_Tushare分红跨end_date精确重复折叠独立初验报告.md`；初验 PASS 后由主 Agent 终验
