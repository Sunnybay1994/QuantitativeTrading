# M3 G1 BENCH-B1B-R5：Workflow 最小 Fixture 性能外部返工交付报告

- 角色：外部返工实现 Agent（全新会话，`cursor-grok-4.5-high`）
- 任务单：`docs/agent/M3_G1_BENCH-B1B-R5_Workflow最小Fixture性能返工任务单.md`
- 白名单：`tests/unit/test_m3_g1_workflow.py`；本报告
- 状态：返工已落地并自测；**不宣布 B1B/G1 Gate 通过**

## 1. 改动摘要

仅缩小两个 HISTORY 恢复语义测试的 fixture，不改生产代码、不 mock 恢复链：

1. 新增 `_patch_resume_fixture_scale` / `_resume_fixture_config` / `_resume_fixture_symbols`
2. 仅 `test_history_bounded_incomplete_then_resume_success` 与
   `test_history_unbounded_incomplete_still_fail_closed` 使用该最小 fixture
3. 规模：`expected_constituent_count=30`（满足硬编码 `sample_symbols=30`）、
   `feature_warmup_sessions=1`、`label_tail=1` / `horizons=[1]`、
   `dates_per_symbol=2`（同步 patch reference `_DATES_PER_SYMBOL`/`_KEY_COUNT` 与
   planning `_build_cross_source_policy`）
4. HISTORY 计划从约 `300×5+fund≈1503` 降至 `30×5+fund=153`；仍走真实
   planner / raw / journal / candidate / workflow

## 2. 为何未削弱合同

| 冻结证据 | 如何保留 |
|---|---|
| 非法 `max_new_requests` 仍拒收且无副作用 | 未改 `test_history_max_new_rejects_illegal...`；仍用 `_fast_config`/300 |
| 连续两次有界各提交预算内新身份、前缀稳定 | 测试体仍 `max_new=2` 两轮 + fund identity 前缀断言 |
| 有界执行真实跨过基金身份 | 仍推进到首个 `fund_*` 后再跨 1 笔 |
| 充足预算完成 HISTORY；再次无界零新增 | 仍 `max_new=100_000` 后无界 reuse `new_requests_committed==0` |
| 无界截断 fail-closed | 仍注入 `max_new_requests=1` → `G1_WORKFLOW_HISTORY_INCOMPLETE` |
| 基金闭包与 `fund_adj` 分段 | 仍 `_assert_history_fund_fake_closure(expected_adj=...)` |
| 正式 `637/3185/3190` 与 H00300 排除 | 未改 planning/backfill 合同测试；生产代码只读 |

## 3. 验证记录

环境：WSL Miniforge `base`（`/home/mabw/AI_Coding_win/QuantitativeTrading`）。
目标「两测合计通常 ≤60s」在该平台满足；Windows 同 fixture 更慢（inspect/lstat），不作为本轮宣称平台。

### 3.1 恢复语义（必跑）

```text
python -m pytest tests/unit/test_m3_g1_workflow.py -q \
  -k "history_bounded_incomplete_then_resume_success or history_unbounded_incomplete_still_fail_closed" \
  --durations=5
→ 2 passed, 22 deselected in 42.02s
  slowest: bounded 38.14s; unbounded 2.00s
```

### 3.2 回归（必跑）

```text
python -m pytest tests/unit/test_m3_g1_workflow.py -q \
  -k "history_max_new_rejects_illegal_before_side_effects or five_stage_fake_publish_and_inspect_closure" \
  --durations=5
→ 2 passed, 22 deselected in 3659.40s (1:00:59)
  slowest: five_stage 3648.06s; history_max_new 0.05s
```

`history_max_new...` / `five_stage...` 仍用原 300-symbol `_fast_config`（本返工未改其规模）。
five_stage 长耗时来自既有 1503-request 全链，与 R5 fixture 收缩无关。

### 3.3 静态

```text
python -m ruff check tests/unit/test_m3_g1_workflow.py
→ All checks passed!

git diff --check -- tests/unit/test_m3_g1_workflow.py
→ EXIT 0
```

## 4. 剩余风险

- Fixture 通过测试侧 monkeypatch 放松 `_EXPECTED_COUNT` / reconciliation 日期字面量；
  独立初验须对抗性确认：非空计划、真实跨基金、resume 前缀复用、最终零新增，而非空计划或 mock。
- Windows 反馈环同规模可能仍接近或超过 60s；Gate/主验应以 WSL base 为准。
- 未跑全量 pytest；未宣称 Gate 通过。
