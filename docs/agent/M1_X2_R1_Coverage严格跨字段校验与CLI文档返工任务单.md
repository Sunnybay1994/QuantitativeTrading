# M1-X2-R1 Coverage 严格跨字段校验与 CLI 文档返工任务单

日期：2026-07-18  
角色：主 Agent 冻结返工合同；外部实现与外部独立复验必须使用不同全新会话  
状态：待 XP0 释放 `README.md` 写白名单后实施；不关闭 M1 或任何 Gate

## 1. 返工问题闭环

- 现象：公共不可变值对象 `BarWindowCoverage` 接受
  `requested_observations=2, eligible=1, returned=1, missing=(), short=(), min=max=3`，且
  `is_full_window` 返回 `True`。
- 根因：`__post_init__` 只校验 min/max 非负及 `min <= max`，没有约束它们不得超过 requested，亦没有完整封闭
  eligible/returned/short/missing 与 min/max 的跨字段关系；`is_full_window` 只观察 missing/short。
- 应遵循规则：任务单要求 coverage 是“不可变、严格校验”的 typed public result；full window 必须表示每个 eligible
  证券恰有 requested 个观测，不能接受内部查询不会产生、但外部可直接构造的矛盾状态。CLI 新增参数和输出属于公共
  运行方式，按 `AGENTS.md` §3 必须同步 README。
- 最小复现：

  ```python
  BarWindowCoverage(
      universe="SH_CONNECT", as_of=date(2026, 7, 18), source="tushare",
      requested_observations=2, eligible_symbol_count=1, returned_symbol_count=1,
      missing_symbols=(), short_symbol_counts=(), min_observations=3,
      max_observations=3,
  ).is_full_window  # 当前错误地为 True
  ```

- 通过条件：上述构造稳定抛 `BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")`；新增系统化跨字段反例；README
  明确默认 report 与 `--require-full-window` fail-closed/no-output 语义；两平台聚焦验证通过。

## 2. 最小实现范围

1. 在 `BarWindowCoverage.__post_init__` 中封闭跨字段合同，至少满足：
   - `min_observations <= max_observations <= requested_observations`；
   - eligible=0 时既有全零合同保持；
   - eligible>0 且 returned=0 时 min=max=0、全部 eligible 必须 missing、short 为空；
   - eligible>0 且 returned>0 时 max>0；若 missing 非空则 min=0；若 missing 为空则 min>0；
   - `short_symbol_counts` 的计数落在 `[1, requested-1]`，`len(short_symbol_counts) <= returned`，且符号不与
     missing 重叠；
   - 令 `full_count = returned - len(short_symbol_counts)`，必须非负；eligible>0 时 min/max 必须严格等于：
     `expected_min = 0 if missing else (min(short_counts) if short_counts else requested)`，
     `expected_max = requested if full_count > 0 else (max(short_counts) if short_counts else 0)`；
   - 因而无 missing/short 时，每个 eligible 均恰有 requested，min=max=requested；一个 full 与一个 short
     并存时 max 必须为 requested，而不是 short count。
2. 不改变 `recent_for_universe()` 的兼容签名或语义；不把 strict 门禁移入 audited 库查询。
3. 在 `tests/unit/test_query.py` 增加参数化的非法手工构造反例，并保留查询生成的合法空池、全缺、短窗、满窗反例。
4. 更新 `README.md` 现有 `query_universe` 示例：说明默认 JSON 显式报告 coverage；正式完整窗口证据使用
   `--require-full-window`，失败返回 `BAR_WINDOW_INCOMPLETE` 且不写 `--output`。不得复制字段 SSOT 或声称真实
   60 日覆盖已经完成。

## 3. 文件白名单

- `src/quant/data/query.py`
- `tests/unit/test_query.py`
- `README.md`（仅 `query_universe` 现有小节）
- `docs/agent/M1_X2_R1_Coverage严格跨字段校验与CLI文档返工交付报告.md`

禁止修改 `query_universe.py`、其他生产代码/测试、Schema、配置、`data/**`、`artifacts/**`、`.git` 和既有
任务/交付/验收报告。禁止联网和真实数据命令。

## 4. 验证与职责分离

外部实现使用全新 `cursor-grok-4.5-high`；Windows 使用 `D:\Miniforge3\python.exe`，Linux 通过 WSL
`/home/mabw/AI_Coding_win/QuantitativeTrading` 的 Miniforge base。最低验证：

```text
pytest tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider
ruff check src/quant/data/query.py tests/unit/test_query.py
mypy src/quant/data/query.py
```

实现完成后，另一全新外部会话只读复验，唯一允许写：
`docs/agent/M1_X2_R1_Coverage严格跨字段校验与CLI文档独立复验报告.md`。

复验须新增实现者未使用的非法组合，至少覆盖：“无 missing/short 但 min/max 小于 requested”、“returned=0
但 missing 未覆盖全部 eligible”，以及“full+short 并存但 max 等于 short count”，并逐项报告现象、预期错误码
和两平台结果。

## 5. 停止条件

- XP0 或其他写会话仍持有 `README.md`；
- 需要修改白名单外公共接口、引入依赖、真实查询或读取凭据；
- 为修复值对象而改变旧查询兼容语义，或把不完整真实数据包装成 full window。
