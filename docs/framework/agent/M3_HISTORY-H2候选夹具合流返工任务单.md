# M3 HISTORY-H2 候选夹具合流返工任务单

## 1. 背景与裁定

HISTORY-H1 已把 `suspend_d` 请求身份冻结为“每个历史成员证券一次完整历史窗口”，因此请求参数必须包含
`ts_code`。主 Agent 合流验证得到 `176 passed / 3 failed / 28 errors / 1 deselected`；所有失败都在
`tests/unit/test_m3_g1_candidate.py::_build_inputs` 构造停牌 `VerifiedRawResponse` 时遗漏 `ts_code`，导致生成的
response request id 与 `plan.history_batch` 不一致并在 setup 阶段 `KeyError`。这是测试夹具与已验收生产合同
漂移，不授权修改生产实现。

## 2. 实现范围

唯一代码白名单：

- `tests/unit/test_m3_g1_candidate.py`

唯一交付报告：

- `docs/framework/agent/M3_HISTORY-H2候选夹具合流返工交付报告.md`

要求：

1. 在 `_build_inputs` 构造每个 `suspend_d` response 时，从对应 `spec.parameters` 原样带入 `ts_code`、
   `start_date`、`end_date`、`suspend_type`；不得自行从循环外推导另一份参数。
2. 夹具生成的 `VerifiedRawResponse.spec.request_id` 必须与对应 plan request 完全一致。
3. 不改变测试原本覆盖的业务断言，不删除、skip、xfail 或放宽任何测试。
4. 不修改 `src/`、配置、data、既有 receipt/journal 或其他测试文件。
5. 禁止网络、全量 pytest、five-stage 慢测和 Git 初始化。

## 3. 验证

在 WSL Miniforge base 中运行：

```bash
python -m pytest tests/unit/test_m3_g1_candidate.py -q
python -m pytest tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_g1_planning.py tests/unit/test_m3_g1_candidate.py tests/unit/test_m3_g1_workflow.py -q -k 'not five_stage'
ruff check tests/unit/test_m3_g1_candidate.py
```

通过条件：全部退出码为 0，且没有生产代码变更。实现完成后由全新外部 Agent 只读独立初验；初验唯一可写
`docs/agent/M3_HISTORY-H2候选夹具合流独立初验报告.md`。
