# M3 G1 P0H：CNINFO 日期格式闭包返工交付报告

状态：**外部实现已交付，待外部独立初验**（自测 ≠ 独立初验 ≠ Gate）

日期：2026-07-28（Asia/Shanghai）
实现基线：`a1bb4f0`（Freeze G1 P0H CNINFO date contract）
任务书：`docs/framework/agent/M3_G1_P0H_CNINFO日期格式闭包返工任务单.md`

## 1. 修复摘要

1. 新增私有 `_parse_cninfo_iso_date`：仅接受精确 `YYYY-MM-DD` 且日历真实日期；拒绝 `YYYYMMDD`、时间戳、空白填充、其他分隔符、空串、None、布尔与非字符串；失败统一 `G1_CORPORATE_ACTION_EVENT_INVALID`。
2. CNINFO 七个 required 日期字段（`DECLAREDATE`/`F011D`/`F012D`/`F013D`/`F014D`/`F052D`/`F038D`）全部改用该解析器；不再复用 Tushare `_parse_optional_date8`。
3. Tushare dividend `_parse_optional_date8` 与 `YYYYMMDD` 合同完全不变；不引入双格式宽松接受。
4. `G1_CORPORATE_ACTION_SELECTION_VERSION` 精确升级为 `tushare_dividend_cninfo_rights_capital_iso_date_v5`。
5. 未改 connector/raw/journal/CLI/request plan/正式 data；零网络。

## 2. 现象—根因—规则—最小复现—新增测试—通过条件

### P0H-1：CNINFO 官方 ISO 日期被 date8 parser 误拒

- **现象**：正式 13 个 CNINFO response / 35 行 raw-first 成功后，candidate build 首错 `M3G1ExecutionFactError:G1_CORPORATE_ACTION_EVENT_INVALID`；零网络探针显示失败点在日期解析，官方值为 `2020-12-04` 等严格 ISO。
- **根因**：`select_g1_cninfo_rights_actions` 错误复用 Tushare 专用 `_parse_optional_date8`（只接受 `YYYYMMDD`），与 CNINFO 官方 `YYYY-MM-DD` 合同错配。
- **规则**：日期解析必须 source-specific；CNINFO 严格 ISO，Tushare 严格 date8；不得双格式宽松或在 raw 层改写。
- **最小复现**：以 connector 一致的 ISO fixture（如 `F012D="2026-01-07"`）调用 `select_g1_cninfo_rights_actions`；修复前因 date8 失败，修复后通过。
- **新增/修订测试**：
  - fixture `_rights_row` 改为真实 ISO；
  - `test_p0h_cninfo_iso_fixture_selection_verify_and_identity`（000661 ISO 自证）；
  - `test_p0h_cninfo_required_iso_date_fields_accepted`（七字段参数化）；
  - `test_p0h_cninfo_iso_date_rejects_non_exact_iso`（任务书非法格式 + None）；
  - `test_p0h_cninfo_iso_parser_rejects_non_string`（布尔/非字符串）；
  - `test_p0h_tushare_date8_unchanged_rejects_iso`（Tushare happy path + ISO 不静默接受）；
  - `test_p0h_rights_date8_no_longer_accepted`；
  - `test_p0h_rights_date_order_still_fail_closed`；
  - `test_version_constants` 断言 `…_iso_date_v5`。
- **通过条件**：合法 ISO 通过 selection/verify/identity；非法格式 fail closed；Tushare date8 不回退；版本精确为 v5；白名单定向 pytest/ruff/mypy/diff check 全绿。

## 3. 白名单变更

| 路径 | 变更 |
|---|---|
| `src/quant/data/m3_execution_facts.py` | `_DATE_ISO` + `_parse_cninfo_iso_date`；七字段换用；selection version → `…_iso_date_v5` |
| `tests/unit/test_m3_execution_facts.py` | ISO fixture；P0H 反例与 Tushare 不回退；版本断言 |
| `tests/unit/test_cninfo_connector.py` | 未改（connector fixture 已是官方 ISO） |
| `docs/framework/agent/M3_G1_P0H_CNINFO日期格式闭包返工交付报告.md` | 本报告 |

## 4. 验证命令与退出码

解释器：`D:\Miniforge3\python.exe`（Windows 原生反馈环）。

| 命令 | 退出码 |
|---|---|
| `pytest tests/unit/test_m3_execution_facts.py tests/unit/test_cninfo_connector.py -q` | 0（113 passed） |
| `ruff check src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py tests/unit/test_cninfo_connector.py` | 0 |
| `mypy src/quant/data/m3_execution_facts.py` | 0 |
| `git diff --check a1bb4f0 -- <白名单代码>` | 0 |

未运行：全量 pytest、全量 Ruff/mypy、正式网络、正式 status/HISTORY/REFERENCE/PREPARE/PUBLISH、WSL Gate。上述属外部独立初验 / 主 Agent 终验。

## 5. 版本漂移与身份

- 旧 selection version `tushare_dividend_cninfo_rights_capital_v4` 不可再声称等价。
- 新版本 `tushare_dividend_cninfo_rights_capital_iso_date_v5` 改变可接受事件集合，将自然触发 build code version、candidate key、REFERENCE 抽样及下游 release 身份变化。
- 旧 Baostock / prepare / publish 身份不得复用。

## 6. 残留风险

- 正式 13 个 receipts 的零网络逐 response selection 尚未由本会话重跑；需独立初验/主 Agent 确认 35 行不再因 ISO 触发 `EVENT_INVALID`。
- 本交付仅为外部实现自测；不得宣称独立初验、G1 Gate、REFERENCE、PREPARE、PUBLISH 或 Linux publish Gate 通过。
