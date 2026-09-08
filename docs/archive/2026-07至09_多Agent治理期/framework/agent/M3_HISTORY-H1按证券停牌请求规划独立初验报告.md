# M3 HISTORY-H1 按证券停牌请求规划独立初验报告

日期：2026-07-17  
角色：外部独立初验 Agent（HISTORY-H1；未参与实现；cursor-grok-4.5-high）  
状态：**初验通过（HISTORY-H1 白名单合同）；附白名单外合流风险**  
来源：[`M4_D1Route闭包与M3_HISTORY截断返工任务单.md`](M4_D1Route闭包与M3_HISTORY截断返工任务单.md) · [`M3_HISTORY-H1按证券停牌请求规划返工交付报告.md`](M3_HISTORY-H1按证券停牌请求规划返工交付报告.md)

声明：生产代码 / 实现测试 / 配置 / data 全部只读；唯一写入本报告。未联网；未执行 `history` / `run-all` / BaoStock / Tushare；未改 raw/journal/receipt；未初始化 Git；未跑全量 pytest / five-stage。命令均在 WSL `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` Miniforge `base`。

## 1. 压缩结论

| 项 | 结果 |
|---|---|
| HISTORY-H1 核心合同 | **通过** |
| 零网络 `status` | **exit 0**；`completed_stages=[INDEX]`；`history_symbols=637`；`history_requests=3186` |
| receipt 复用 / 缺口 | **reusable=114**；**missing=3072**；数学闭合 `3186-114=3072` |
| 旧 5 完整 + 1 不完整月窗 | **原样保留**；不在新 plan；不阻塞 status |
| 白名单外 `test_m3_g1_candidate` | **确认断裂**（setup KeyError）；不否决本包，须另开白名单返工 |
| 初验退出码 | **0** |

不宣称 HISTORY / M3 Gate / 主验通过；不得启动 HISTORY 网络。

## 2. 逐项核对

| # | 标准 | 证据 | 结论 |
|---|---|---|---|
| 1 | `fetch_suspend_raw` 必需 `symbol`；SDK 精确 `ts_code/start_date/end_date/suspend_type=S/fields` | `tushare.py` L230–244；`test_tushare_connector` 12 passed；对抗 A3 | 通过 |
| 2 | 每证券全窗口 `suspend_d`（非月窗） | `plan_history_requests` L456–465；planning/backfill 断言全窗口；对抗 A1 | 通过 |
| 3 | 确定排序（`request_id` 升序、输入顺序/重复无关） | `_make_batch`；`test_history_plan_deduplicates_*`；对抗 A2 | 通过 |
| 4 | `HISTORY = 5*S+1`；S=637 → 3186 | 代码每 symbol 5 端点 + 1 `index_daily`；status `3186`；`5*637+1=3186` | 通过 |
| 5 | `row_limit=5000` / `empty_response=ALLOW`；未放宽 | `ENDPOINT_POLICIES_V1["suspend_d"]`；对抗 A5；truncation 参数已含 `ts_code` | 通过 |
| 6 | 旧月度无 `ts_code` spec 拒绝；零 SDK | `_validate_request_contract`；`test_legacy_monthly_suspend_spec_fails_before_sdk`；对抗 A4（batch ValueError + `_fetch` KeyError） | 通过 |
| 7a | receipt 身份 / 114 复用 | journal∩plan：daily36+adj28+stk29+div21=**114**；旧 suspend 5 份 ∉ plan | 通过 |
| 7b | 旧 5 完整 + 1 不完整原样保留 | 5 份无 `ts_code` 月窗 receipt + 1 份仅 `intent.json`（`20160301`–`20160331`）；raw suspend meta=5 | 通过 |
| 7c | workflow 兼容（非 five-stage） | `test_m3_g1_workflow -k 'history and not five_stage'` → 3 passed；status 无 `JOURNAL_INVALID` | 通过 |
| 7d | candidate 兼容 | 见 §4；fixture 仍按无 `ts_code` 造 suspend response → setup KeyError | **风险（白名单外）** |

## 3. 验证命令与结果

```text
pytest tests/unit/test_tushare_connector.py -q
→ 12 passed  (exit 0)

pytest tests/unit/test_m3_backfill_requests.py -k 'history or suspend or truncat' -q
→ 9 passed, 116 deselected  (exit 0)

pytest tests/unit/test_m3_g1_planning.py -k history_plan -q
→ 1 passed, 17 deselected  (exit 0)

pytest tests/unit/test_m3_g1_workflow.py -k 'history and not five_stage' -q
→ 3 passed, 17 deselected  (exit 0)

ruff check <白名单 6 文件>
→ All checks passed!  (exit 0)

mypy src/quant/data/connectors/tushare.py src/quant/data/m3_backfill.py
→ Success: no issues found in 2 source files  (exit 0)

# 实现者披露调查（最窄，未修）
pytest tests/unit/test_m3_g1_candidate.py -q -x
→ ERROR at setup of test_happy_path_build_verify_audit
→ KeyError: '01fb6820f55cfc1faeaeceb595a31598841bef5c496b983a67b57ff14db3c420'  (exit ≠0)

# /tmp 对抗探针（实现者未用）
A1–A6 全部 PASS；FAIL_COUNT=0  (exit 0)
# 覆盖：2symbol→11、全窗口绑定、排序稳定、非A股/倒置日期零SDK、旧月窗 batch/_fetch fail-closed、5000/ALLOW、旧式无 ts_code response id ∉ plan

# 恰好一次零网络 status（最后）
python -m quant.research.m3.run_g1 --config configs/research/m3_qlib_example.toml status
→ {"command":"status","completed_stages":["INDEX"],"error_code":null,"error_operation":null,
   "history_requests":3186,"history_symbols":637,"index_requests":127,
   "manifest_sha256":null,"outcome":"INCOMPLETE","primary_candidate_key":null,
   "reference_requests":0,"release_id":null,"schema_version":"m3-g1-cli-result-v1"}
→ STATUS_EXIT:0
```

字段语义映射（与任务书用语）：`history_symbols`↔S；`history_requests`↔计划 HISTORY 总数；`completed_stages`↔阶段前缀；CLI 无 `reusable`/`missing` 字段——由 journal∩`derived_plan.request_plan.history_batch` 只读审计得到。

## 4. 白名单外风险（不否决本包）

### 现象
`tests/unit/test_m3_g1_candidate.py` 在 fixture 构造阶段 KeyError：plan 中 per-symbol `suspend_d` 的 `request_id` 在 `by_id` 中找不到。

### 根因
`_build_inputs`（约 L373–387）对 suspend 调用 `_make_verified` 时**故意省略 `ts_code`**，只传 `start_date/end_date/suspend_type`。`TushareRequestSpec.create` 不跑 `_validate_request_contract`，故能造出旧式无 `ts_code` spec；其 `request_id` 与新 plan（含 `ts_code`）不一致 → `by_id[spec.request_id]` 失败。

### 应遵循规则
任务书 §2.2 新 `suspend_d` 必须含 `ts_code`；§2.4 白名单未含 `test_m3_g1_candidate.py`；AGENTS.md §11 合流前契约一致性；实现者发现白名单不足应停止并请协调者扩权（已在交付报告披露）。

### 最小复现
```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
/home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_m3_g1_candidate.py::test_happy_path_build_verify_audit -q --tb=line
```

### 新增测试建议
在获准白名单后：fixture 必须从 `spec.parameters` 原样带上 `ts_code`；增加反例——缺 `ts_code` 的 suspend verified response 不得拼进 `G1BuildInputs`。

### 通过条件
`test_m3_g1_candidate.py` 定向全绿；suspend response parameters 与 plan spec 全等（含 `ts_code`）；request_id 可按 plan 闭包对齐。

说明：此为**测试 fixture 漂移**，非生产 `plan_history_requests` / connector 合同错误；workflow 路径与真实 receipt 复用已通过。故不将 HISTORY-H1 初验标为失败，但主验合流前必须处理。

## 5. 关键计数（只读审计）

| 计数 | 值 | 含义 |
|---:|---:|---|
| S / `history_symbols` | 637 | INDEX 后历史成员并集 |
| `history_requests` | 3186 | `5×637+1` |
| reusable receipts | 114 | daily36+adj_factor28+stk_limit29+dividend21 ∩ 新 plan |
| missing identities | 3072 | `3186-114` |
| 旧月窗 suspend 完整 receipt | 5 | 无 `ts_code`；∉ plan；不计入 reusable |
| 旧月窗 suspend 不完整 | 1 | 仅 `intent.json`（`20160301`–`20160331`） |
| `index_daily` 完成 | 0 | 与既有证据一致 |
| `completed_stages` | `[INDEX]` | status 原样 |
| status exit | 0 | 零网络 |

未改写任何 journal/receipt/raw；旧 5+1 目录仍在原位。

## 6. 范围外 / 未执行

- 未更新 `M3_G1_R1C-B真实运行授权与资源清单.md`（交付约定留给 status 验真后；本初验只读，不改该清单）。
- 未启动 HISTORY 网络；逐证券全窗口是否仍触 5000 截断待联网授权后验证。
- 未跑 D1-R；未跑全量 pytest。

## 7. 建议下一步

1. 主 Agent 终验 HISTORY-H1（含对本报告 candidate 风险的白名单裁定）。
2. 另开最小白名单修复 `test_m3_g1_candidate.py` suspend fixture。
3. 用户明确授权前**禁止** HISTORY 网络；新授权上限应为 **3186**（取代旧 2679）。
