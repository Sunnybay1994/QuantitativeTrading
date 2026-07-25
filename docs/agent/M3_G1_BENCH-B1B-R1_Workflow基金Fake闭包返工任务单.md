# M3 G1 BENCH-B1B-R1：Workflow 基金 Fake 闭包返工任务单

## 1. 现象—根因—规则

R0 部分实现恢复后，B1B 分组测试中 candidate/workflow 组为 62 passed、2 failed。两个失败均发生于
`run_g1_history_stage`：新 planner 已发射 `fund_daily/fund_adj/fund_div`，但
`tests/unit/test_m3_g1_workflow.py::_CountingProClient` 仍只有旧 `index_daily` 与股票 endpoint，导致
connector 调用缺失方法并被包装成 `G1_WORKFLOW_EXECUTION_FAILED`。

根因是测试 fake 未随生产 endpoint 闭包同步；应遵循规则是 fake 必须模拟当前冻结外部合同，生产代码不得
为了旧 fake 回退到 H00300/index_daily 或放宽错误语义。

## 2. 最小复现

```bash
python -m pytest \
  tests/unit/test_m3_g1_workflow.py::test_five_stage_fake_publish_and_inspect_closure \
  tests/unit/test_m3_g1_workflow.py::test_history_bounded_incomplete_then_resume_success -q
```

返工前两项均在 HISTORY 阶段报 `G1_WORKFLOW_EXECUTION_FAILED`。

## 3. 白名单与实现要求

只允许修改：

- `tests/unit/test_m3_g1_workflow.py`
- `docs/agent/M3_G1_BENCH-B1B-R1_Workflow基金Fake闭包外部返工交付报告.md`

要求：

- 为 `_CountingProClient` 增加 `fund_daily/fund_adj/fund_div` 精确 fake 方法；参数与 B1A connector 合同一致；
- `fund_daily` 可复用相同字段语义但必须以独立 endpoint 方法计数，`fund_adj` 覆盖每个请求分段；
- `fund_div` 必须返回非空、字段精确、`div_proc=实施` 的事件，事件放在测试 history 窗口外，避免伪造窗口内
  因子跳变；不得使用空响应绕过 REJECT policy；
- 更新 call-count/闭包断言以反映新增基金请求，明确新 HISTORY 不调用 `index_daily`；
- 不改生产代码、其他测试或配置，不真实联网，不发布。

## 4. 新增测试与通过条件

新增或扩展断言至少证明：

- workflow 完成 HISTORY 时 fake 记录 `fund_daily=1`、计划内 `fund_adj` 全分段、`fund_div=1`；
- `index_daily=0`；
- bounded resume 不重复已完成基金 request identity；
- 所有返回列与 `TUSHARE_FIELDS` 精确一致。

通过条件：

```bash
python -m pytest tests/unit/test_m3_g1_workflow.py -q
ruff check tests/unit/test_m3_g1_workflow.py
git diff --check
```

返工后由未参与实现的全新外部会话只读复验，并写
`docs/agent/M3_G1_BENCH-B1B-R1_Workflow基金Fake闭包外部独立复验报告.md`；复验必须增加一个实现者未用的
endpoint 次数或字段闭包反例。该项通过后仍须继续 B1B 其余分组回归，不能宣布 B1B Gate。
