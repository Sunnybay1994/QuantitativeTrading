# M2 U1：统一股票 / ETF 日频事件模拟器任务单

状态：**合同已冻结，待当前 G1 正式 status 结束后由主 Agent 实现与自验**

日期：2026-07-31（Asia/Shanghai）

执行角色：主 Agent。用户当前要求省略外部实现与外部初验；必要的内部 subagent 只承担只读审计，
生产实现、测试和最终裁定均由主 Agent 完成。

## 1. 目标

关闭路线图 M2 唯一未勾选项：把既有停牌、涨跌停、A 股 T+1 和股票 / ETF 成本原语接入同一套
权威交易日驱动的日频账户循环，并补齐：

- 停牌无 bar 时的持仓延续估值；
- 明确的执行拒绝证据；
- 股票与 ETF 共用事件顺序；
- 股票费用 0.5× / 1× / 2× 独立压力重放；
- 现有 S0 / S1 `simulate_etf_targets` 公共入口和经济结果兼容。

本任务不以给旧 ETF 模拟器增加几个条件判断代替统一循环。旧实现由 bar 日期驱动，停牌无 bar 时不会推进
session；估值只累加当日有 bar 的持仓；目标只遍历 `daily_bars`，会静默跳过停牌订单。这三个问题必须在
同一事件模型内关闭。

## 2. 非目标

- 不实现 M3 G7 的公司行动 entitlement、七表发布或 artifact identity；
- 不实现分钟级、撮合队列、部分成交或冲击成本模型；
- 不从 OHLCV 推断停牌或开盘涨跌停状态；
- 不按 `instrument_type=ETF` 猜测 T+0 / T+1；本任务只保持现有 M2 ETF 行为；
- 不顺手实现“可卖部分成交 + T+1 residual”。最小切片使用整笔拒绝；
- 不校准真实券商费率。成本继续来自版本化配置，报告须保留“尚未账单校准”限制；
- 不改策略接口；策略仍只输出 `TargetWeightSchema`。

## 3. 权威输入与现有原语

复用：

- `schedule_next_trading_day(...)`；
- `DailyMarketState` 与 `execution_reject_reason(...)`；
- `EtfCostModel`、`AShareCostModel`；
- `TargetWeightSchema`、`Bar1dSchema`、`InstrumentSchema`；
- `BacktestNavSchema`、`BacktestTradeSchema`；
- 既有 `simulate_etf_targets(...)` 的分红、次日开盘、整手、先卖后买与现金约束回归。

新增统一入口：

```python
@dataclass(frozen=True)
class DailySimulationResult:
    nav: pl.DataFrame
    trades: pl.DataFrame
    positions: pl.DataFrame
    rejections: pl.DataFrame


def simulate_daily_targets(
    *,
    calendar: pl.DataFrame,
    bars: pl.DataFrame,
    scheduled_targets: pl.DataFrame,
    instruments: pl.DataFrame,
    market_states: Mapping[tuple[date, str], DailyMarketState],
    initial_cash: float,
    etf_costs: EtfCostModel,
    stock_costs: AShareCostModel,
    strategy: str,
    initial_positions: pl.DataFrame | None = None,
) -> DailySimulationResult:
    ...
```

`initial_positions` 最少包含 `symbol, quantity, settled_quantity, mark_price`。它表示**首个模拟 session
已完成盘前交收后的快照**：注入的 `quantity-settled_quantity` 在首日仍未交收，于第二个模拟 session
开始时才转为 settled。首日新买股票同样在下一模拟 session 开始时转 settled。这样纯日频循环能真实覆盖
首日 T+1 拒绝，而不需要没有时间依据的同日第二事件或额外猜测 acquisition date。

每个 `(strategy, execution_date)` target batch 必须只有一个 `as_of` 和一个 `strategy_version`，symbol
唯一，且按整个 execution batch 汇总后的权重和不超过 1。不能利用不同 as_of/version 分组分别通过
`TargetWeightSchema` 后在同一执行日叠加超过 1。

## 4. 文件范围

生产代码：

- 新增 `src/quant/backtest/daily_simulator.py`；
- 修改 `src/quant/backtest/simulator.py`，保留 `simulate_etf_targets` 兼容入口；
- 按需最小修改 `src/quant/backtest/costs.py`，统一内部费用调用并增加压力倍数构造；
- 修改 `src/quant/domain/schemas.py`，新增 position / rejection Schema；
- 修改 `src/quant/backtest/__init__.py` 导出新接口。

测试：

- 新增 `tests/unit/test_daily_simulator.py`；
- 按需修改 `tests/unit/test_etf_simulator.py`；
- 既有 `tests/unit/test_backtest_timing.py`、`tests/unit/test_market_rules.py` 原则上只读。

`timing.py`、`rules.py` 原则上不改；若现有纯函数无法表达冻结合同，必须先在任务单记录缺口，再作最小修订。

## 5. 每日事件顺序

1. 按权威 calendar 推进 session，即使当日所有持仓均无 bar；
2. 除首个模拟 session 外，上一个模拟 session 留存的未交收股票数量转为 settled；ETF 保持既有 M2
   非 T+1 行为，不因 `settled_quantity` 不足拒绝；
3. 构造盘前权益：
   - 有 bar：使用当日 open；
   - 明确 `FULL_DAY` 停牌且无 bar：沿用上一合法 mark；
   - 非停牌但缺 bar：fail closed；
4. 当日存在 target batch 时，证券集合为“当前持仓 ∪ 当日 target”，batch 内缺行表示目标 0；
   当日完全没有 target batch 时只估值并延续持仓，不得隐式清仓；
5. 先卖后买；
6. 每笔意图先调用 `execution_reject_reason`：
   - 停牌；
   - 买入开盘涨停；
   - 卖出开盘跌停；
   - 股票 T+1；
7. 被拒订单不改变现金或持仓，并写 rejection；
8. 成交按证券执行政策选择 ETF 或股票成本模型；
9. 收盘估值：
   - 有 bar：使用 raw close；
   - 明确全天停牌且无 bar：沿用上一合法 mark；
   - 其他缺失：fail closed；
10. 写 NAV、position、trade、rejection，并核对现金非负、数量与权益守恒。

成本压力由模型自身提供确定构造器：

```python
EtfCostModel.with_execution_cost_multiplier(multiplier)
AShareCostModel.with_execution_cost_multiplier(multiplier)
```

`multiplier` 必须是正有限数。ETF 缩放 commission rate/min 与 slippage；股票只缩放 commission
rate/min 与 slippage，stamp tax 和 transfer fee 保持原值。每个压力档返回新 immutable model，
不得修改原对象或复用其他压力档的 fills。

`market_states` 必须是执行时点已知的显式投影。不得用当日 close/high/low/volume 反推开盘状态。

## 6. 输出 Schema

`BacktestPositionSchema` 最少字段：

```text
strategy
date
symbol
quantity
settled_quantity
unsettled_quantity
mark_price
market_value
target_weight
```

`BacktestRejectionSchema` 最少字段：

```text
strategy
date
symbol
side
reason
requested_quantity
rejected_quantity
reference_price
```

四张输出必须稳定排序；输入行顺序变化不得改变摘要和经济结果。固定顺序为：NAV `date`；
position `date/symbol`；rejection `date/symbol/side`；trade 按 `date` 后保持事件顺序（SELL 在 BUY 前，
同一 side 内按 symbol）。

Schema 跨字段约束：

- `quantity == settled_quantity + unsettled_quantity`；
- `market_value` 在表示容差内等于 `quantity * mark_price`；
- position key `strategy/date/symbol` 唯一；
- position 每个 session 覆盖“非零持仓 ∪ 当日 batch symbols”；当日卖至 0 的 symbol 保留该日零仓位
  evidence，后续无 batch 且仍为 0 时可省略；
- `target_weight` 可空：初始持仓在首个 target batch 前为 null；有 batch 时使用该 symbol 的目标权重，
  batch 省略的现持仓记 0；后续无 batch 时延续最近一次已知目标；
- 当前最小切片只产生整笔拒绝，故 `rejected_quantity == requested_quantity`；
- `BUY_AT_UPPER_LIMIT` 只配 BUY，`SELL_AT_LOWER_LIMIT/T_PLUS_ONE` 只配 SELL，
  `SUSPENDED` 可配双边；
- rejection key `strategy/date/symbol/side` 唯一。
- rejection `reference_price`：有 bar 时使用当日 open；明确全天停牌且无 bar 时使用上一合法 carried mark。

## 7. 失败语义

- `BACKTEST_CALENDAR_COVERAGE_MISSING`
- `BACKTEST_MARKET_STATE_MISSING`
- `BACKTEST_TRADABLE_BAR_MISSING`
- `BACKTEST_INITIAL_MARK_MISSING`
- `BACKTEST_TARGET_BATCH_INVALID`
- `BACKTEST_INSTRUMENT_POLICY_MISSING`
- `BACKTEST_COST_NOT_EFFECTIVE`
- `BACKTEST_ACCOUNT_INVARIANT_BROKEN`

可证明的市场阻断写 rejection 并继续模拟；输入覆盖、执行政策或账户守恒不成立则 fail closed。
不得把缺 bar 默认解释为停牌，不得把停牌持仓估值为零，不得静默忽略缺 Instrument 或缺 market state 的目标。

## 8. 强制反例

使用一个 `600000.SH` 股票 + `510300.SH` ETF、5–6 个 session 的共同 fixture：

1. 停牌股票昨日 100 股、mark=10；当日 `FULL_DAY` 且无 bar：
   - market value 仍为 1000；
   - 清仓目标写 `SUSPENDED`；
   - 持仓不消失。
2. 同样缺 bar 但 `suspended=False`：必须失败。
3. 股票开盘等于上限，买单写 `BUY_AT_UPPER_LIMIT`。
4. 持仓股票开盘等于下限，卖单写 `SELL_AT_LOWER_LIMIT`。
5. 收盘涨停但开盘未触限：不得前视拒单。
6. 初始 `quantity=200, settled=100`，目标清仓：整单 T+1 拒绝并保留 200 股；不得使用未成交卖款买入 ETF。
   同形状 ETF 即使 `settled_quantity=0` 也保持既有非 T+1 行为，可正常卖出。
7. 0.5× / 1× / 2× 必须从相同初始账户独立重放：
   - ETF 的佣金、最低佣金、滑点按冻结压力合同缩放；
   - 股票只缩放佣金、最低佣金、滑点，印花税和过户费不缩放；
   - 2× 可少买一手，但现金始终非负；
   - 禁止复用 1× fills 后只重算费用。
8. bars、targets、instruments、states 逆序后，四张输出和经济结果一致。
9. 现有 ETF 分红回归仍保持两日权益 `[10000, 10000]`，S0 / S1 调用接口不变。

## 9. 跨平台与数值边界

- 核心循环纯内存，不引入锁、rename 或平台文件系统原语；
- 统一使用 `datetime.date`，不依赖本机时区解析；
- 先稳定排序再迭代；
- 现金 / 费用 / 整手边界用 `Decimal(str(value))` 或同等确定方法，不用裸 float 等号决定多买一手；
- 错误信息不得包含绝对路径；
- Windows 原生作为反馈环，WSL Miniforge base 执行同组定向终验。

## 10. 验收命令

Windows：

```powershell
D:\Miniforge3\python.exe -m pytest tests/unit/test_backtest_timing.py tests/unit/test_market_rules.py tests/unit/test_etf_simulator.py tests/unit/test_daily_simulator.py -q
D:\Miniforge3\python.exe -m ruff check src/quant/backtest/daily_simulator.py src/quant/backtest/simulator.py src/quant/backtest/costs.py src/quant/domain/schemas.py tests/unit/test_daily_simulator.py tests/unit/test_etf_simulator.py tests/unit/test_market_rules.py
D:\Miniforge3\python.exe -m mypy src/quant/backtest/daily_simulator.py src/quant/backtest/simulator.py src/quant/backtest/costs.py
git diff --check
```

WSL base 运行同组 pytest、Ruff、mypy。定向全部绿色后，才在独立 artifact root 运行一次 S0 / S1
兼容回归并比较既有关键结果；不得与 G1 正式状态任务并行争用大规模 I/O。

## 11. 通过条件

- 强制反例全部通过；
- `simulate_etf_targets` 公共接口保持兼容，S0 / S1 关键结果无未解释漂移；
- Windows 与 WSL base 定向测试、Ruff、mypy 通过；
- 路线图 M2 唯一未勾选项只有在以上证据齐全后才能关闭；
- 报告继续披露候选池后见偏差和成本尚未用券商账单校准，不把工程闭环写成策略有效性保证。
