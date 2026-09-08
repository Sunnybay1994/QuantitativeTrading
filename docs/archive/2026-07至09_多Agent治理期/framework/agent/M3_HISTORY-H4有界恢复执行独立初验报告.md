# M3 HISTORY-H4 有界恢复执行独立初验报告

角色：外部独立初验 Agent（HISTORY-H4；全新会话；未参与实现）  
来源：[`M3_HISTORY-H4有界恢复执行任务单.md`](M3_HISTORY-H4有界恢复执行任务单.md)、[`M3_HISTORY-H4有界恢复执行交付报告.md`](M3_HISTORY-H4有界恢复执行交付报告.md)  
范围：生产代码 / 实现测试 / README / 配置 / `data` **严格只读**；本文件为唯一写入。  
环境：WSL Miniforge `base`（`/home/mabw/miniforge3/bin/conda run -n base`）。未联网；未跑真实 `status`/`history`；未读改项目 `data/`；未跑全量 pytest / five-stage；未使用 Git。

## 1. 结论

**初验通过（退出码 0）。** 任务单冻结语义与交付实现一致；定向测试与静态检查均绿；实现者未使用的对抗性反例（预算耗尽后非法/不完整尾部 journal 仍须 preflight 拒绝；`max_new_requests=True`）通过。不宣称主验 / Gate / 真实 HISTORY 通过。

## 2. 逐项核对

| # | 冻结项 | 证据 | 结论 |
|---|---|---|---|
| 1 | `max_new_requests` 严格正整数（`type is int` 且 `>0`）；拒 `True/0/-1/1.0/"1"` | `m3_backfill._validate_max_new_requests`；`g1_workflow.run_g1_history_stage` 入口；CLI `_parse_cli_max_new_requests`；`test_max_new_requests_rejects_illegal_before_fs_or_api` / `test_history_max_new_rejects_illegal_before_side_effects` / `test_history_max_new_requests_illegal_cli_rejected`；ADV2 | 通过 |
| 2 | 只计本轮新 committed identity；恢复已有 receipt 不计 | `new_requests_committed += 1` 仅在成功写 receipt 后；`test_bounded_max_new_skips_existing_receipts_and_resumes`（114 不计后额） | 通过 |
| 3 | 同 identity 内 retry 不改变计数 | `test_bounded_retry_counts_one_committed_identity`（3 attempts → committed=1）；永久失败不计 committed | 通过 |
| 4 | 达上限后下一缺失 identity 零 journal/raw 增量 | 预算耗尽且 `not dir_exists` → `continue`；`test_bounded_budget_next_missing_has_zero_journal_raw_delta`；ADV_phase | 通过 |
| 5 | 第二次 `N=2` 从断点新增而非重复 | `test_bounded_resume_second_call_adds_two_new_not_repeat`；workflow `test_history_bounded_incomplete_then_resume_success` | 通过 |
| 6 | 有界未完成 `INCOMPLETE`/exit 0；完成 `SUCCESS`/0；completed stages 未完成时仅 INDEX | `run_g1.py` history 分支；`test_history_max_new_incomplete_and_success_outcomes`；workflow 有界用例 | 通过 |
| 7 | 无上限未完成仍 `G1_WORKFLOW_HISTORY_INCOMPLETE` fail-closed | `test_history_unbounded_incomplete_still_fail_closed` | 通过 |
| 8 | CLI JSON：`max_new_requests`/`new_requests_committed` 进严格值对象；status 等为 null/0 | `G1CliResultV1.__post_init__`；`_result_mapping`；status key 集合与 null/0 断言 | 通过 |
| 9 | 禁止 break 跳过尾部非法 journal | 循环用 `continue` 非 `break`；预算后仍 `_validate_journal_files` / receipt 完整性 / `_preflight_no_receipt`；ADV 反例 | 通过 |

## 3. 定向验证（任务单命令）

| 命令 | 退出码 | 摘要 |
|---|---|---|
| `pytest tests/unit/test_m3_backfill_requests.py -q -k 'bounded or max_new or resume'` | **0** | 6 passed, 125 deselected |
| `pytest tests/unit/test_m3_g1_workflow.py -q -k 'history and not five_stage'` | **0** | 6 passed, 17 deselected（~358s，仅 tmp fixture） |
| `pytest tests/unit/test_m3_run_g1.py -q -k 'history or max_new'` | **0** | 3 passed, 33 deselected |
| `ruff check`（任务单路径） | **0** | All checks passed |
| `mypy`（三生产模块） | **0** | no issues |

## 4. 对抗性反例（`/tmp`，实现者未使用）

脚本：`/tmp/h4_adversarial_preflight.py`、`/tmp/h4_adversarial_preflight3.py`（不入库）。

### ADV-A：预算耗尽 + 尾部非法/不完整 journal

**场景（同一次调用）**：batch=4；尾部预先植入 `evil.bin` 或仅有 `receipt.json`（无 intent/candidate）；`max_new_requests=2`。

| 观察 | 结果 |
|---|---|
| 前 2 个缺失 identity 提交后预算耗尽 | api_calls==2，对应 receipt 存在 |
| 下一缺失 identity | 目录不存在，零新建 |
| 尾部非法/不完整 | 分别抛出 `JOURNAL_UNKNOWN_OR_NON_REGULAR_ENTRY` / `COMMITTED_JOURNAL_INCOMPLETE` |
| 拒绝路径上对尾部 identity | 无 API、无 receipt/intent/candidate/raw 增量 |

**判定**：通过。满足任务单「预算到达后非法尾部 journal 仍须被 preflight 拒绝」，且在预算耗尽之后对剩余 identity **零进一步 API/新写入**。

说明：实现为循环内逐项校验（`continue` 保留尾部检查），而非调用入口一次性全计划扫描。若把「全局 preflight」升级为「整次调用在任何写入前先扫完全部 journal」，当前实现不满足该更强解释；该解释超出任务单反例原文「预算到达后…仍须被 preflight 拒绝」，**不作为本轮初验失败项**，记供主验酌定。

### ADV-B：`max_new_requests=True`

- 抛出 `ValueError: max_new_requests 必须是严格正整数`
- `connector.calls==0`；journal/raw 未创建
- `type(True) is int == False`（`type is int` 守卫有效）

**判定**：通过。

## 5. 范围与未验

- 未越权改白名单外 contract（只读核对）。
- 未验证真实网络、真实 data、真实 HISTORY 恢复；不得据此勾选 Gate。
- 初验未修改任何生产/测试代码。

## 6. 下一步

交主 Agent 终验（契约、跨模块不变量、文档一致性；按需决定是否采纳更强「写入前全计划 journal 扫描」解释）。
