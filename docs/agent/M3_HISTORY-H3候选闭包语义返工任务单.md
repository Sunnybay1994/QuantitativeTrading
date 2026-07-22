# M3 HISTORY-H3 候选闭包语义返工任务单

## 1. 现象与根因

HISTORY-H2 已使 candidate fixture 的 response identity 与新 plan 完全一致，但生产函数
`src/quant/data/m3_g1_candidate.py::_assert_endpoint_closures` 仍按旧合同要求 `suspend_d` 覆盖每个自然月。
这会拒绝 HISTORY-H1 已冻结的“每个历史成员证券一个完整历史窗口”请求。稳定失败码仍为
`G1_CANDIDATE_PLAN_RESPONSE_MISMATCH`，不得另造兼容分支或同时接受旧、新两套合同。

## 2. 文件白名单

- `src/quant/data/m3_g1_candidate.py`
- `tests/unit/test_m3_g1_candidate.py`
- `docs/agent/M3_HISTORY-H3候选闭包语义返工交付报告.md`

## 3. 冻结合同

1. 删除 candidate 对 `suspend_d` 自然月集合的生产要求。
2. 以由 `daily/adj_factor/stk_limit/dividend` 闭合得到的 `history_symbols` 为权威证券集合。
3. 对每个 `history_symbol`，必须恰有一个 `suspend_d` spec；其 `ts_code` 等于该证券，`start_date` 等于
   `history.start`，`end_date` 等于 `history.end`，`suspend_type` 严格等于 `S`。
4. `suspend_d` 不得缺证券、增加集合外证券、重复证券或使用子窗口/月窗口；任一情况统一抛
   `M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")`。
5. 不修改 request planning、connector、receipt、journal、candidate 输出身份算法或其他 endpoint 语义。
6. HISTORY-H2 的 fixture 改动保留；新增最小对抗测试，至少证明旧月窗口/缺失证券不能被 candidate 接受。
   不删除、skip、xfail 或放宽既有测试。
7. 禁止网络、status、history/run-all、data 修改、全量 pytest、five-stage 慢测和 Git 初始化。

## 4. 定向验证

全部在 WSL Miniforge base：

```bash
python -m pytest tests/unit/test_m3_g1_candidate.py -q
python -m pytest tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_g1_planning.py tests/unit/test_m3_g1_candidate.py tests/unit/test_m3_g1_workflow.py -q -k 'not five_stage'
ruff check src/quant/data/m3_g1_candidate.py tests/unit/test_m3_g1_candidate.py
mypy src/quant/data/m3_g1_candidate.py
```

实现与独立初验必须使用不同全新 `cursor-grok-4.5-high` 会话。初验只读生产代码/测试，唯一允许写
`docs/agent/M3_HISTORY-H3候选闭包语义独立初验报告.md`，并须用 `/tmp` 增加一个实现者未使用的反例。
