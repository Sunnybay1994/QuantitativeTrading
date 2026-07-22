# M3 HISTORY-H2 候选夹具合流返工交付报告

日期：2026-07-17  
角色：外部实现 Agent（HISTORY-H2；全新会话；cursor-grok-4.5-high）  
状态：**夹具合同已兑现；定向验证未全绿；待主 Agent 裁定生产闭包漂移**  
来源：[`M3_HISTORY-H2候选夹具合流返工任务单.md`](M3_HISTORY-H2候选夹具合流返工任务单.md)

声明：本报告只交付 HISTORY-H2 白名单夹具返工与定向自测证据；不兼任独立初验；**不宣称主验 / Gate / HISTORY 通过**。未联网；未跑全量 pytest / five-stage；未改 `src/`、配置、data、其他测试；未初始化 Git。

## 1. 实现摘要

| 项 | 内容 |
|---|---|
| 根因（任务单已冻结） | `_build_inputs` 构造 `suspend_d` `VerifiedRawResponse` 时遗漏 `ts_code`，response `request_id` 与 `plan.history_batch` 不一致 → setup `KeyError` |
| 最小修复 | 从对应 `spec.parameters` 原样带入 `ts_code` / `start_date` / `end_date` / `suspend_type` |
| 夹具结果 | plan/response `request_id` 多重集对齐；参数全等（含 `ts_code`） |
| 未扩大范围 | 未改断言、未删/skip/xfail 测试；未动生产代码 |

## 2. 已改文件

- `tests/unit/test_m3_g1_candidate.py` — `_build_inputs` 停牌夹具参数补齐
- `docs/agent/M3_HISTORY-H2候选夹具合流返工交付报告.md` — 本文件

变更点（约 L373–387）：

```python
parameters={
    "ts_code": params["ts_code"],
    "start_date": params["start_date"],
    "end_date": params["end_date"],
    "suspend_type": params["suspend_type"],
},
```

## 3. 定向验证（WSL Miniforge base）

环境：`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`/home/mabw/miniforge3/bin/conda run -n base`。

| # | 命令 | 结果 | 退出码 |
|---|---|---|---:|
| V1 | `python -m pytest tests/unit/test_m3_g1_candidate.py -q` | `1 failed, 6 passed, 26 errors` | **1** |
| V2 | `python -m pytest tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_g1_planning.py tests/unit/test_m3_g1_candidate.py tests/unit/test_m3_g1_workflow.py -q -k 'not five_stage'` | `1 failed, 168 passed, 1 deselected, 26 errors` | **1** |
| V3 | `python -m ruff check tests/unit/test_m3_g1_candidate.py` | `All checks passed!` | **0** |

失败形态：setup/`build_g1_candidate` 抛出 `M3G1CandidateError: G1_CANDIDATE_PLAN_RESPONSE_MISMATCH`（不再是 KeyError）。代表用例：`test_happy_path_build_verify_audit`（ERROR）、`test_no_file_or_network_io_during_build`（FAILED）。

## 4. 夹具探针证据（白名单合同已满足）

```text
_build_inputs(symbols=['000001.SZ','000002.SZ'])
→ multiset_match True
→ n_suspend 2
→ parameters 含 ts_code/start_date/end_date/suspend_type=S，与 plan spec 全等
```

说明：任务单要求的「response request_id 与 plan 完全一致」已达成；合流 KeyError 根因已消除。

## 5. 任务书矛盾 / 阻塞（停止扩大）

### 现象
夹具对齐后，`build_g1_candidate` 仍在 `_assert_endpoint_closures` 失败。

### 根因
`src/quant/data/m3_g1_candidate.py` L1736–1754 仍按**完整自然月**集合校验 `suspend_d` 的 `(start_date, end_date)`；HISTORY-H1 已把计划改为**每证券一次完整历史窗口**（本夹具为 `20160201`–`20160202`）。

探针：

```text
build_g1_candidate(inputs=...) → ERR G1_CANDIDATE_PLAN_RESPONSE_MISMATCH
line 1754 file .../src/quant/data/m3_g1_candidate.py
```

对比：

| 侧 | `(start_date, end_date)` |
|---|---|
| plan / 夹具 suspend（H1） | `{('20160201','20160202')}` |
| `_assert_endpoint_closures` expected_months | `{('20160201','20160229')}` |

### 应遵循规则
AGENTS.md §11：发现任务书与事实冲突时停止扩大并提交证据；不得在未授权白名单外修改 `src/`。任务单明确禁止改生产代码。

### 最小复现
```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_m3_g1_candidate.py::test_happy_path_build_verify_audit -q --tb=line
```

### 通过条件（需主 Agent 扩权后）
1. 生产 `_assert_endpoint_closures` 与 HISTORY-H1「每证券全窗口」合同对齐；
2. 再跑本任务单 V1/V2/V3 全部退出码 0。

本会话**未**修改 `m3_g1_candidate.py`。

## 6. 范围外 / 未执行

- 未改 `src/`、其他测试、配置、data、receipt/journal
- 未联网、未全量 pytest、未 five-stage、未 Git init
- 不兼任独立初验；初验报告路径仍为任务单指定的 `M3_HISTORY-H2候选夹具合流独立初验报告.md`

## 7. 建议下一步

1. 主 Agent 裁定：扩权修复 `m3_g1_candidate._assert_endpoint_closures` 停牌月窗残留，或另开任务包。
2. 生产合同对齐后，交回外部实现返工，再由**未参与实现**的外部 Agent 独立初验。
