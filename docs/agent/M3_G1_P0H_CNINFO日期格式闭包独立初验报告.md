# M3 G1 P0H：CNINFO 日期格式闭包独立初验报告

状态：**PASS**（独立初验通过；≠ 主验 / ≠ G1 Gate / ≠ REFERENCE / PREPARE / PUBLISH）

日期：2026-07-28（Asia/Shanghai）  
角色：外部独立初验 Agent（与实现者不同全新会话）  
模型：`cursor-grok-4.5-high`  
审查对象：冻结基线 `a1bb4f0` → 实现提交 `7460b0f`（Fix G1 CNINFO ISO date parsing）  
任务书：`docs/agent/M3_G1_P0H_CNINFO日期格式闭包返工任务单.md`  
交付报告：`docs/agent/M3_G1_P0H_CNINFO日期格式闭包返工交付报告.md`

写权限遵守：生产代码、测试、交付报告、正式 `data/` 全部只读；本会话仅新建本报告。

---

## 1. 结论

**PASS**

实现以 source-specific `_parse_cninfo_iso_date` 修复 CNINFO ISO 合同错配；七个 required 字段改用该解析器；Tushare `_parse_optional_date8`/`YYYYMMDD` 不回退；selection version 精确为 `tushare_dividend_cninfo_rights_capital_iso_date_v5`；白名单仅三文件；正式 13 receipts 零网络 selection 全部通过且正式 cninfo 路径零写。未发现需返工项。

独立初验不等于主 Agent 终验，也不等于任何 Gate。

---

## 2. 白名单与 diff 卫生

| 检查 | 证据 |
|---|---|
| 实现提交文件集合 | `docs/agent/M3_G1_P0H_CNINFO日期格式闭包返工交付报告.md`、`src/quant/data/m3_execution_facts.py`、`tests/unit/test_m3_execution_facts.py`（恰好任务书白名单；`test_cninfo_connector.py` 未改，符合“仅必要时强化”） |
| `git diff --check a1bb4f0 7460b0f` | 清洁（无 whitespace 报错） |
| 无 connector/raw/journal/CLI/正式 data 变更 | `git diff --name-only` 无对应路径 |

---

## 3. 逐项合同证据

### 3.1 CNINFO ISO parser 与七字段

- `_DATE_ISO = ^[0-9]{4}-[0-9]{2}-[0-9]{2}$`；`_parse_cninfo_iso_date` 使用 `type(value) is not str` + `fullmatch` + `strptime("%Y-%m-%d")`；失败统一 `G1_CORPORATE_ACTION_EVENT_INVALID`。
- `select_g1_cninfo_rights_actions` 中 `DECLAREDATE`/`F011D`/`F012D`/`F013D`/`F014D`/`F052D`/`F038D` 全部调用 `_parse_cninfo_iso_date`，不再调用 `_parse_optional_date8`。
- 测试：`test_p0h_cninfo_required_iso_date_fields_accepted`（七字段参数化）、`test_p0h_cninfo_iso_fixture_selection_verify_and_identity`（000661 ISO + verify + identity）。

### 3.2 非法格式 fail closed

实现者参数化覆盖：`20160427`、斜杠、timestamp、首尾空白、`2016-02-30`、空串、`None`；另有 `True`/`False`/`int`/`float`/`bytes`。全部期望 `G1_CORPORATE_ACTION_EVENT_INVALID`。定向 suite 已绿。

### 3.3 Tushare date8 不回退

- `_parse_optional_date8` 语义未改（仍 `_DATE8` + `%Y%m%d`）。
- dividend 路径仍用 date8 parser。
- `test_p0h_tushare_date8_unchanged_rejects_iso`：YYYYMMDD happy path 通过；ISO `ex_date` 被拒。
- 独立对抗（见 §5）：`_parse_optional_date8("2020-02-29")` → `EVENT_INVALID`；`"20200229"` 可解析。

### 3.4 身份版本

`G1_CORPORATE_ACTION_SELECTION_VERSION == "tushare_dividend_cninfo_rights_capital_iso_date_v5"`（代码与 `test_version_constants`）。身份自然漂移为预期，本初验不宣称下游 release/Gate。

### 3.5 connector/raw 57 列与无 raw 改写

- `len(CNINFO_STOCK_ALLOTMENT_FIELDS) == 57`。
- `tests/unit/test_cninfo_connector.py` fixture 仍为官方 ISO（如 `DECLAREDATE="2016-04-14"`）；实现提交未改该文件。
- `cninfo.py` 无 `%Y%m%d`/strftime 等日期改写；投影保持 Utf8 官方字符串。

### 3.6 既有不变量不回退

定向 suite `113 passed` 覆盖既有配股日期顺序、重复 SUBID、同 symbol/ex-date 冲突、股本身份、schema/hash，以及新增 `test_p0h_rights_date_order_still_fail_closed` / `test_p0h_rights_date8_no_longer_accepted`。

### 3.7 定向静态检查

解释器：`D:\Miniforge3\python.exe`

| 命令 | 结果 |
|---|---|
| `pytest tests/unit/test_m3_execution_facts.py tests/unit/test_cninfo_connector.py -q` | **113 passed** |
| `ruff check`（白名单三路径） | All checks passed |
| `mypy src/quant/data/m3_execution_facts.py` | Success: no issues |

未机械跑全量 pytest/Ruff/mypy。

---

## 4. 正式 13 receipts 零网络探针与零写证据

探针（只读正式 receipts，写入仅 ignored artifacts）：

```text
D:\Miniforge3\python.exe artifacts/g1_component_diag_20260722/enrich_cninfo_event_invalid_p0h.py
```

结果（exit 0）：

```json
{"status": "ALL_CNINFO_SELECTIONS_PASSED", "responses": 13, "network": false, "formal_data_writes": false}
```

零写快照：对 `data/raw/m3_g1/cninfo` 与 `data/run_state/m3_g1/cninfo` 在探针前后做相对路径 + size + UTC mtime + SHA256 清单（各 66 行）：

- before：`artifacts/g1_component_diag_20260722/p0h_indep_review_cninfo_fs_before.tsv`
- after：`artifacts/g1_component_diag_20260722/p0h_indep_review_cninfo_fs_after.tsv`
- `Compare-Object` → **CNINFO_FS_SNAPSHOT_IDENTICAL=YES**

---

## 5. 独立对抗反例（实现者未使用）

在 Windows `D:\Miniforge3\python.exe` 一次性脚本验证（非实现者测试名）：

| 反例 | 结果 |
|---|---|
| exact-type `str` 子类 `IsoStr("2016-04-27")` | `G1_CORPORATE_ACTION_EVENT_INVALID`（`type is not str`） |
| Unicode en-dash `2016\u2013…` / em-dash `2016\u2014…` | 均 `EVENT_INVALID` |
| 非闰年 `2021-02-29` | `EVENT_INVALID` |
| 闰年边界 `2020-02-29` | 接受为 `2020-02-29` |
| 将 ISO 注入 Tushare `_parse_optional_date8` | `EVENT_INVALID`；date8 `"20200229"` 仍接受 |

以上证明：严格 exact-type、ASCII 连字符与日历边界；Tushare ISO 注入不被静默接受。

---

## 6. 明确未运行 / 未宣称

未运行：正式网络请求、正式 `status`、HISTORY/REFERENCE/PREPARE/PUBLISH、WSL Linux Gate、全量回归。

本报告不宣称：主 Agent 终验通过、G1 Gate、REFERENCE/PREPARE/PUBLISH 或 Linux publish Gate。

---

## 7. 返工项

无（结论 PASS）。
