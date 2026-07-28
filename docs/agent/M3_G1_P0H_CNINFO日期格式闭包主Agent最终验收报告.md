# M3 G1 P0H：CNINFO 日期格式闭包主 Agent 最终验收报告

状态：**PASS**（仅关闭 P0H；不等于 G1 HISTORY、REFERENCE、PUBLISH 或 Linux Gate 完成）

日期：2026-07-28（Asia/Shanghai）  
冻结基线：`a1bb4f0`  
实现提交：`7460b0f`  
外部独立初验：`067d421`，结论 PASS

## 1. 主验结论

P0H 已按冻结合同完成：

- CNINFO 配股七个 required 日期字段使用 source-specific 严格 `YYYY-MM-DD` 解析；
- 不存在日期、date8、时间戳、其他分隔符、首尾空白、空值和非精确字符串类型均 fail closed；
- Tushare dividend `YYYYMMDD` 合同和 `_parse_optional_date8` 未被放宽；
- CNINFO connector/raw 继续保留官方 57 列和原始 ISO 字符串；
- selection identity 精确升级为 `tushare_dividend_cninfo_rights_capital_iso_date_v5`；
- 正式 13 个 responses、35 行不再触发日期解析 `G1_CORPORATE_ACTION_EVENT_INVALID`。

变更范围最小，未修改网络、请求计划、CLI、raw/journal 或正式数据。

## 2. 验证证据

### Windows 原生反馈环

- `test_m3_execution_facts.py` + `test_cninfo_connector.py`：**113 passed**
- Ruff：通过
- mypy `m3_execution_facts.py`：通过
- `git diff --check a1bb4f0 7460b0f`：清洁

### WSL Miniforge base

HEAD：`067d421`

- 同一组定向测试：**113 passed**
- 正式 receipts 零网络探针：

```json
{"status":"ALL_CNINFO_SELECTIONS_PASSED","responses":13,"network":false,"formal_data_writes":false}
```

- `data/raw/m3_g1/cninfo` 与 `data/run_state/m3_g1/cninfo` 前后文件路径、大小和 mtime 摘要一致：
  `WSL_P0H_CNINFO_ZERO_WRITE_PASS`

### 正式 status

WSL `base` 正式零网络 `status` 完成全量 candidate 构建后返回：

- `outcome=FAILED`
- `error_code=G1_WORKFLOW_QUALITY_FAILED`
- `error_operation=INSPECT`

该结果不再是 P0H 的 ISO 日期首错：逐 response 正式 selector 已全部通过。CLI 仍将后续 candidate build/audit 错误泛化为同一质量码，因此下一步需用单次分层诊断捕获新的具体首错。

## 3. 身份与后续

P0H 改变生产源码树和 selection identity，旧 v4 candidate、Baostock sample、prepare/publish/release 身份均不可复用。

本报告关闭 P0H。下一步进入新的正式 candidate 质量缺陷诊断；在其关闭前不宣称 HISTORY、REFERENCE、PREPARE、PUBLISH 或 Linux Gate 通过。
