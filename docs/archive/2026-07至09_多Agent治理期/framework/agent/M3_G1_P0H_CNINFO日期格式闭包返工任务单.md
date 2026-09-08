# M3 G1 P0H：CNINFO 配股日期格式闭包返工任务单

状态：**设计已冻结，待外部实现 → 外部独立初验 → 主 Agent 终验**

日期：2026-07-28（Asia/Shanghai）

## 1. 目标与正式证据

P0G 通过后，WSL `base` 正式执行：

```text
python -m quant.research.m3.run_g1 --config configs/research/m3_qlib_example.toml history --max-new-requests 13
```

13 个 CNINFO 请求均完成 raw-first/journal 提交，但 candidate build 首错为：

```text
M3G1ExecutionFactError:G1_CORPORATE_ACTION_EVENT_INVALID
```

零网络逐响应探针进一步证明：

- 正式 CNINFO raw 共 13 个 response、35 行、官方投影 57 列；
- 第一 response 的 3 行均在日期解析处失败；
- 官方真实日期值为严格 ISO 日期，例如 `2020-12-04`、`2020-12-08`、`2020-12-17`；
- `tests/unit/test_cninfo_connector.py` 的 connector fixture 同样使用 `YYYY-MM-DD`；
- `select_g1_cninfo_rights_actions` 错误复用了 Tushare 专用 `_parse_optional_date8`，只接受 `YYYYMMDD`；
- 因此错误属于 source-specific parser 合同错配，不是网络、journal、缺字段或正式数据污染。

诊断产物：

- `artifacts/g1_component_diag_20260722/formal_audit_diag_p0h.summary.json`
- `artifacts/g1_component_diag_20260722/cninfo_event_invalid_p0h.json`

上述 artifacts 为 ignored 诊断证据，不进入生产身份。

## 2. 冻结合同

### 2.1 CNINFO 日期

为 CNINFO 配股 selector 增加私有、source-specific 的严格日期解析器：

- 只接受精确 `YYYY-MM-DD` 字符串；
- 使用日历真实日期校验，拒绝不存在日期；
- required 字段遇到 `None` 必须拒绝；
- 拒绝 `YYYYMMDD`、时间戳、前后空白、其他分隔符、空字符串、布尔值和非字符串；
- 失败统一保持 `G1_CORPORATE_ACTION_EVENT_INVALID`。

以下七个 CNINFO 字段必须改用该解析器：

- `DECLAREDATE`
- `F011D`
- `F012D`
- `F013D`
- `F014D`
- `F052D`
- `F038D`

### 2.2 不得改变

- Tushare dividend 的 `_parse_optional_date8` 及 `YYYYMMDD` 合同保持不变；
- CNINFO connector/raw 官方 57 列投影、原始字符串、hash、receipt、journal 和恢复语义保持不变；
- 不在 connector 或 raw 层改写日期；
- 配股日期先后关系、A 股判定、SUBID、价格/比例/股本、成功发行过滤和冲突规则保持不变；
- CLI、请求计划、13 批预算、网络行为、正式 raw/journal 不变；
- 不删除、覆盖或迁移已提交的正式 receipts。

### 2.3 身份版本

日期解析改变可接受事件集合，必须将：

```text
tushare_dividend_cninfo_rights_capital_v4
```

升级为：

```text
tushare_dividend_cninfo_rights_capital_iso_date_v5
```

不得伪装为无语义版本变化。由该版本自然触发的 build code version、candidate key、REFERENCE 抽样及下游 release 身份变化是预期行为；旧 Baostock/prepare/publish 身份不得复用。

## 3. 实现白名单

外部实现 Agent 只可修改：

- `src/quant/data/m3_execution_facts.py`
- `tests/unit/test_m3_execution_facts.py`
- `tests/unit/test_cninfo_connector.py`（仅在需要强化 raw/selector 格式边界时）
- `docs/framework/agent/M3_G1_P0H_CNINFO日期格式闭包返工交付报告.md`

禁止修改其他生产代码、配置、正式 `data/`、既有交付/验收报告和路线图。

## 4. 必须新增或修订的测试

1. 使用与真实 connector 一致的 `YYYY-MM-DD` 配股 fixture，合法 000661/任意合成证券通过 selection、verify 和 identity 自证。
2. 参数化覆盖七个 required 日期字段，逐字段证明合法 ISO 日期可解析。
3. 至少对一个字段参数化拒绝：
   - `20160427`
   - `2016/04/27`
   - `2016-04-27T00:00:00`
   - ` 2016-04-27`
   - `2016-04-27 `
   - `2016-02-30`
   - `""`
   - `None`
4. 证明 Tushare dividend `YYYYMMDD` happy path 不回退，ISO 值不会被其 date8 parser 静默接受。
5. 现有配股日期顺序反例、重复 SUBID、跨 symbol/ex-date 冲突、股本身份和 schema/hash 测试继续通过。
6. 版本常量精确等于 `tushare_dividend_cninfo_rights_capital_iso_date_v5`。
7. connector fixture 保持官方 ISO 日期字符串，不在 raw 层格式化为 date8。

## 5. 验收命令

Windows 原生反馈环：

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_execution_facts.py tests/unit/test_cninfo_connector.py -q
D:\Miniforge3\python.exe -m ruff check src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py tests/unit/test_cninfo_connector.py
D:\Miniforge3\python.exe -m mypy src/quant/data/m3_execution_facts.py
git diff --check <冻结提交> -- <白名单>
```

外部独立初验必须使用另一全新 `cursor-grok-4.5-high` 会话，生产代码和实现者测试只读，并新增实现者未用的对抗反例。

主验阶段：

- Windows 与 WSL `base` 定向回归；
- 零网络复用正式 13 个 receipts，逐 response selection 全部通过；
- 再执行正式 `status`，确认 HISTORY/candidate 的下一真实状态；
- 本任务不自行宣称 G1 Gate、REFERENCE、PREPARE、PUBLISH 或 Linux publish Gate 通过。

## 6. 通过条件

- 根因由 source-specific ISO parser 修复，不通过 raw 改写或双格式宽松接受掩盖；
- 正式 35 条 CNINFO 配股记录不再因格式正确的 ISO 日期触发 EVENT_INVALID；
- 所有非法格式和不存在日期 fail closed；
- Tushare date8 合同不回退；
- 版本身份正确升级；
- 白名单、测试、静态检查、外部独立初验和主验全部通过。
