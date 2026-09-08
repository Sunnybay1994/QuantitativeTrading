# M1-X1 复权因子首日基线 Fail-Closed 实现任务单

日期：2026-07-18  
状态：已授权零网络实现；不关闭 HK 真实权限、M1 或任何 Gate

## 1. 目标与现状

当调用方显式启用复权因子时，每个已返回 bar 的证券必须在其首根 bar 当日或之前存在可 as-of 匹配的累计
复权因子。当前 `apply_adjustment_factors()` 对因子全空、证券无因子、或首个因子晚于首根 bar 时会保留 bar
中默认 `adj_factor`（通常为 1），与“空因子不得静默当 1”合同冲突。

本包只加固零网络数据合同与测试；不调用 Tushare、不声称账号具有 `hk_adjfactor` 权限、不修改既有 raw/clean。

## 2. 成功标准

- [ ] 新增稳定、脱敏的 typed coverage error；至少区分“证券完全无因子”和“首根 bar 前无基线”。
- [ ] `apply_adjustment_factors` 对每个 bar symbol 先完成全局 coverage preflight，再产生输出；任一证券失败时
  不返回部分结果，不使用 bar 原 `adj_factor` 兜底。
- [ ] 首个 factor `effective_date <= min(trade_date)` 合法；晚一日即失败。因子变化日使用新因子，之前使用
  最近的历史因子。
- [ ] `BarUpdatePipeline` 启用 factor mapper/store 时，coverage 失败前可以保留两类 raw snapshot，但不得调用
  factor clean store 或 bar clean store；显式 `use_adjustment_factors=false` 路径行为不变。
- [ ] 增加 HK 多日手算反例：调整收益严格等于
  `(close_t * factor_t) / (close_t-1 * factor_t-1) - 1`，证明变化日不是常量 1 或错误方向。
- [ ] 输入/输出仍通过 `Bar1dSchema` 与 `AdjustmentFactorSchema`；不改变 Schema SSOT，不新增依赖。
- [ ] Windows base 与 WSL base 聚焦测试、Ruff、mypy 均通过。

## 3. 文件白名单

- `src/quant/data/adjustments.py`
- `src/quant/data/pipeline.py`
- `tests/unit/test_adjustments.py`
- `tests/integration/test_bar_pipeline.py`
- `docs/framework/agent/M1_X1复权因子首日基线FailClosed实现交付报告.md`

禁止修改其他代码/测试、`AGENTS.md`、`README.md`、配置、`data/**`、`artifacts/**`、`.git`。禁止联网和真实
数据命令。若公共导出确有必要，停止并向主 Agent 提交证据，不越权改包根。

## 4. 关键反例

1. 两个证券中第二个首 factor 晚于首 bar：整体失败，两个 clean store 写次数均为 0；raw bundle 均保留。
2. factor frame 有该证券但只有未来 effective date：不能因“symbol 存在”而通过。
3. 首 factor 恰等于首 bar 日：通过；第二日 factor 改变，手算调整收益正确。
4. 未启用 factors 时同样 bars 保持当前显式不复权行为，不被新门禁误伤。
5. bars/factors 行顺序变化不改变结果或错误中的 canonical symbol 集合。

## 5. 外部闭环与验证

实现 Agent 使用全新 `cursor-grok-4.5-high`，不得兼任初验。Windows 命令用
`D:\Miniforge3\python.exe`；Linux 命令进入
`/home/mabw/AI_Coding_win/QuantitativeTrading` 并用 WSL Miniforge base。

最低验证：

```text
Windows:
python -m pytest tests/unit/test_adjustments.py tests/integration/test_bar_pipeline.py -q -p no:cacheprovider
python -m ruff check <白名单 Python 文件>
python -m mypy src/quant/data/adjustments.py src/quant/data/pipeline.py

Linux:
python -m pytest tests/unit/test_adjustments.py tests/integration/test_bar_pipeline.py -q -p no:cacheprovider
ruff check <白名单 Python 文件>
mypy src/quant/data/adjustments.py src/quant/data/pipeline.py
```

实现完成后另一全新外部会话只读初验，唯一允许写
`docs/framework/agent/M1_X1复权因子首日基线FailClosed独立初验报告.md`，并增加“一个合法证券 + 一个未来基线证券时
不得发生任何 clean 写入”的未公开反例。

## 6. 停止条件

- 需要读取真实 token/联网、修改 Schema/配置/依赖、或触碰白名单外公共接口；
- 新实现把 explicit no-factor 模式也禁止；
- 为通过测试将缺因子替换为 1、前向填充未来因子、或删除既有 raw 证据。

