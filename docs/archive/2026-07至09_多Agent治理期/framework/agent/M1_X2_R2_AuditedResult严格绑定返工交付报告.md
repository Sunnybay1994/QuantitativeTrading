# M1-X2-R2 Audited Result 严格绑定返工交付报告

日期：2026-07-18  
角色：外部返工实现 Agent（全新会话；仅实现/自测，不兼任复验或主验）  
返工任务单：[`M1_X2_R2_AuditedResult严格绑定返工任务单.md`](M1_X2_R2_AuditedResult严格绑定返工任务单.md)  
前置：[`M1_X2_R1_Coverage严格跨字段校验与CLI文档返工交付报告.md`](M1_X2_R1_Coverage严格跨字段校验与CLI文档返工交付报告.md)、[`M1_X2_R1_Coverage严格跨字段校验与CLI文档独立复验报告.md`](M1_X2_R1_Coverage严格跨字段校验与CLI文档独立复验报告.md)  
状态：**返工自测完成；未做独立复验/主验；不关闭 M1 或任何 Gate**

## 1. 结论

按 R2 合同完成两处严格化：

- **R2-A**：`BarWindowCoverage` 对 `missing_symbols` / `short_symbol_counts` 使用领域 SSOT
  `quant.domain.schemas.SYMBOL_PATTERN`（`re.compile` + `fullmatch`），不复制正则；空串、非 canonical、
  错误市场后缀稳定抛 `BAR_WINDOW_INPUT_INVALID`；合法 A/H canonical 保持通过。
- **R2-B**：`AuditedBarWindow.__post_init__` 在构造期绑定 frame/coverage：空 frame 仅允许
  `returned==0` 且 `max==0`；非空 frame 校验 key 列存在、dtype、无 null、source/as_of、唯一键、
  canonical symbol、确定排序、returned/missing 不相交、逐证券 counts 与 short/min/max 闭包；
  不得静默 cast/排序/去重/丢行。任务单最小复现（full coverage + empty frame）稳定拒收；
  库查询合法 empty/all-missing/short/full 路径保持通过。

未改 `query_universe.py`、README、Schema、配置、旧 `recent_for_universe()` 语义。

## 2. 修改文件

| 文件 | 目的 |
|---|---|
| `src/quant/data/query.py` | SYMBOL_PATTERN 校验；AuditedBarWindow 严格绑定 |
| `tests/unit/test_query.py` | R2-A/R2-B 非法构造与合法绑定反例 |
| `docs/framework/agent/M1_X2_R2_AuditedResult严格绑定返工交付报告.md` | 本报告 |

## 3. 关键设计选择

- 模块级 `_SYMBOL_RE = re.compile(SYMBOL_PATTERN)`，经 `_require_canonical_symbol` 复用。
- 空 frame（`height==0`）跳过列/dtype 检查，只强制 returned/max 为零（支持真空池与 all-missing）。
- 非空 frame 用 schema 精确相等拒绝错误 dtype；用 `order_keys != sorted(order_keys)` 拒绝乱序；
  从 frame 重算 short tuple 与 min/max（missing⇒min=0）并与 coverage 逐字段相等。

## 4. 验证命令与结果

### Windows（`D:\Miniforge3\python.exe`，`F:\AI_Coding\QuantitativeTrading`）

```text
python -m pytest tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider
→ 38 passed；exit 0

python -m ruff check src/quant/data/query.py tests/unit/test_query.py
→ All checks passed!；exit 0

python -m mypy src/quant/data/query.py
→ Success: no issues found；exit 0
```

### WSL（`/home/mabw/AI_Coding_win/QuantitativeTrading`，`conda run -n base`）

```text
同上 pytest → 38 passed；exit 0
同上 ruff → All checks passed!；exit 0
同上 mypy → Success: no issues found；exit 0
```

未联网、未真实查询；未宣称独立复验 / 主验 / M1 / Gate 通过。

## 5. 实现者自测反例摘要

**R2-A**：missing/short 分别测空串、`not-a-symbol`、错误后缀、过短代码；合法
`600000.SH` + `00700.HK` 可构造。

**R2-B**：full+empty frame；缺列；Datetime dtype；乱序；重复 key；未来行/异源；short 计数相同但
symbol 不同；min/max 正确但 returned 伪造；合法 full-window frame 与 empty/all-missing 绑定通过。
既有查询路径短窗/全缺/满窗等用例仍绿。

## 6. 风险与下一步

- 未做独立复验；下一会话只读写
  `docs/framework/agent/M1_X2_R2_AuditedResult严格绑定独立复验报告.md`，须追加任务单列明的对抗反例。
- 本包不构成真实港股通 60 日覆盖或 M1 Gate 关闭证据。
