# M1-X2-R1 Coverage 严格跨字段校验与 CLI 文档返工交付报告

日期：2026-07-18  
角色：外部返工实现 Agent（全新会话；仅实现/自测，不兼任复验或主验）  
返工任务单：[`M1_X2_R1_Coverage严格跨字段校验与CLI文档返工任务单.md`](M1_X2_R1_Coverage严格跨字段校验与CLI文档返工任务单.md)  
前置：[`M1_X2Universe行情窗口Coverage实现交付报告.md`](M1_X2Universe行情窗口Coverage实现交付报告.md)、[`M1_X2Universe行情窗口Coverage独立初验报告.md`](M1_X2Universe行情窗口Coverage独立初验报告.md)  
状态：**返工自测完成；未做独立复验/主验；不关闭 M1 或任何 Gate**

## 1. 结论

按返工合同封闭 `BarWindowCoverage` 跨字段校验：`min/max` 不得超过 `requested`，并按任务书
`full_count` / `expected_min` / `expected_max` 公式与 eligible/returned/missing/short 关系严格一致；
任务单最小复现构造稳定抛 `BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")`。新增参数化非法手工构造
测试；`README.md` 的 `query_universe` 小节同步默认 report 与 `--require-full-window` fail-closed/no-output
语义。未改 `query_universe.py`、旧 `recent_for_universe()` 语义，亦未把 strict 门禁移入 audited 库查询。

## 2. 修改文件

| 文件 | 目的 |
|---|---|
| `src/quant/data/query.py` | `BarWindowCoverage.__post_init__` 封闭跨字段合同 |
| `tests/unit/test_query.py` | 参数化非法构造反例 + 合法 full+short 构造断言 |
| `README.md` | 仅更新 `query_universe` 现有小节 CLI 文档 |
| `docs/framework/agent/M1_X2_R1_Coverage严格跨字段校验与CLI文档返工交付报告.md` | 本报告 |

未改 `query_universe.py`、Schema、配置、`data/**`、`artifacts/**`、`.git` 及既有任务/交付/初验报告。

## 3. 关键设计选择

- 在既有类型/排序/互斥/计数守恒校验之后追加：`max <= requested`、`len(short) <= returned`；
  `eligible==0` 保持全零合同；`eligible>0` 时用
  `full_count = returned - len(short)`、
  `expected_min = 0 if missing else (min(short) if short else requested)`、
  `expected_max = requested if full_count > 0 else (max(short) if short else 0)`
  强制 `min/max` 相等。
- 因而无 missing/short 时必有 `min=max=requested`；full+short 并存时 `max` 必须为 `requested`。
- `is_full_window` 仍由 missing/short 判定；矛盾状态在构造期即被拒绝，无法再冒充 full window。

## 4. 验证命令与结果

### Windows（`D:\Miniforge3\python.exe`，仓库 `F:\AI_Coding\QuantitativeTrading`）

```text
python -m pytest tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider
→ 19 passed；exit 0

python -m ruff check src/quant/data/query.py tests/unit/test_query.py
→ All checks passed!；exit 0

python -m mypy src/quant/data/query.py
→ Success: no issues found in 1 source file；exit 0
```

### WSL（`/home/mabw/AI_Coding_win/QuantitativeTrading`，`conda run -n base`）

```text
python -m pytest tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider
→ 19 passed；exit 0

python -m ruff check src/quant/data/query.py tests/unit/test_query.py
→ All checks passed!；exit 0

python -m mypy src/quant/data/query.py
→ 首次：mypy 2.2.0 INTERNAL ERROR（exit 2，非类型诊断）
→ 立即重跑：Success: no issues found；exit 0
```

未运行真实 data 查询、未联网、未宣称独立复验 / 主验 / M1 / Gate 通过。

## 5. 反例覆盖（实现者自测）

参数化非法构造（均期望 `BAR_WINDOW_INPUT_INVALID`）：

1. `requested=2, min=max=3`（任务单最小复现）
2. 无 missing/short 但 min/max < requested
3. `returned=0` 但 missing 未覆盖全部 eligible
4. full+short 并存但 `max` 等于 short count
5. missing 存在且 `max > requested`
6. `len(short) > returned`
7. missing 非空但 `min != 0`

另保留查询路径合法短窗/全缺/满窗等既有用例；新增合法 full+short 手工构造
（`min=59, max=60, requested=60`）断言可通过且 `is_full_window is False`。

## 6. 风险与未验证项

- 未做独立复验；下一会话应只读复验并写
  `docs/framework/agent/M1_X2_R1_Coverage严格跨字段校验与CLI文档独立复验报告.md`，追加实现者未用的非法组合。
- WSL mypy 再次偶发 INTERNAL ERROR，重跑通过；复验宜再跑一次。
- 未验证真实港股通 60 日覆盖；本包仅为值对象合同与 CLI 文档同步，不构成 M1 Gate 关闭证据。
