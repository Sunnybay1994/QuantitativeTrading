# M3 G1 R1C-B INDEX 独立复验报告

角色：全新外部独立复验 Agent（代码/数据只读）  
模型：`cursor-grok-4.5-high`  
日期：2026-07-17  
前置：INDEX 写入 Agent 已退出；本会话与运行者无共享上下文  
结论：**独立复验不通过**，不可交主 Agent 终验。不宣称 R1C-B / G1 / M3 Gate 完成。

## 1. 复验摘要

| 必验项 | 结果 |
|---|---|
| 零网络新进程 `status`，`completed_stages` 精确为 `[INDEX]` | **失败**：`completed_stages=[]`，`outcome=FAILED`，`error_operation=INSPECT`，`error_code=G1_WORKFLOW_IDENTITY_MISMATCH`，退出码 `3` |
| INDEX 计划/成功 receipt 身份闭包数量唯一性精确 127 | **落盘侧通过**（计划=receipt=raw=127，集合相等）；**verified INDEX 阶段未达成** |
| raw/journal 一致、可导出 S 与后续计划数 | **部分**：raw↔journal 一致无缺口；因身份闭包失败，**S / history_requests / reference_requests 不可导出** |
| 无 HISTORY/REFERENCE/PREPARE/candidate/release/PUBLISH 完成证据 | **通过** |
| 只读凭据泄露扫描 | **通过**（命中 0） |
| 对抗性核对（实现者未使用） | **发现次级阻塞**（见 §4） |

## 2. 独立证据（只读）

### 2.1 零网络 `status`

命令（WSL Miniforge `base`）：

```bash
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml status
```

独立复验观测：

```text
INSPECT:G1_WORKFLOW_IDENTITY_MISMATCH
{"command":"status","completed_stages":[],"error_code":"G1_WORKFLOW_IDENTITY_MISMATCH",
 "error_operation":"INSPECT","history_requests":0,"history_symbols":0,"index_requests":0,
 "outcome":"FAILED",...}
EXIT:3
```

与交付报告一致：失败态 CLI counts 回退为 0；**不能**把 `index_requests=0` 解读为“未落盘”。

### 2.2 INDEX 落盘闭包（127）

| 核对 | 结果 |
|---|---|
| 静态计划 `index_weight` requests | 127，唯一 |
| journal `receipt.json` | 127，唯一；目录名=`request_id`=`raw_snapshot_id` |
| raw `tushare/index_weight/request=*` | 127；与计划 request_id 集合相等 |
| 每 receipt `endpoint` | 均为 `index_weight` |
| 每 receipt `row_count` | 均为 300（`{300: 127}`） |
| 月份集合 | 排序后 `201512`…`202606`，127 月连续 |
| `_recover_tushare_batch` | `complete` |
| `_verify_tushare_complete` | 返回 127 条 verified responses |
| normalize 观测 | 38100 行，历史并集符号数 637（normalize 成功） |

因此：**网络抓取与 raw/journal 写入本身成功**；失败发生在“complete 之后的 membership/derive 身份闭包”。

### 2.3 无后续阶段证据

- raw 端点仅 `index_weight`；`daily/adj_factor/stk_limit/dividend/index_daily/suspend_d` 均不存在
- `data/run_state/m3_g1/baostock` 不存在
- `data/clean/m3_g1/releases` 不存在
- 无 HISTORY/REFERENCE/PREPARE/PUBLISH 完成 marker；`completed_stages` 始终为空
- 复验时 `.writer.lock` 不存在（交付报告曾记文件存在；写进程退出后锁已释放，不构成后续阶段证据）

### 2.4 凭据扫描

扫描范围：`docs/framework/agent/M3_G1_R1C-B_INDEX交付报告.md` + `data/run_state/m3_g1/**/*.json`（381 文件）。
未读取 token 配置。  
模式命中：`token_like=0`，`bearer=0`，`long_hex=0`。

## 3. 身份闭包失败：最小根因

### 3.1 失败链路（生产路径）

1. INDEX 命令落盘 127 个 request 后再次 `_inspect`
2. recover/verify 判定 INDEX batch `complete`
3. `derive_g1_history_plan` → `build_observed_membership`
4. `_prepare_instruments(instruments, observations)` 遍历 **整张** clean instrument 表，要求每一行：
   - `instrument_type == "STOCK"`
   - `currency == "CNY"`
   - symbol 后缀与 `market` 一致
5. 当前 `_load_source_context` 加载的 SH+SZ instrument 共 **7135** 行，其中 **ETF=1598，STOCK=5537**
6. 首个 ETF 行立即触发：

   `G1_MEMBERSHIP_INSTRUMENT_INVALID`
   → `G1_PLANNING_MEMBERSHIP_INVALID`
   → `G1_WORKFLOW_IDENTITY_MISMATCH`

7. 异常发生在 `completed.append("INDEX")` **之前**，故 `completed_stages` 永不为 `[INDEX]`；`status`/`INSPECT` 稳定复现同一 code。

### 3.2 最小根因陈述

**最小根因**：G1 workflow 把含 ETF 的全量 clean instrument 表直接交给 membership 的 `_prepare_instruments`，而后者把“表中每一行都必须是 STOCK”当作身份不变量；与真实 clean 源（STOCK+ETF）冲突。  
这不是 127 个 `index_weight` 请求缺失/重复/超范围，也不是网络瞬态。

受影响范围：

- INDEX 阶段无法 verified 完成（尽管 raw/receipt 已齐）
- `status`/`INSPECT`/`index` 后验均失败，无法 resume 到 INDEX SUCCESS
- 无法导出历史成分并集 `S`、`history_requests`、`reference_requests`
- HISTORY 及后续阶段按授权本就未启动，且因 INDEX 未完成亦不可启动

## 4. 对抗性核对（实现者未使用）

在临时内存中将 instruments 过滤为 STOCK-only（不改生产数据）后复跑 membership：

| 步骤 | 结果 |
|---|---|
| `_prepare_instruments` | 通过 |
| membership intervals | 709 段，构建成功 |
| `_build_eligible_keys` | **失败** `G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID` |

原因：信号窗 2544 个 session 中有 **46** 天成分数=**299**（期望 300），全部因退市日截断早于下一月观测替换：

| 缺口簇 | 缺失符号 | instrument.delist_date |
|---|---|---|
| 2017-02-15…2017-02-28（10 日） | `600005.SH` | 2017-02-14 |
| 2025-03-05…2025-03-31（19 日） | `600837.SH` | 2025-03-04 |
| 2025-09-08…2025-09-30（17 日） | `601989.SH` | 2025-09-05 |

对应月度观测行数仍为 300；缺口来自 **lifecycle clip × 月频 PIT 激活** 的跨月空窗，不是 raw 缺月。

额外只读核对（对抗性清单）：

- receipt 重复身份：无（127 unique）
- 缺月/超范围月：无（2015-12…2026-06 连续 127）
- stage prefix：无 INDEX 成功 prefix；journal 仅 tushare/index_weight

**结论**：即使只修 ETF 过滤，当前真实数据在既有 `expected_constituent_count=300` 硬门禁下仍会以同一 workflow code 失败。返工必须同时覆盖两层。

## 5. 返工通过条件

以下全部满足后，才可再次提交独立复验：

1. **Instrument 契约对齐（当前主因）**  
   G1 membership/derive 路径不得把 ETF 行送入 `_prepare_instruments` 的全表 STOCK 断言；或权威修订该断言并同步测试。修复后，生产路径不得再因 ETF 触发 `G1_MEMBERSHIP_INSTRUMENT_INVALID`。

2. **退市空窗 / 300 硬门禁（潜伏次因）**  
   主 Agent 必须裁定并落地其一（写入权威契约后再实现）：  
   - 调整 membership/lifecycle 语义，使信号日始终恰为 300；或  
   - 明确允许退市空窗并调整门禁/错误码；或  
   - 其他可复现、可测试的 SSOT 方案。  
   对抗复现：STOCK-only 下 46 个 299 日必须消失或被新契约合法化。

3. **验收命令（零网络，新进程）**

   ```bash
   python -m quant.research.m3.run_g1 \
     --config configs/research/m3_qlib_example.toml status
   ```

   必须：`outcome` 非 FAILED；`completed_stages` **精确** `[INDEX]`；可导出真实 `S`、`history_requests`、`reference_requests`；仍无 HISTORY/REFERENCE/PREPARE/PUBLISH 完成证据。

4. **不变量回归**  
   - 计划/receipt/raw request_id 仍为 127 且集合相等（除非主 Agent 显式改计划并重跑授权）  
   - 不得放宽空响应政策、不得改限频/日期/端点以“绕过”  
   - 新增回归：含 ETF 的 instrument 源 + 退市空窗反例

5. **职责分离**  
   返工由外部实现 Agent 完成并写交付报告后，须由**另一**未参与该轮实现的外部初验 Agent 复验；本报告不得被当作通过证明。

## 6. 最终裁定

**独立复验不通过。**  
127 请求落盘属实，但 INDEX verified 身份闭包失败；稳定 code 为 `G1_WORKFLOW_IDENTITY_MISMATCH`。  
最小根因是 clean instrument 全表含 ETF 与 `_prepare_instruments` 的全表 STOCK 断言冲突；对抗核对另揭示退市导致的 299 日空窗，同属 INDEX 完成阻塞。  
不可交主 Agent 终验。
