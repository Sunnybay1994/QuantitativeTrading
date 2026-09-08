# M3 G1 R1C-B INDEX 身份合同返工独立复验报告

角色：全新外部独立复验 Agent（生产代码 / 测试 / 配置 / data 全部只读）  
模型：`cursor-grok-4.5-high`  
日期：2026-07-17  
前置：身份合同返工实现 Agent 已退出并提交交付报告  
权威 Prompt：[`M3_G1_R1C-B_INDEX身份合同返工独立复验Prompt.md`](M3_G1_R1C-B_INDEX身份合同返工独立复验Prompt.md)  
结论：**独立复验通过，可交主 Agent 终验**。  
**不宣称** R1C-B、G1、M3 或 Gate 完成。

## 1. 复验摘要

| 必验项 | 结果 |
|---|---|
| 纯合同：无关 ETF 超集 digest 不变；引用 instrument fail-closed；observation 299/301 仍拒；月中退市允许 eligible&lt;300；eligible 非空/唯一/排序/`&lt;=300`；verifier 拒伪造 | **通过**（代码审查 + 实现者新增 5 node + 独立对抗 7 例） |
| 零网络新进程 `status`：`outcome=INCOMPLETE`，`completed_stages` 精确 `[INDEX]`，exit 0 | **通过** |
| INDEX plan/receipt/raw 身份集合精确 127，月份 `2015-12…2026-06` 连续 | **通过** |
| raw/journal 未扩展到 HISTORY；无后续阶段完成证据 | **通过** |
| `S=637`，`history_requests=4*S+131=2679` 数学闭合 | **通过** |
| eligible 分布解释真实 46 个 299 日 + 三只退市空窗 | **通过**（与当前证据一致，非硬编码迁就） |
| `membership_method_version` 未改；code identity 因生产代码变化而变；127 request ID 仍由冻结 endpoint/params 闭合 | **通过** |
| 只读凭据扫描（token/bearer/env 赋值）命中 0 | **通过** |

## 2. 零网络 `status`（权威）

```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
export PYTHONPATH=src
/home/mabw/miniforge3/bin/conda run -n base --no-capture-output \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml status
```

观测 JSON（exit 0）：

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

字段核对：

- `outcome=INCOMPLETE`，`completed_stages` **精确** `['INDEX']`
- `index_requests=127`（与 plan/receipt/raw 闭包一致）
- `history_symbols=S=637`；`history_requests=2679=4×637+131`
- `reference_requests=0`：**当前 workflow 已完成/已派生的 REFERENCE 请求计数**，不是未来理论 BaoStock 请求数；理论 REFERENCE 规模仍为 `S=637`，本阶段尚未启动 REFERENCE，故 CLI 报 0
- `primary_candidate_key` / `release_id` / `manifest_sha256` 均为 null

## 3. 真实 evidence（只读）

| 核对 | 结果 |
|---|---|
| 静态 plan `index_weight` request_id | 127，唯一 |
| journal `receipt.json` | 127；与 plan/raw 集合相等 |
| raw `tushare/index_weight/request=*` | 127；集合相等 |
| 每 receipt `endpoint` / `row_count` | 全为 `index_weight` / 300 |
| 月份 | `201512…202606`，127 月连续 |
| `_recover_tushare_batch` | `complete` |
| `_verify_tushare_complete` | 127 条 verified responses |
| raw 端点目录 | **仅** `index_weight` |
| `data/run_state/m3_g1/baostock` | 不存在 |
| `data/clean/m3_g1/releases` | 不存在 |
| HISTORY/REFERENCE/PREPARE/candidate/release/PUBLISH 完成证据 | **无** |

未调用 `index` / `history` / `reference` / `prepare` / `publish` / `run-all`；未发起网络。

## 4. 纯合同与代码核对

### 4.1 生产修订（只读审查）

`src/quant/data/index_membership.py`：

1. `_prepare_instruments`：整表仅 Schema + symbol 唯一；STOCK/CNY/市场后缀/观测时生命周期只对 observation 引用的 symbol 执行；无关合法 ETF/INDEX 不进入 mapping。
2. `_clip_and_merge_intervals`：生命周期裁剪使区间为空时 `continue`，不发明替补。
3. `_build_eligible_keys`：每 signal open session 非空、唯一、排序确定，且 `count <= 300`；允许经验证生命周期裁剪短暂 `&lt;300`。observation 精确 300 门禁未放宽。

### 4.2 身份与版本

- 配置与常量 `membership_method_version` / `G1_MEMBERSHIP_METHOD_VERSION` 仍为 `tushare_monthly_observed_next_session_close_v1`（可知时点/激活方法未变）。
- `static.runtime.code_version` 前缀观测为 `m3-g1-code-v1-45…`（生产代码已变，source-tree/code identity 改变符合预期）。
- 127 个 request ID 仍由冻结 endpoint/params 闭合；derive/status 零网络复用成功，未被当前 code hash 伪造为新网络证据。

### 4.3 实现者新增 test node

```bash
python -m pytest tests/unit/test_index_membership.py -q --tb=line \
  -k "unrelated_etf or observed_instrument or delist_between or observation_299_301 or eligible_empty_over"
```

结果：**5 passed**（未重跑整份 workflow / run_g1 / 全量 pytest）。

### 4.4 独立对抗反例（实现者未使用）

内存内只读脚本（未写入测试树）全部通过：

| ID | 反例 | 结果 |
|---|---|---|
| A1 | 多个无关 ETF + INDEX 混合，输入行序 shuffle；三表与 digest 与 STOCK-only 一致；verifier 闭合 | 通过 |
| A2 | observation 引用 symbol 为 INDEX 类型 → `G1_MEMBERSHIP_INSTRUMENT_INVALID`，无 cause | 通过 |
| A2b | instrument 表 duplicate symbol → 同 code fail-closed | 通过 |
| A3 | 同月连续两名成员退市 → eligible 合法 **298**；下一 observation 激活后恢复 300 | 通过 |
| A4 | `delist_date` 恰为 activation session → 当日仍 300，次日 299 | 通过 |
| A4b | `delist_date` 恰为 observation_date → 信号窗内该 symbol 不出现，eligible 299 | 通过 |
| A5 | 自洽伪造 eligible payload + 重算 digest → verifier `G1_MEMBERSHIP_RESULT_INVALID` | 通过 |

## 5. 真实 eligible 分布（当前证据）

全量 clean instrument：`7135` 行（`STOCK=5537`，`ETF=1598`）。  
全量超集与 STOCK-only 重建的 observations/membership/eligible **三个 digest 完全一致**。

信号窗 open session：**2544**；eligible 计数分布：

| count | sessions |
|---|---|
| 300 | 2498 |
| 299 | **46** |

三个已知退市空窗（与先前独立复验对抗核对一致，现已由修订合同合法化）：

| 缺口簇 | 日数 | 缺失符号 | instrument.delist_date |
|---|---|---|---|
| 2017-02-15…2017-02-28 | 10 | `600005.SH` | 2017-02-14 |
| 2025-03-05…2025-03-31 | 19 | `600837.SH` | 2025-03-04 |
| 2025-09-08…2025-09-30 | 17 | `601989.SH` | 2025-09-05 |

合计 `10+19+17=46`。退市日当日仍在 eligible；次一 open session 起缺席直至下一月 observation 激活替换。未补造替补证券。

## 6. 凭据扫描

范围：返工交付报告 + `data/run_state/m3_g1/**/*.json`（382 文件）。  
未读取 token 配置文件。  
模式：`token_assign` / `bearer` / `TUSHARE_TOKEN=` 赋值 → **命中 0**。  
报告不输出任何疑似 secret 内容。

## 7. 未决风险（不阻塞本轮初验）

1. 交付报告已提示：`m3_g1_candidate` 仍可能对真实 299 日报 `MEMBERSHIP_COUNT_MISMATCH`；属后续 PREPARE/candidate 范围，非本 INDEX 身份合同返工白名单。
2. 本复验按 Prompt 未重跑 `test_m3_g1_workflow.py` 长测与全量 pytest；主 Agent 终验可按需补做。

## 8. 最终裁定

**独立复验通过，可交主 Agent 终验。**  
身份合同返工使零网络 `status` 恢复 `completed_stages=['INDEX']`，`S/history_requests` 可导出且数学闭合；127 INDEX evidence 未被重写或扩展；合同与对抗反例覆盖无关超集、observation 门禁、退市空窗与 verifier fail-closed。  
**不得**据此宣称 R1C-B / G1 / M3 Gate 完成。
