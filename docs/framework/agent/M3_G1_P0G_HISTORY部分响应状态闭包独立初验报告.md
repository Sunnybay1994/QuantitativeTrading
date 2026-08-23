# M3 G1 P0G：HISTORY 部分响应状态闭包独立初验报告

状态：**PASS**（不等于主验 / G1 Gate / Windows publish / Linux Gate / 正式 CNINFO 网络 HISTORY）

日期：2026-07-28（Asia/Shanghai）  
审查对象：实现提交 `644995e`（相对冻结基线 `123c1c0`）  
审查模型：`cursor-grok-4.5-high`（外部独立初验全新会话；与实现者不同）  
角色：生产 / 测试 / 交付报告 / 正式 `data` 全部只读；唯一写入本报告

冻结合同：
- [`M3_G1_P0G_HISTORY部分响应状态闭包返工任务单.md`](M3_G1_P0G_HISTORY部分响应状态闭包返工任务单.md)
- 实现交付：[`M3_G1_P0G_HISTORY部分响应状态闭包返工交付报告.md`](M3_G1_P0G_HISTORY部分响应状态闭包返工交付报告.md)

## 1. 审查范围与方法

- `git diff --stat` / 语义 diff / `git diff --check 123c1c0 644995e`（清洁）
- 提交白名单仅 4 路径：`g1_workflow.py`、`test_m3_g1_workflow.py`、`test_m3_run_g1.py`、交付报告
- 语义改动核对：`_inspect` 局部 `verified_history`/`verified_cninfo`，两批 complete 后才赋最终 responses；闭包 INDEX/HISTORY incomplete 强制 `cninfo_responses==()`，HISTORY complete 核对 CNINFO 有序 IDs
- 未放宽 incomplete 规则；未改 counts / CLI JSON / 错误码 / 版本 / connector / raw-journal 恢复语义
- 独立重放 P0G 与 resume 定向测试；正式 Windows 磁盘 `status` + socket-poison `inspect`；补充实现者未覆盖对抗
- **未运行**：正式 CNINFO 网络 HISTORY、WSL/Linux Gate、publish、five-stage 全文件、全量 pytest/Ruff/mypy

## 2. 合同逐项证据

| # | 合同项 | 证据 | 结论 |
|---|---|---|---|
| 1 | INDEX + Tushare complete + CNINFO missing → INDEX-only，responses/candidate 空，counts=计划 totals | `test_p0g_tushare_complete_cninfo_missing_inspect_index_only`；正式 status/inspect | 通过 |
| 2 | 同上 + CNINFO partial journal/raw → 同 1，零写 | `test_p0g_tushare_complete_cninfo_partial_inspect_index_only` | 通过 |
| 3 | Tushare+CNINFO complete → HISTORY 完成，两批 IDs 精确有序 | `test_p0g_both_batches_complete_history_succeeds` | 通过 |
| 4 | fresh/index-only 注入 CNINFO 拒绝 | `test_p0g_cninfo_response_closure_rejects_tampering`；正式 INDEX-only 对抗 | 通过 |
| 5 | HISTORY-complete 删/重排/替换 CNINFO 拒绝 | 同上 + 独立 single-replace | 通过 |
| 6 | socket blocked + connector poison → status 零网零写 exit 0 INCOMPLETE | `test_p0g_status_partial_history_shape_socket_and_connector_poison`；正式 inspect socket poison | 通过 |
| 7 | bounded resume / unbounded fail-closed 不回退 | `test_history_bounded_incomplete_then_resume_success`；`test_history_unbounded_incomplete_still_fail_closed` | 通过 |
| 8 | `git diff --check` 清洁；提交仅白名单 | check 无输出；`git show --name-only 644995e` 仅 4 文件 | 通过 |

定向 pytest（`D:\Miniforge3\python.exe`）：上述 7 项，**7 passed**，退出码 0（约 218s）。

## 3. 正式 Windows 磁盘 status（只读、零网络）

命令：

```text
D:\Miniforge3\python.exe -m quant.research.m3.run_g1 --config configs/research/m3_qlib_example.toml status
```

| 项 | 结果 |
|---|---|
| 退出码 | **0** |
| 运行约 | 380s |
| JSON 摘要 | `outcome=INCOMPLETE`；`completed_stages=["INDEX"]`（无 HISTORY）；`error_code=null`；`history_requests=3190`；`history_symbols=637`；`index_requests=127`；`new_requests_committed=0`；`schema_version=m3-g1-cli-result-v1` |
| 相对旧行为 | **不再** `CLI_INTERNAL_ERROR` / exit 1 |

零写证据（命令前后快照）：

- `data/raw/m3_g1/cninfo`：**命令前不存在，命令后仍不存在**
- `data/run_state/m3_g1/cninfo`：**命令前不存在，命令后仍不存在**
- 比较结果：`ZERO_WRITE_RAW=True`，`ZERO_WRITE_STATE=True`（目录缺失快照一致；无新建 receipts/raw/journal）

补充：同一正式磁盘上 `inspect_g1_workflow` + `socket.socket` poison，约 405s，仍 INDEX-only、responses/candidate 空、counts 同上、`data/` 文件 mtime/size 不变、CNINFO 目录仍缺失。

## 4. 新增对抗性反例（实现者未用）

环境：Windows `D:\Miniforge3\python.exe`；正式磁盘只读或临时 fixture；零网络。

| # | 反例 | 结果 |
|---|---|---|
| A | 正式磁盘 `inspect` + socket poison；断言 INDEX-only / 空 responses / counts=3190/637/127 / 零写 / CNINFO 目录仍缺 | **通过**（实现者未跑正式磁盘） |
| B | 对正式 INDEX-only state：仅注入 `history_responses` stub | `ValueError` 拒绝 |
| C | 对正式 INDEX-only state：仅注入 `cninfo_responses` stub | `ValueError` 拒绝 |
| D | 对正式 INDEX-only state：同时注入 history+cninfo stub | `ValueError` 拒绝 |
| E | HISTORY-complete fixture：单条 CNINFO 替换为非法 stub | `ValueError` 拒绝 |

## 5. 发现项

无。语义与合同一致；正式 status 形状修复已独立证实。

## 6. 未运行与残留风险

- 未运行正式 CNINFO 网络 HISTORY、WSL/Linux Gate、publish、five-stage 全文件、全量静态/回归。
- 本结论仅为外部独立初验 PASS；主 Agent 终验与 Gate 关闭仍待后续。
- P0G 通过前仍禁止正式 CNINFO 网络 HISTORY（按任务书）。

## 7. 最终结论

**PASS**
