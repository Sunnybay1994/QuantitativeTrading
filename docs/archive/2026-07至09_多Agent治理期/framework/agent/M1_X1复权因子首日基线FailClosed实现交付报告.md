# M1-X1 复权因子首日基线 Fail-Closed 实现交付报告

日期：2026-07-18  
角色：外部实现 Agent（cursor-grok-4.5-high）  
任务单：[M1_X1复权因子首日基线FailClosed实现任务单.md](M1_X1复权因子首日基线FailClosed实现任务单.md)  
结论：**实现自测完成，待独立初验与主验；未宣称初验/主验/Gate/M1 通过；零网络、未触达真实 data**

## 1. 完成内容

- 新增脱敏 typed 错误：`AdjustmentFactorCoverageIssue` /
  `AdjustmentFactorCoverageError`，`reason` 区分 `missing_symbol` 与
  `no_baseline_on_or_before_first_bar`；issues 按 symbol 规范排序。
- `apply_adjustment_factors`：非空 bars 先全局 coverage preflight，再 as-of
  backward 匹配；任一证券失败整体抛错，不返回部分结果，不再
  `coalesce` 回退 bar 原 `adj_factor`。
- 合同：`effective_date <= min(trade_date)` 合法；晚一日失败；变化日用新因子，
  之前用最近历史因子。空 bars 仍直接返回，不要求因子。
- `BarUpdatePipeline`：factor 路径先 `apply_adjustment_factors`（含 preflight），
  通过后再 `factor_store.upsert`；coverage 失败时两类 raw 已写入，两 clean
  store 均不调用。未配置 factor_mapper/store 的显式不复权路径不变。
- 测试覆盖任务书强制反例：双证券晚基线、仅未来因子、首日恰等于且 HK 手算
  调整收益、显式无因子、行序无关；Schema 仍为 `Bar1dSchema` /
  `AdjustmentFactorSchema`，未改 Schema/依赖/包根导出。

## 2. 白名单改动文件

| 文件 | 目的 |
|---|---|
| `src/quant/data/adjustments.py` | typed coverage error + fail-closed preflight/as-of |
| `src/quant/data/pipeline.py` | coverage 通过前不写 factor/bar clean |
| `tests/unit/test_adjustments.py` | 单元反例与 HK 手算收益 |
| `tests/integration/test_bar_pipeline.py` | 管线 raw 保留 / clean 写次数 0 / 无因子路径 |
| `docs/framework/agent/M1_X1复权因子首日基线FailClosed实现交付报告.md` | 本报告 |

未改 `AGENTS.md` / `README.md` / `pyproject.toml` / configs / `data/**` /
`artifacts/**` / `.git` / `src/quant/data/__init__.py`；未联网、未跑真实数据命令。

## 3. 验证命令与退出码

### Windows（`D:\Miniforge3\python.exe`）

```text
python -m pytest tests/unit/test_adjustments.py tests/integration/test_bar_pipeline.py -q -p no:cacheprovider
→ 16 passed；退出码 0

python -m ruff check src/quant/data/adjustments.py src/quant/data/pipeline.py \
  tests/unit/test_adjustments.py tests/integration/test_bar_pipeline.py
→ All checks passed!；退出码 0

python -m mypy src/quant/data/adjustments.py src/quant/data/pipeline.py
→ Success: no issues found in 2 source files；退出码 0
```

### Linux（WSL `/home/mabw/AI_Coding_win/QuantitativeTrading`，
`/home/mabw/miniforge3/bin/conda run -n base`）

```text
python -m pytest tests/unit/test_adjustments.py tests/integration/test_bar_pipeline.py -q -p no:cacheprovider
→ 16 passed；退出码 0

ruff check src/quant/data/adjustments.py src/quant/data/pipeline.py \
  tests/unit/test_adjustments.py tests/integration/test_bar_pipeline.py
→ All checks passed!；退出码 0

mypy src/quant/data/adjustments.py src/quant/data/pipeline.py
→ Success: no issues found in 2 source files；退出码 0
```

失败摘要：无（本包聚焦命令均退出码 0）。

## 4. 明确非宣称

- 不宣称独立初验、主验、M1 Gate、`hk_adjfactor` 权限或任何真实港股复权链路通过。
- 本包仅为零网络合同加固；真实账号权限与连续运行验收不在范围。

## 5. 风险与下一步

- 旧夹具曾用晚于首 bar 的因子日期并依赖 `adj_factor=1` 兜底；现已改为合法首日
  基线。其他白名单外调用方若仍依赖静默兜底，会在启用复权时显式失败（符合合同）。
- 覆盖检查对象为**已返回 bar 的证券**，不再按请求 symbol 列表做集合差；请求中无
  bar 返回的证券不进入本门禁（与任务书“已返回 bar”口径一致）。
- 下一步：另一全新外部会话只读初验，写入
  `docs/framework/agent/M1_X1复权因子首日基线FailClosed独立初验报告.md`，并补任务书要求的
  未公开反例；初验通过后由主 Agent 终验。
