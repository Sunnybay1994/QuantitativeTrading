# M3 HISTORY-H1 按证券停牌请求规划返工交付报告

日期：2026-07-17  
角色：外部实现 Agent（HISTORY-H1；第二个全新会话；cursor-grok-4.5-high）  
状态：**待独立初验**  
来源：[`M4_D1Route闭包与M3_HISTORY截断返工任务单.md`](M4_D1Route闭包与M3_HISTORY截断返工任务单.md)

声明：本报告只交付 HISTORY-H1 零网络代码返工与定向自测证据；不兼任独立初验；不宣称 HISTORY / M3 Gate / 主验通过。未执行 `status`、`history`、`run-all`；未联网；未改写 data/raw/journal/receipt；未初始化 Git；未跑全量 pytest / five-stage。

## 1. 实现摘要

| 项 | 内容 |
|---|---|
| Connector | `TushareConnector.fetch_suspend_raw` 改为必需 `symbol`；校验 A 股代码；SDK 精确传 `ts_code/start_date/end_date/suspend_type=S/fields` |
| 计划 | `plan_history_requests` 取消按月全市场 `suspend_d`；每个 canonical symbol 生成五个 per-symbol 请求（`daily/adj_factor/stk_limit/dividend/suspend_d`）+ 唯一 `index_daily` → `5*S+1` |
| 执行桥 | `_fetch` 对 `suspend_d` 传入 `symbol=values["ts_code"]`，使新计划可真实执行 |
| 合同 | 既有 `_validate_request_contract` 已要求 `suspend_d` 含 `ts_code`；旧月窗无 `ts_code` spec 在 batch 构造 / `_fetch` 前失败，零 SDK 调用 |
| 门禁 | `ENDPOINT_POLICIES_V1["suspend_d"]` 仍为 `row_limit=5000`、`empty_response=ALLOW`；未放宽截断 |
| 排序 / 身份 | 仍经 `_make_batch` 按 `request_id` 排序；非 suspend 的 per-symbol/window 参数未改，对应 request_id 可复用 |

未修改 `g1_planning.py` / `run_g1.py`（`derive_g1_history_plan` 仅委托 `plan_history_requests`）。未更新 `M3_G1_R1C-B真实运行授权与资源清单.md`（零网络 status 数值验真留给独立初验）。

## 2. 已改文件

- `src/quant/data/connectors/tushare.py` — `fetch_suspend_raw` 必需 symbol + SDK `ts_code`
- `src/quant/data/m3_backfill.py` — 逐证券全窗口 `suspend_d` 计划；`_fetch` 传 symbol
- `tests/unit/test_tushare_connector.py` — SDK kwargs / 非法代码 / 倒置日期反例
- `tests/unit/test_m3_backfill_requests.py` — `5*S+1`、全窗口绑定、旧月窗 fail-closed、empty/truncation 参数补 `ts_code`
- `tests/unit/test_m3_g1_planning.py` — `history_plan` 断言 `5*S+1` 与 per-symbol suspend 全窗口
- `docs/agent/M3_HISTORY-H1按证券停牌请求规划返工交付报告.md` — 本文件

## 3. 定向自测

环境：WSL `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，Miniforge `base`（`conda run -n base`）。

```text
python -m pytest tests/unit/test_tushare_connector.py -q
→ 12 passed  (exit 0)

python -m pytest tests/unit/test_m3_backfill_requests.py -k 'history or suspend or truncat' -q
→ 9 passed, 116 deselected  (exit 0)

python -m pytest tests/unit/test_m3_g1_planning.py -k history_plan -q
→ 1 passed, 17 deselected  (exit 0)

python -m pytest tests/unit/test_m3_g1_workflow.py -k 'history and not five_stage' -q
→ 3 passed, 17 deselected  (exit 0)

python -m ruff check \
  src/quant/data/connectors/tushare.py src/quant/data/m3_backfill.py \
  tests/unit/test_tushare_connector.py tests/unit/test_m3_backfill_requests.py \
  tests/unit/test_m3_g1_planning.py tests/unit/test_m3_g1_workflow.py
→ All checks passed!  (exit 0)

python -m mypy src/quant/data/connectors/tushare.py src/quant/data/m3_backfill.py
→ Success: no issues found in 2 source files  (exit 0)
```

## 4. 风险与未决

- **未跑零网络 `status`**：计划 HISTORY=3186、复用 114 receipt、未完成 identity=3072、旧 5+1 月窗 journal 作为 extra evidence 不阻塞等，留给独立初验只读会话审计。
- **白名单外测试**：`tests/unit/test_m3_g1_candidate.py` 仍按无 `ts_code` 拼 suspend verified response；本轮未改、未跑；合流全量时可能暴露，需后续最小返工或另开白名单。
- **真实网络 HISTORY**：无授权、未执行；逐证券全窗口是否仍触及 5000 行截断边界，需联网后验证。
- 下一步：由**未参与本轮实现**的全新外部 Agent 只读独立初验（含对抗性反例 + 一次零网络 status）；初验通过后停止等待用户网络授权，不得自行启动 HISTORY。
