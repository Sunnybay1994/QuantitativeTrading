# M1-X2 Universe 行情窗口 Coverage 实现交付报告

日期：2026-07-18  
角色：外部实现 Agent（仅实现/自测）  
任务单：[`M1_X2Universe行情窗口Coverage实现任务单.md`](M1_X2Universe行情窗口Coverage实现任务单.md)  
状态：**实现自测完成；未做独立初验/主验；不关闭 M1 Gate**

## 1. 结论

在白名单内完成 `BarWindowCoverage` / `AuditedBarWindow` / `recent_for_universe_audited`，保留
`recent_for_universe()` 原签名与语义；CLI 改走 audited 查询，默认 report 显式输出 coverage，
`--require-full-window` 在 missing/short 时以 `BAR_WINDOW_INCOMPLETE` 非零退出且不写 `--output`。
Windows 与 WSL base 聚焦 pytest / Ruff / mypy 均通过（WSL mypy 首次偶发 INTERNAL ERROR，立即重跑成功）。

## 2. 修改文件

| 文件 | 目的 |
|---|---|
| `src/quant/data/query.py` | 新增 coverage 值对象、稳定错误码、audited 查询；重复键 fail closed；无 bar 仍报告 eligible missing；基线前 as_of 复用 `eligible_symbols_on` |
| `src/quant/data/query_universe.py` | CLI 改用 audited；coverage JSON；`--require-full-window`；output 仅用 `as_posix()` |
| `tests/unit/test_query.py` | 新建：短窗/缺失、无 bar、重复键、异源/未来行、顺序确定性、基线前失败、类型拒绝 |
| `tests/unit/test_query_universe.py` | 新建：report coverage、strict 无 output、成功写 parquet |
| `docs/agent/M1_X2Universe行情窗口Coverage实现交付报告.md` | 本报告 |

未改 Schema / membership 发布合同 / `AGENTS.md` / README / pyproject / configs / `data/**` / `artifacts/**` / `.git`。

## 3. 关键设计选择

- `recent_for_universe_audited` 先经 `eligible_symbols_on` 绑定 eligible，再与 bar payload 做源内窗口；
  目标 source 的 `(symbol, trade_date, source)` 重复在窗口裁剪前检测并抛 `BAR_WINDOW_DUPLICATE_KEY`。
- `observations` 使用 `type is int and > 0`（拒绝 bool/float）；旧方法校验语义不变。
- strict 门禁在 CLI 层基于 `coverage.is_full_window`；库函数本身返回 coverage，不因 short/missing 抛错。
- 成功 JSON 的 `output` 使用 `Path.as_posix()`，避免平台分隔符进入摘要 identity。

## 4. 验证命令与结果

### Windows（`D:\Miniforge3\python.exe`）

```text
python -m pytest tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider
→ 11 passed；exit 0

python -m ruff check src/quant/data/query.py src/quant/data/query_universe.py tests/unit/test_query.py tests/unit/test_query_universe.py
→ All checks passed!；exit 0

python -m mypy src/quant/data/query.py src/quant/data/query_universe.py
→ Success: no issues found in 2 source files；exit 0
```

### WSL（`/home/mabw/AI_Coding_win/QuantitativeTrading`，`conda run -n base`）

```text
python -m pytest tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider
→ 11 passed；exit 0

python -m ruff check ...（同上路径）
→ All checks passed!；exit 0

python -m mypy src/quant/data/query.py src/quant/data/query_universe.py
→ 首次：mypy 2.2.0 INTERNAL ERROR（exit 2，非类型诊断）
→ 立即重跑：Success: no issues found；exit 0
```

未运行真实 data 查询、未联网、未宣称 M1 Gate / 初验 / 主验通过。

## 5. 反例覆盖（实现者自测）

1. A=60/B=59/C=0：report 返回 A/B，short B、missing C；CLI strict → `BAR_WINDOW_INCOMPLETE` 且无 output。
2. eligible=3 且无 bar parquet：eligible=3/missing=3。
3. 同 symbol/date/source 两行 → `BAR_WINDOW_DUPLICATE_KEY`。
4. 第二 source 与未来行不入 frame；目标 source 重复仍失败。
5. membership/bar 行序变化不改变 frame 与 coverage。
6. as_of 早于 coverage_start → `EligibilityHistoryError`（不降级空池成功）。

## 6. 风险与未验证项

- 未验证真实港股通 60 日全市场覆盖；本包仅为查询/审计能力，不构成 M1 Gate 关闭证据。
- WSL mypy 曾出现一次与本改动无关的 INTERNAL ERROR；重跑通过，但初验宜再跑一次。
- CLI 将 membership 缺失的 `FileNotFoundError` 脱敏为 `BAR_WINDOW_INPUT_INVALID`（stderr），不再回显绝对路径。
- 独立初验应另开只读会话，并按任务单追加“无 bar 但 eligible 非空”与“目标 source 重复键”对抗反例。
