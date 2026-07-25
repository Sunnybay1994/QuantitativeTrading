# M3 G1 BENCH-B1B-R1：Workflow 基金 Fake 闭包外部返工交付报告

- 角色：外部实现 Agent（全新会话）
- 任务单：`docs/agent/M3_G1_BENCH-B1B-R1_Workflow基金Fake闭包返工任务单.md`
- 白名单：`tests/unit/test_m3_g1_workflow.py`；本报告
- 状态：实现已落地；快速合同验证已执行；完整 HISTORY 两条长测见下文（未宣称 B1B/G1 Gate）

## 1. 审计结论（超时会话遗留改动）

保留并沿用已有正确 R1 改动，未回滚：

- `_BENCHMARK = "510300.SH"`
- `_fund_daily_frame` / `_fund_adj_frame` / `_fund_div_frame`（`fund_div` 非空、`div_proc=实施`、事件在 history 窗外）
- `_CountingProClient.fund_daily/fund_adj/fund_div`：字段精确、身份 `_BENCHMARK`、独立 `endpoint_calls`、`fund_request_identities`
- `_assert_history_fund_fake_closure`：`fund_daily=1`、计划内 `fund_adj`、`fund_div=1`、`index_daily=0`、identity 不重复
- `test_five_stage_fake_publish_and_inspect_closure` 接入上述闭包断言

## 2. 本会话补强

1. 新增快速合同测试 `test_counting_pro_client_fund_endpoint_contract`：不跑完整 HISTORY，直接验证三端点字段、基金身份、非空实施分红、分端点计数、`index_daily=0`、不同 `fund_adj` 分段 identity 不重复。
2. 审计原 bounded-resume：仅靠前两轮 `max_new_requests=2` 时，因 HISTORY 按 `request_id` 排序，前几笔常为股票端点，基金 identity 前缀断言可能空转。已最小补强：推进到计划中首个基金请求后再跨 1 笔 resume，断言基金 identity 前缀稳定且全集无重复。

## 3. 验证记录

### 3.1 快速验证（本会话已跑）

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_g1_workflow.py::test_counting_pro_client_fund_endpoint_contract -q --tb=short
→ 1 passed in 2.30s

D:\Miniforge3\python.exe -m ruff check tests/unit/test_m3_g1_workflow.py
→ All checks passed!

git diff --check -- tests/unit/test_m3_g1_workflow.py docs/agent/M3_G1_BENCH-B1B-R1_Workflow基金Fake闭包外部返工交付报告.md
→ EXIT:0（无空白错误）
```

### 3.2 任务书目标长测（有界）

目标：

```bash
python -m pytest \
  tests/unit/test_m3_g1_workflow.py::test_five_stage_fake_publish_and_inspect_closure \
  tests/unit/test_m3_g1_workflow.py::test_history_bounded_incomplete_then_resume_success -q
```

已知约 1500 次 raw/journal/fsync，耗时可很长。执行中；若超出本会话窗口，记为「主 Agent 长测待验」，不虚报通过。
