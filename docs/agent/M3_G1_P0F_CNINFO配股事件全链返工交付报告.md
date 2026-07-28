# M3 G1 P0F：CNINFO 配股事件全链返工交付报告

状态：**外部实现已提交自测；不等于独立初验 / Codex / G1 Gate**

日期：2026-07-28（Asia/Shanghai）  
实现基线：`d1f944b`（Freeze G1 P0F CNINFO rights issue contract）  
实现 Agent：外部全新会话（cursor-grok-4.5）

冻结合同：
- [`M3_G1_P0F_CNINFO配股事件全链返工任务单.md`](M3_G1_P0F_CNINFO配股事件全链返工任务单.md)
- [`20260728_M3_G1_P0F_000661配股真实证据与设计裁定.md`](20260728_M3_G1_P0F_000661配股真实证据与设计裁定.md)

## 1. 实现要点（对照冻结合同）

| 合同项 | 实现 |
|---|---|
| CNINFO 独立 source/request/journal/raw | `source=cninfo`，`endpoint=stock_allotment`，`adapter=akshare_cninfo_p_stock2232_v1`；路径 `data/raw/m3_g1/cninfo/`、`data/run_state/m3_g1/cninfo/` |
| 官方字段码 / 响应校验 | connector 冻结 57 字段集合；校验 resultcode=200、success、count==total==records、SECCODE 范围、SUBID 唯一 |
| 50 证券批次 / 637→13 | `batch_cninfo_symbol_groups` + `plan_cninfo_rights_requests`；探针确认 637→13 |
| 空响应合法完整 receipt | empty schema + journal intent→candidate→receipt |
| 统一 CA ledger/evidence | 新增 `action_type/rights_price/rights_ratio/vendor_record_id`；dividend 行兼容 |
| 通式 + market reference | reconciliation v5；`rights_subscription_cash_per_share`；P0E `supported_ratio` 未放宽 |
| 版本升级 | selection `…_v3`；reconciliation `…_v5`；mapper `…-v4`；schema `m3-g1-schema-v2`；request plan v2；derived plan v2；manifest v4；table schema v2 |
| CLI | `run_g1.py` HISTORY / run-all 注入 `CninfoConnector` |
| 零网络默认测试 | connector 可注入 fake client/enckey；正式 637 网络 HISTORY **未运行** |

## 2. 改动文件（白名单）

生产：
- `src/quant/data/connectors/cninfo.py`（新增）
- `src/quant/data/connectors/__init__.py`
- `src/quant/data/m3_backfill.py`
- `src/quant/data/m3_execution_facts.py`
- `src/quant/data/m3_g1_candidate.py`
- `src/quant/data/m3_release.py`
- `src/quant/domain/schemas.py`
- `src/quant/research/m3/g1_planning.py`
- `src/quant/research/m3/g1_workflow.py`
- `src/quant/research/m3/run_g1.py`
- `configs/research/m3_qlib_example.toml`（注释说明默认；**未**声明 `[g1_backfill.cninfo]` 键）

测试：
- `tests/unit/test_cninfo_connector.py`（新增）
- `tests/unit/test_m3_execution_facts.py`
- `tests/unit/test_schemas.py`
- `tests/unit/test_m3_backfill_requests.py`
- `tests/unit/test_m3_g1_candidate.py`
- `tests/unit/test_m3_g1_planning.py`
- `tests/unit/test_m3_g1_release.py`
- `tests/unit/test_m3_g1_workflow.py`
- `tests/unit/test_m3_reference.py`

文档：本报告

未改：`src/quant/data/__init__.py`（既有导出已覆盖版本常量与 candidate；Cninfo 经 `connectors` 导入）。仓库无 `tests/unit/test_m3_g1_cli.py`。

## 3. 失败语义

- Connector：`CNINFO_*`（schema/scope/duplicate/network/params/enckey/row_limit）
- Journal：沿用 `M3BackfillError` + CNINFO permanent/exhausted 码
- Rights mapping：既有 `G1_CORPORATE_ACTION_*`；无事件大跳仍 `FACTOR_UNEXPLAINED`
- Workflow：缺 CNINFO receipt → HISTORY incomplete；user `max_new_requests<=0` 仍 INPUT_INVALID；共享预算耗尽时内部允许 `0` 只验证不新取

## 4. 接口冲突（白名单外）

**`config.py` 不在白名单**：若在 example.toml 声明 `[g1_backfill.cninfo].*`，加载即 `UNKNOWN_KEY`。  
本轮规避：workflow 冻结默认 `row_limit=5000`；batch_size=50 在 connector/planning；toml 仅注释。正式 TOML 旋钮需主 Agent 扩展 `config.py` 白名单。

## 5. 验证（Windows `D:\Miniforge3\python.exe`）

| 检查 | 结果 |
|---|---|
| `test_cninfo_connector` + `test_m3_execution_facts` + `test_schemas` + `test_m3_backfill_requests` | **260 passed, 11 skipped**，退出码 0 |
| `test_m3_g1_planning` + release b1b×2 | **19 passed, 1 skipped**，退出码 0 |
| `test_m3_g1_workflow`（排除 five_stage/self_proof） | **20 passed**；1 fail=`test_journal_extra_file_and_symlink_invalid`（WinError 1314 无符号链接特权，环境限制） |
| `test_m3_reference::test_audit_g1_candidate_...` | **1 passed**（约 78s） |
| Ruff（白名单生产 + connector 测试） | 退出码 0 |
| mypy（10 个改动生产文件含 run_g1） | Success，退出码 0 |
| `git diff --check`（白名单） | 退出码 0 |

未完整确认：`test_m3_g1_candidate` 全文件、`test_m3_g1_release` 全文件（300 证券 fixture 构建极慢）、`test_five_stage` / self_proof。

## 6. 明确未运行 / 不宣称

- 正式 637 证券 CNINFO 网络 HISTORY（13 request）
- WSL / Linux Gate / Windows publish / VerifiedG1Release
- 独立初验、主 Agent 终验、G1 Gate

自测通过 ≠ 独立初验 / Codex / G1 Gate。

## 7. 残留风险

1. 全量 candidate/release/five_stage 定向测试未在本轮全部绿确认；pandera 新字段使 300 证券路径更慢。
2. CNINFO TOML 配置键需未来 `config.py` 白名单扩展。
3. Manifest v4 要求 input_receipts 含 cninfo；旧 v3 只读保留。
4. 未做 Linux flock 平台特有终验。
5. Windows 无 symlink 特权时 journal symlink 反例测试会 OSError（既有环境限制）。
