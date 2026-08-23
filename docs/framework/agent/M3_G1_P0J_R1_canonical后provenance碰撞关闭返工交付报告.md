# M3 G1 P0J-R1：canonical 后 provenance 碰撞关闭返工 — 交付报告

## 结果

- 状态：已交付（实现 + 自测；**不宣称独立复验 / 主验 / Gate / 正式 status 通过**）
- 返工基线：`8e47d4f`（Freeze G1 P0J R1 provenance collision closure；上游 FAIL `af76cee`，上游实现 `f467c1a`）
- 角色：外部返工实现 Agent；不兼任独立复验
- 修改文件及目的：
  - `src/quant/data/m3_execution_facts.py`：cross-end exact fold 输出携带 `exact_identity`；`_fold_identical_candidates` 仅在 rank + decision + exact identity 全同时累加 `raw_row_count`，同 rank 下任一差异 fail-closed 为 `G1_CORPORATE_ACTION_VERSION_CONFLICT`
  - `tests/unit/test_m3_execution_facts.py`：覆盖 A∪B 最小复现、仅 A1+A2 仍折叠、同 end provenance 冲突、同 end exact 累计、输入顺序无关
  - `docs/framework/agent/M3_G1_P0J_R1_canonical后provenance碰撞关闭返工交付报告.md`：本报告
- 明确未修改：上游 P0J 任务/交付/初验报告、其他已有 modified docs、Schema、哈希标签、selection version（仍为 v6）、mapper/reconciliation/candidate/planning/release/workflow/CLI/config/connector、正式 data/raw/receipt/journal、ignored artifacts

## 设计与合同证据

| 成功标准 | 实现 / 测试证据 |
| --- | --- |
| A1+A2+B 不再静默合并，稳定抛 `G1_CORPORATE_ACTION_VERSION_CONFLICT` | `test_dividend_post_canonical_provenance_collision_fail_closed` |
| 仅 A1+A2 仍折一事件，canonical max，`raw_row_count=2` | `test_dividend_cross_end_exact_fold_a1_a2_only_still_folds` |
| 同 end、同 rank/decision、仅 `base_share` 不同 → 同一冲突码 | `test_dividend_same_end_provenance_collision_fail_closed` |
| 同 end 完全 exact duplicate 仍累加 `raw_row_count` | `test_dividend_same_end_exact_duplicates_still_accumulate` |
| 输入顺序反转冲突码不变 | `test_dividend_post_canonical_provenance_collision_order_independent` |
| exact identity 复用 `_dividend_cross_end_exact_identity`，不进 Schema/公开字段 | wrapper 字段仅内部选择使用；无 Schema/digest 改动 |
| 保留 v6、canonical max、哈希和 Schema | 常量仍为 `..._cross_end_exact_fold_v6`；`test_version_constants` 继续通过 |
| 既有 600733/600930/null≠0/provenance 阻断/版本冲突/对账/v6 | 定向集既有用例继续通过 |

关键实现要点：

- 不建第二套 selector；只打通 `_fold_dividend_cross_end_exact_duplicates` → `_fold_identical_candidates` 的 identity 传递。
- 同 rank 且 `fold_key` 不同（decision 或 exact identity 任一不同）一律 `VERSION_CONFLICT`，与任务书 fail-closed 裁定一致。
- 未读取正式诊断产物或硬编码扫描计数。

与原计划不同之处：无。

## 验证

Windows 反馈环：`D:\Miniforge3\python.exe`；默认零网络；未运行正式 full status。

| 命令或检查 | 结果 | 证据摘要 |
| --- | --- | --- |
| `pytest tests/unit/test_m3_execution_facts.py -k "dividend or corporate_action_selection or reconciliation or version_constants" -q` | 通过 | `26 passed, 107 deselected`（较 P0J 实现多 5 个 R1 用例） |
| `ruff check src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py` | 通过 | All checks passed |
| `mypy src/quant/data/m3_execution_facts.py` | 通过 | Success: no issues found in 1 source file |
| `git diff --check`（本轮白名单三文件，相对 `af76cee`） | 通过 | 无 whitespace 错误 |

## 清理与范围审查

- 无临时代码、诊断脚本或第二套 selection 路径
- 工作区既有其他 modified docs **保留且未暂存**
- 范围外改动：无（仅三白名单文件）

## 风险与交接

- 已知限制：未跑正式 637-response 零网络 selection/status；未跑 WSL Gate；不裁定下一正式首败
- 安全 / 回滚：纯派生选择语义；raw/receipt/journal 未改写；回滚即还原本提交三文件
- 下一步：未参与本轮实现的外部独立复验 Agent 写 `M3_G1_P0J_R1_canonical后provenance碰撞关闭独立复验报告.md`；复验 PASS 后方可进入主验
