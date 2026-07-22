# M3 HISTORY-H3 候选闭包语义返工交付报告

日期：2026-07-17  
角色：外部实现 Agent（HISTORY-H3；全新会话；cursor-grok-4.5-high）  
状态：**白名单合同已兑现；四项定向验证退出码 0；待独立初验**  
来源：[`M3_HISTORY-H3候选闭包语义返工任务单.md`](M3_HISTORY-H3候选闭包语义返工任务单.md)

声明：本报告只交付 HISTORY-H3 白名单实现与定向自测证据；不兼任独立初验；**不宣称主验 / Gate / HISTORY 通过**。未联网；未跑全量 pytest / five-stage；未改 planning/connector/receipt/journal/身份算法；未改 data；未初始化 Git。

## 1. 实现摘要

| 项 | 内容 |
|---|---|
| 根因（任务单已冻结） | `_assert_endpoint_closures` 仍按自然月集合校验 `suspend_d` 的 `(start_date, end_date)`，拒绝 H1 全历史窗口 |
| 最小修复 | 删除自然月合同；以 `daily/adj_factor/stk_limit/dividend` 闭合的 `history_symbols` 为权威集合；每个 symbol 恰一个 `suspend_d`，`ts_code/start/end/suspend_type=S` 全闭合 |
| 失败码 | 任一违规统一 `G1_CANDIDATE_PLAN_RESPONSE_MISMATCH`；未另造兼容分支 |
| H2 夹具 | 保留 `_build_inputs` 从 plan spec 原样带入 `ts_code/start/end/suspend_type` |
| 对抗测试 | 新增自然月窗口拒绝、缺失证券拒绝 |

## 2. 已改文件

- `src/quant/data/m3_g1_candidate.py` — `_assert_endpoint_closures` suspend 闭包语义对齐 H1
- `tests/unit/test_m3_g1_candidate.py` — 对抗测试 + 重建 helper；H2 fixture 保留
- `docs/agent/M3_HISTORY-H3候选闭包语义返工交付报告.md` — 本文件

生产闭包要点：

```python
suspend_specs = [spec for spec in history_specs if spec.endpoint == "suspend_d"]
if len(suspend_specs) != len(history_symbols):
    raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
# 每 symbol 恰一 match；start/end == history；suspend_type == "S"
```

## 3. 定向验证（WSL Miniforge base）

环境：`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`/home/mabw/miniforge3/bin/conda run -n base`。

| # | 命令 | 结果 | 退出码 |
|---|---|---|---:|
| V1 | `python -m pytest tests/unit/test_m3_g1_candidate.py -q` | `35 passed`（含 2 个新对抗） | **0** |
| V2 | `python -m pytest tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_g1_planning.py tests/unit/test_m3_g1_candidate.py tests/unit/test_m3_g1_workflow.py -q -k 'not five_stage'` | `197 passed, 1 deselected` | **0** |
| V3 | `ruff check src/quant/data/m3_g1_candidate.py tests/unit/test_m3_g1_candidate.py` | `All checks passed!` | **0** |
| V4 | `mypy src/quant/data/m3_g1_candidate.py` | `Success: no issues found in 1 source file` | **0** |

## 4. 范围外 / 未执行

- 未改 `m3_backfill` / connector / receipt / journal / 身份算法 / 其他 endpoint 语义
- 未改 status、data、配置；未联网；未全量 pytest；未 five-stage；未 Git init
- 不兼任独立初验；初验报告路径为任务单指定的 `M3_HISTORY-H3候选闭包语义独立初验报告.md`，须用 `/tmp` 增加实现者未使用的反例

## 5. 风险与建议下一步

| 风险 | 说明 |
|---|---|
| 身份算法未动 | 本包仅改闭包校验；`primary_candidate_key` 计算路径未改 |
| 跨模块合流 | planning 侧 H1 合同与 candidate 闭包现已对齐，但仍需独立初验用新反例复核 |
| 真实 HISTORY 重跑 | 本包未授权真实网络/status；截断后 resume 仍待主验裁定 |

建议：交由**未参与本实现**的外部 `cursor-grok-4.5-high` 会话做只读独立初验 → 主 Agent 终验。
