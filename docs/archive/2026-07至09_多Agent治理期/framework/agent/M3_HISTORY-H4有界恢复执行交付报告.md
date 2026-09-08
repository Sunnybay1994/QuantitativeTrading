# M3 HISTORY-H4 有界恢复执行交付报告

角色：外部实现 Agent（HISTORY-H4；全新会话；cursor-grok-4.5-high）  
来源：[`M3_HISTORY-H4有界恢复执行任务单.md`](M3_HISTORY-H4有界恢复执行任务单.md)  
声明：本报告只交付 HISTORY-H4 白名单零网络实现与定向自测证据；不兼任独立初验；**不宣称主验 / Gate / HISTORY 通过**。未联网；未跑真实 `status`/`history`；未读改项目 `data/`；未跑全量 pytest / five-stage；未初始化 Git。

## 1. 结论

已实现按「本轮新提交 request identity」计数的有界 HISTORY 恢复：CLI `history --max-new-requests N`、执行器预算耗尽后零写尾部缺失 identity、已有 receipt 只读恢复、非法 `N` 在 FS/API 前拒绝、有界未完成返回 `INCOMPLETE`/退出码 0、恰好完成 `SUCCESS`/0、无上限仍 `G1_WORKFLOW_HISTORY_INCOMPLETE` fail-closed。CLI JSON 增加 `max_new_requests` / `new_requests_committed` 并纳入严格值对象校验。**未越权修改白名单外公共 contract。**

## 2. 变更文件

| 文件 | 目的 |
|---|---|
| `src/quant/data/m3_backfill.py` | `max_new_requests`、`TushareBatchExecutionResult`、预算耗尽后只读 preflight/零写 |
| `src/quant/research/m3/g1_workflow.py` | `G1HistoryStageResultV1`、有界 INCOMPLETE vs 无界 fail-closed |
| `src/quant/research/m3/run_g1.py` | `--max-new-requests`、JSON 字段、history `INCOMPLETE`/`SUCCESS` |
| `tests/unit/test_m3_backfill_requests.py` | 计数/恢复/重试/非法 N 反例 |
| `tests/unit/test_m3_g1_workflow.py` | 有界 workflow 反例；既有 history 调用适配 `.state` |
| `tests/unit/test_m3_run_g1.py` | CLI 非法参数、INCOMPLETE/SUCCESS、JSON 字段 |
| `README.md` | 同步 `history --max-new-requests` 用法 |
| `docs/framework/agent/M3_HISTORY-H4有界恢复执行交付报告.md` | 本文件 |

## 3. 冻结语义落地摘要

1. `N` 必须 `type is int` 且 `> 0`（拒绝 `True/0/-1/1.0/"1"`）；CLI 额外拒绝非规范数字串。
2. 计数仅含本轮从无有效 receipt → 成功写入 receipt 的 identity；恢复已有 receipt 与同 identity 内 retry 不计多次。
3. 预算耗尽后：已有 receipt 继续只读恢复；下一缺失 identity 不新建/改写 intent/candidate/receipt/raw；仍对已存在 journal 做 `_validate_journal_files` + `_preflight_no_receipt`（禁止 `break` 跳过尾部非法 journal）。
4. 有界未完成：返回最新 verified state，`outcome=INCOMPLETE`，退出码 0；完成则 `SUCCESS`/0。
5. 无上限未完成：仍抛 `G1_WORKFLOW_HISTORY_INCOMPLETE`。
6. status/其他命令：`max_new_requests=null`，`new_requests_committed=0`。

## 4. 定向验证（WSL Miniforge base）

| 命令 | 退出码 |
|---|---|
| `python -m pytest tests/unit/test_m3_backfill_requests.py -q -k 'bounded or max_new or resume'` | **0**（6 passed） |
| `python -m pytest tests/unit/test_m3_g1_workflow.py -q -k 'history and not five_stage'` | **0**（6 passed） |
| `python -m pytest tests/unit/test_m3_run_g1.py -q -k 'history or max_new'` | **0**（3 passed） |
| `ruff check`（任务单所列路径） | **0** |
| `mypy`（三个生产模块） | **0** |

## 5. 风险与未决

- 独立初验须另开只读会话，并增加实现者未使用的「预算到达后非法尾部 journal 仍须被 preflight 拒绝」反例。
- 工作流有界补全用例会跑完剩余 HISTORY fake 请求（定向约 6 分钟），仅用 tmp fixture，不触达项目 data。
- 未做真实网络/真实 data 恢复；不得据此宣称 HISTORY Gate 通过。

## 6. 下一步

交未参与本轮实现的外部独立初验 Agent；初验通过后再由主 Agent 终验。
