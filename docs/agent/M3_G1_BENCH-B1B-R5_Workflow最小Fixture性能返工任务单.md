# M3 G1 BENCH-B1B-R5：Workflow 最小 Fixture 性能返工任务单

## 1. 现象与根因

WSL base 全文件主验在前 22 个用例完成后，`test_history_bounded_incomplete_then_resume_success`
长时间运行。该测试用正式规模的 637 证券 HISTORY 计划反复执行、恢复和重建候选，产生数千个 raw/journal
身份与多轮完整验真。把 pytest 临时目录从 WSL1 `wslfs` 换成 `tmpfs` 后仍超过两分钟，证明主要瓶颈是
测试规模和重复计算，而不是单纯文件系统延迟。

这违反 `AGENTS.md` §7“单元测试使用最小、确定且覆盖边界的 fixture，不用大范围历史数据代替合同测试”。
正式 `637 symbols / 3190 requests / 3185 equity identities unchanged` 已由 planning 合同测试和主 Agent
零网络正式计划检查独立覆盖，不应由恢复语义测试重复承担。

## 2. 冻结目标与边界

仅优化以下两个 workflow 恢复语义测试及它们直接使用的测试 helper：

- `test_history_bounded_incomplete_then_resume_success`
- `test_history_unbounded_incomplete_still_fail_closed`

必须保持以下行为证据：

1. 严格正整数预算校验仍由既有测试覆盖；
2. 连续两次有界执行各只提交预算内的新身份，并保持前缀稳定、不重写旧 receipt；
3. 有界执行必须真实跨过至少一个 `fund_daily/fund_adj/fund_div` 身份；
4. 充足预算完成 `("INDEX", "HISTORY")`，再次无界调用零新增、零额外网络调用；
5. 无界执行被故障注入截断时仍返回 `G1_WORKFLOW_HISTORY_INCOMPLETE`；
6. 基金端点闭包及 `fund_adj` 分段数量断言继续成立；
7. 不修改或弱化正式规模 planning 测试中的 `637/3185/3190` 与旧 H00300 排除断言。

允许为这两个测试新增一个最小配置/helper，缩短日期窗、warmup/tail、指数观察或证券集合；但必须通过真实
planner、raw/journal、candidate 和 workflow 路径，禁止 mock 掉被测恢复链。目标是在 Windows Miniforge 与
WSL base 任一平台上，这两个测试合计通常不超过 60 秒。

## 3. 文件白名单

可写：

- `tests/unit/test_m3_g1_workflow.py`
- `docs/agent/M3_G1_BENCH-B1B-R5_Workflow最小Fixture性能外部返工交付报告.md`

其余文件只读。禁止真实网络、禁止修改生产代码、配置示例、正式 raw/journal/receipt、路线图或交接文档。

## 4. 验收

实现者必须使用全新 Cursor 会话与 `cursor-grok-4.5-high`，运行：

```text
python -m pytest tests/unit/test_m3_g1_workflow.py -q -k "history_bounded_incomplete_then_resume_success or history_unbounded_incomplete_still_fail_closed" --durations=5
python -m pytest tests/unit/test_m3_g1_workflow.py -q -k "history_max_new_rejects_illegal_before_side_effects or five_stage_fake_publish_and_inspect_closure" --durations=5
python -m ruff check tests/unit/test_m3_g1_workflow.py
git diff --check -- tests/unit/test_m3_g1_workflow.py
```

交付报告须记录改动、为什么未削弱合同、命令结果和耗时，不得宣布 Gate 通过。

独立初验由另一全新 Cursor 会话承担，只读生产代码和实现者测试，仅可写自己的复验报告；必须增加至少一个
对抗性检查，确认被缩小的 fixture 确实触发基金身份、resume 前缀复用和最终零新增，而非通过空计划或 mock
绕过。
