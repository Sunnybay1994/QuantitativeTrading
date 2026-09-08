# M3 G1 P0K-A-R2 交付报告：五阶段最小 fixture 与中断恢复

状态：**实现完成（未宣布 Gate / 终验）**

日期：2026-07-30（Asia/Shanghai）

实现模型：`cursor-grok-4.5-high`

任务单冻结 HEAD：`cf7821680ec097c50c0f4fcd7ced424e4c40308a`

## 1. 现有差异逐项复核

接管未提交 P0K-A(+R1/R2) 工作树差异并复核，结论：合同覆盖完整，不假设天然通过。

| 合同点 | 证据 |
|---|---|
| 独立 CA 类型 / schema v1 | `m3_backfill.py`：`CninfoCorporateAction*`、`m3-g1-cninfo-corporate-action-*-v1` |
| endpoint/adapter 冻结 | `cninfo.py`：`stock_dividend`/`p_sysapi1139`；`stock_share_change`/`p_stock2215` |
| 官方字段精确集合 | `CNINFO_STOCK_DIVIDEND_FIELDS`（11）/`CNINFO_STOCK_SHARE_CHANGE_FIELDS`（46） |
| plan v3 五 batch | `G1RequestPlan.schema_version=m3-g1-request-plan-v3` + dividend/share batches |
| 旧 v2 fail-closed | backfill / planning 测试拒绝 v2 伪装 |
| HISTORY 顺序与共享预算 | `g1_workflow.py`：tushare→rights→dividend→share；`max_new_requests` 跨段 |
| 独立 journal/raw | `cninfo_dividend` / `cninfo_share_change` |
| candidate 身份传播、不入 ledger | `m3_g1_candidate.py` + `test_p0k_a_cninfo_ca_raw_changes_identity_without_ledger` |
| R1 release 闭包 | `m3_release._consume_build_inputs` + release 定向测试 |
| 生产 `_EXPECTED_COUNT=300` | `g1_planning.py` / `m3_g1_candidate.py` 字面量未降级 |
| 五阶段 30-symbol fixture | `_patch_workflow_fixture_scale` + `_RESUME_FIXTURE_SYMBOLS=30` |

未改：`m3_execution_facts.py` / `schemas.py` / 正式 raw·journal / P0K-B。

## 2. 两失败修复

协调方日志中的失败节点与修复：

1. `test_journal_extra_file_and_symlink_invalid`
   - 根因：HEAD 使用裸 `Path.symlink_to`；Windows 无 `SeCreateSymbolicLinkPrivilege`（WinError 1314）→ FAILED。
   - 修复：拆成 `test_journal_extra_file_invalid` + `test_journal_symlink_entry_invalid`；后者经 `_require_symlink` 仅在 1314 时 skip。
2. `test_strict_json_readers`
   - 根因：重复 key 注入硬编码 `m3-g1-manifest-v2`，与 live `manifest.schema_version` 失配。
   - 修复：按 live `schema_token` 动态构造重复 key。

另：高压并发下曾见 `test_extra_hidden_and_fifo_rejected` 一次 FAILED；单独重跑与 release 全文件均 PASSED（记为资源争用风险，非合同缺陷）。

## 3. 五阶段 fixture：规模与耗时

| 项 | 修改前 | 修改后 |
|---|---|---|
| 证券数 | `_symbols()` 默认 300 | `_RESUME_FIXTURE_SYMBOLS=30`（monkeypatch only） |
| 耗时 | ~95min 后外部 `resource_exhausted`，无 exit summary | **单测约 8.5min 通过**（507.67s，含 journal 邻测） |
| 生产期望成分数 | 300 | **仍为 300** |

五阶段断言保留：INDEX→HISTORY→REFERENCE→PREPARE→PUBLISH→INSPECT；两条 CNINFO CA batch 真实规划/执行/journal/candidate；重复 HISTORY/REFERENCE、unsupported publish、零网络。

## 4. 验证命令与摘要

环境：`D:\Miniforge3\python.exe`，`PYTHONPATH=F:\AI_Coding\QuantitativeTrading\src`。

### 4.1 五阶段单测

```text
pytest tests/unit/test_m3_g1_workflow.py::test_five_stage_fake_publish_and_inspect_closure
→ PASSED（与 journal 邻测合计 2 passed / 1 skipped，~8.5min）
```

### 4.2 R1 定向 pytest（分批，避免 Tee 缓冲假死）

| 批次 | 结果 |
|---|---|
| cninfo + backfill_requests + planning | **180 passed, 12 skipped**, 50.94s |
| workflow（deselected five_stage） | **29 passed, 1 skipped**, 475.07s |
| five_stage（上表） | **PASSED** |
| release 全文件 | **33 passed, 2 skipped**, 3880.26s |
| candidate + reference + run_g1 | **204 passed, 6 skipped**, 1820.54s |

合计约 **446 passed / ~21 skipped / 0 failed**（五阶段计入；symlink 类平台 skip 预期内）。

首次整组串联曾因 PowerShell `Tee-Object` 管道缓冲长时间无进度输出；按 R2「不得无限等待」中止后改分批+`PYTHONUNBUFFERED=1`。

### 4.3 静态检查

```text
ruff check <白名单源码与测试> → All checks passed
mypy <白名单 6 个源码文件> → Success: no issues found
git diff --check HEAD -- <白名单实现文件> → exit 0
```

## 5. 临时文件清理

- 删除根目录 `_p0ka_r2_*.log` / `_p0ka_r2_fix_*.log` 等运行日志（不提交）
- 未发现可提交的 `_p0ka_*.py` 临时脚本
- 未暂存无关脏 `docs/agent/*.md`（CRLF）

## 6. 仍存风险

- Windows 无 symlink 特权时相关用例 skip，symlink 分支需 Linux/具备特权环境补证
- release 模块级 fixture + 多次 publish 单文件可达 ~1h；高内存并发可能放大偶发失败
- 正式网络 HISTORY / 1274 / P0K-B / G1 Gate / Codex 终验均未跑
- `test_m3_run_g1.py` 本轮无 diff（CLI 字段合同未改）；靠定向回归覆盖

## 7. 提交范围

实现与测试白名单已落在 `cfb045f`（关闭 P0K-A/R1/R2 代码范围）。本轮补交：
R1 交付报告 + 本报告（含完整分批 pytest 证据）。P0K-A 停止报告保持历史不可变。
不 push。不宣布 Gate 通过。
