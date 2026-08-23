# M3 G1 R1C-B INDEX 身份合同返工交付报告

角色：全新外部实现 Agent（第 2 步）  
模型：`cursor-grok-4.5-high`  
日期：2026-07-17  
任务单：[`M3_G1_R1C-B_INDEX身份合同返工任务单.md`](M3_G1_R1C-B_INDEX身份合同返工任务单.md)  
结论：**实现与定向验证已交付**；零网络 `status` 恢复 `completed_stages=[INDEX]`。  
**不宣称** R1C-B、G1、M3 或 Gate 完成；交由另一全新只读外部 Agent 复验。

## 1. 修改摘要（白名单三文件）

| 文件 | 变更 |
|---|---|
| `src/quant/data/index_membership.py` | ① `_prepare_instruments`：整表仅要求 Schema 后符号唯一；STOCK/CNY/市场后缀/观测时生命周期合同只对 observation 引用的 symbol 执行；无关合法 ETF 不参与 membership。② `_clip_and_merge_intervals`：生命周期裁剪使区间为空时跳过（不发明替补）。③ `_build_eligible_keys`：每 signal open session 要求非空、唯一、排序且 `count <= 300`；允许经验证生命周期裁剪短暂 `<300`。observation 精确 300 门禁未改。 |
| `tests/unit/test_index_membership.py` | 新增无关 ETF 超集 digest 不变、引用 instrument 合同失败、月间退市允许 299、observation 299/301 仍拒、eligible 空/重复/>300 与伪造 verify 失败等回归；保留“后续 observation 仍列出已退市证券 → LIFECYCLE fail-closed”。 |
| 本交付报告 | 本文件。 |

未改：`membership_method_version`、配置、日期、端点、限频、request ID、真实 `data/**`、其他生产/测试文件。未初始化 Git。未调用 `index`/`history` 或任何网络。

## 2. 定向验证摘要

环境：WSL Miniforge `base`（`/home/mabw/miniforge3/bin/python`）。

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/unit/test_index_membership.py -q` | **24 passed** |
| `python -m pytest tests/unit/test_m3_g1_planning.py -q` | **18 passed** |
| `python -m pytest tests/unit/test_m3_g1_workflow.py -k "not five_stage" -q` | **19 passed**, 1 deselected |
| `python -m pytest tests/unit/test_m3_g1_workflow.py::test_five_stage_fake_publish_and_inspect_closure -v` | **1 passed**（约 3219s / 53m39s） |
| `python -m pytest tests/unit/test_m3_run_g1.py -q` | **34 passed** |
| `python -m ruff check src/quant/data/index_membership.py tests/unit/test_index_membership.py` | All checks passed |
| `python -m mypy src/quant/data/index_membership.py` | Success: no issues |

workflow 合计 **20 passed**（分批执行；中间曾遇一次 WSL `0xd00002fe`，重启后重跑通过）。

## 3. 零网络 status（权威）

```bash
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml status
```

稳定 JSON 字段：

```json
{
  "command": "status",
  "completed_stages": ["INDEX"],
  "error_code": null,
  "error_operation": null,
  "history_requests": 2679,
  "history_symbols": 637,
  "index_requests": 127,
  "manifest_sha256": null,
  "outcome": "INCOMPLETE",
  "primary_candidate_key": null,
  "reference_requests": 0,
  "release_id": null,
  "schema_version": "m3-g1-cli-result-v1"
}
```

退出码：`0`。

核对：

- `outcome=INCOMPLETE`，`completed_stages` **精确** `[INDEX]`
- `index_requests=127`（与既有 raw/receipt 闭包一致；未新发起网络）
- 真实 `S = history_symbols = 637`
- `history_requests = 2679 = 4×637 + 131`
- `reference_requests=0`；`manifest_sha256`/`release_id`/`primary_candidate_key` 均为 null
- HISTORY/REFERENCE/PREPARE/PUBLISH 均未完成

## 4. 未启动 HISTORY / 未改 evidence

- 本会话仅运行定向 pytest / ruff / mypy / `status`；**未**调用 `index`、`history`、`reference`、`prepare`、`publish`、`run-all`。
- 真实 `data/**` 只读；127 个 INDEX request/receipt/raw 按冻结 spec 复用。

## 5. 未决风险

1. `m3_g1_candidate` 仍有“eligible 精确 300”审计项；INDEX 已完成，但后续 PREPARE/candidate 在真实 299 日上可能另报 `MEMBERSHIP_COUNT_MISMATCH`。本任务白名单未授权改 candidate；留给后续 Gate。
2. five_stage 单测约 54 分钟（假 HISTORY/PREPARE 重）；已通过，但复验不必机械重跑该长测，应以零网络 status 与 `test_index_membership` 为主。
3. 不得据此宣称 R1C-B / G1 / M3 Gate 通过。

## 6. 交接

请另一名**未参与本轮实现**的外部只读 Agent 按任务单做独立复验；本报告不得当作初验通过证明。
