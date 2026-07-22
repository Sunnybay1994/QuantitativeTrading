# M3 HISTORY-H3 候选闭包语义独立初验报告

日期：2026-07-17  
角色：外部独立初验 Agent（HISTORY-H3；全新会话；未参与实现；cursor-grok-4.5-high）  
状态：**初验通过**  
来源：[`M3_HISTORY-H3候选闭包语义返工任务单.md`](M3_HISTORY-H3候选闭包语义返工任务单.md) · [`M3_HISTORY-H3候选闭包语义返工交付报告.md`](M3_HISTORY-H3候选闭包语义返工交付报告.md)

声明：本报告为只读独立初验；未改生产代码/实现测试/配置/data；唯一写入本文件。未联网；未跑 status、history/run-all、全量 pytest、five-stage、Git。不宣称主验 / Gate / HISTORY 通过。

## 1. 合同逐项映射

| # | 冻结合同 | 证据 | 结论 |
|---|---|---|---|
| 1 | 删除 `suspend_d` 自然月集合生产要求 | `m3_g1_candidate.py` 无 `calendar_month` / `expected_months` / `suspend_months` / `_month_windows`；闭包改为全历史窗 | **通过** |
| 2 | 以 `daily/adj_factor/stk_limit/dividend` 闭合的 `history_symbols` 为权威集合 | `_assert_endpoint_closures` L1699–1707 从上述 endpoint 收集 `ts_code` | **通过** |
| 3 | 每 `history_symbol` 恰一个 `suspend_d`；`ts_code/start/end/suspend_type=S` | L1736–1756：`len(suspend_specs)==len(history_symbols)`；逐 symbol `len(matches)==1`；`start/end` 对 `history`；`suspend_type=="S"` | **通过** |
| 4 | 缺/外/重复/子窗统一 `G1_CANDIDATE_PLAN_RESPONSE_MISMATCH` | 实现者单测 + `/tmp` 反例；稳定码未变；无兼容双合同分支 | **通过** |
| 5 | 不改 planning/connector/receipt/journal/身份算法 | 白名单仅 candidate+测试+交付报告；`_IDENTITY_SCHEMA=m3-g1-primary-candidate-identity-v1`；`_primary_candidate_key` 载荷结构未动 | **通过**（只读核对，未跑 Git） |
| 6 | H2 fixture 保留；新增月窗/缺证券对抗；不删/skip/xfail | `_build_inputs` 仍从 plan 原样带入 suspend；新增 `test_suspend_d_natural_month_window_rejected` / `test_suspend_d_missing_symbol_rejected`；35 passed 无 skip | **通过** |
| 7 | 禁止网络/status/history/run-all/data/全量/five-stage/Git | 本初验仅跑任务单四项定向验证 + `/tmp` 反例 | **遵守** |

## 2. 定向验证（WSL Miniforge base）

环境：`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`/home/mabw/miniforge3/bin/conda run -n base`。

| # | 命令 | 结果 | 退出码 |
|---|---|---|---:|
| V1 | `python -m pytest tests/unit/test_m3_g1_candidate.py -q` | `35 passed` | **0** |
| V2 | `... -k 'not five_stage'`（四文件） | `197 passed, 1 deselected` | **0** |
| V3 | `ruff check src/quant/data/m3_g1_candidate.py tests/unit/test_m3_g1_candidate.py` | All checks passed | **0** |
| V4 | `mypy src/quant/data/m3_g1_candidate.py` | Success: no issues found | **0** |

## 3. 实现者未使用的对抗性反例（`/tmp`）

探针：`/tmp/h3_adversarial_probe.py`、补强 `/tmp/h3_dup_true.py`。  
直接调用 `_assert_endpoint_closures` / `TushareRequestBatch`（2 证券最小 plan），**不**改仓库测试。

实现者已覆盖：自然月窗拒绝、缺失证券拒绝。  
本初验新增优先集合外/重复证券：

| 反例 | 构造 | 拒绝层级 | 结果 |
|---|---|---|---|
| `extra_out_of_set` | 保留全部 history suspend，额外 `999999.SZ` 全窗 | **candidate** → `G1_CANDIDATE_PLAN_RESPONSE_MISMATCH` | **通过** |
| `replace_out_of_set` | 用 `888888.SH` 替换其一（数量仍对齐） | **candidate** → 同上 | **通过** |
| `duplicate_symbol_true_subwindow` | 同 symbol 全窗 + 单日子窗（`end=start`，request_id 不同） | **candidate** → 同上 | **通过** |
| `exact_duplicate_request_id` | 同一 suspend spec 复制两次 | **上游 RequestBatch** → `batch requests 必须按 request_id 排序且唯一`（未达 candidate） | **fail-closed**（如实映射 batch 层） |
| `wrong_suspend_type` | `suspend_type="R"` | **上游参数合同** → `suspend_d 只允许 suspend_type=S`（未达 candidate） | **fail-closed**（如实映射 spec 层；candidate L1755 仍有防御检查） |
| `natural_month_window` | 复核旧月窗 | **candidate** → mismatch | **通过**（与实现者单测一致） |
| `happy_full_window` | H1 全历史窗 | candidate 接受 | **通过** |

探针 SUMMARY：`PASS n_fail=0`（含补强真子窗重复）。

层级说明：精确重复与非法 `suspend_type` 在 `TushareRequestSpec`/`TushareRequestBatch` 先拒，无法组成合法 plan 再进 candidate；集合外与可区分 request_id 的重复/子窗到达 candidate 后统一 `G1_CANDIDATE_PLAN_RESPONSE_MISMATCH`。两层均为 fail-closed，无静默接受。

## 4. 范围与风险

- 只读确认生产闭包已对齐 H1；旧自然月合同从 candidate 彻底移除。
- 未改动、未重跑 planning/connector/receipt/journal 专项以外的 V2 相关回归已绿（含 planning/backfill/workflow 定向集）。
- 身份算法表面未变；本包未授权真实 HISTORY 重跑。
- **初验通过 ≠ 主验/Gate 通过**；真实网络/status/截断 resume 仍待主 Agent 终验裁定。

## 5. 结论

**HISTORY-H3 独立初验通过。** 四项定向验证退出码均为 0；实现者未覆盖的集合外/重复证券反例在 candidate 或上游 batch/spec 层 fail-closed，失败码与合同一致。建议交主 Agent 终验。
