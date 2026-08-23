# M3 G7E R1：正式 A 股单场景账户回放任务单

日期：2026-08-09
状态：**R2 实现、全新独立复验与主 Agent 最终验收 PASS；G7F 仍等待 P0 主验**
环境：Windows 原生 Miniforge 仅作定向反馈；WSL Miniforge `base` 作兼容与 Gate 验证；默认测试不联网、不读取真实账户、不下单
前置：G7B、G7C R3、G7D-F0 R4、G7D-F1 R2、G7D-F2 R3 均已通过主 Agent 最终验收

> 本任务只实现一个正式 A 股成本场景的逐 session 内存账户回放。七张表是普通内存返回值，
> **不是 artifact、不是 verified capability、不是 receipt 或发布成功证据**。0.5×/1×/2× 三场景、指标、
> manifest、StageRunner、receipt 与不可变发布全部属于后续 G7F。

## 1. 目标、前置与唯一职责

G7E 的唯一职责是：从 freshly verified target/plan、唯一正式 market-facts capability、显式基础成本日程、
单个摩擦 multiplier 和初始现金出发，按冻结时序逐日调用 G7C 与 G7D-F2，维护现金、持仓、独立 mark book
和公司行动 replay，最终返回七张确定性内存表。

本包必须是单包实现，不拆 E0/E1，不另建账户 capability、facts capability、transition stage 或中间发布物。
现有 development/example `simulate_a_share_scenario` 及其轻量实现保留；正式 API 使用独立名称，禁止通过
类型分派、隐式 fallback 或改写 development 身份来兼容。

前置权威证据：

- [G7 分包骨架 §8/§9](M3_G7目标到账户回测分包骨架与外部闭环任务单.md)；
- [M3 实施 SSOT §4.8](../M3实施与Agent交接.md)；
- [G7B 任务单](M3_G7B_R1正式BacktestPlanArtifact任务单.md)与
  [G7B 主验](M3_G7B_R1正式BacktestPlanArtifact主Agent最终验收报告.md)；
- [G7C 任务单](M3_G7C_R1正式A股公司行动Entitlement状态机任务单.md)与
  [G7C R3 主验](M3_G7C_R3_正式Transition完整性回归证据主Agent最终验收报告.md)；
- [G7D-F0 任务单](M3_G7D_F0_R1正式A股八表MarketFacts任务单.md)、
  [F0 R3 主验](M3_G7D_F0_R3_publicLoaderClosure与Reload隔离主Agent最终验收报告.md)与
  [F0 R4 benchmark SSOT 主验](M3_G7D_F0_R4_benchmark510300SSOT主Agent最终验收报告.md)；
- [G7D-F1 任务单](M3_G7D_F1_R1正式A股开盘执行事实任务单.md)与
  [F1 主验](M3_G7D_F1_R1正式A股开盘执行事实主Agent最终验收报告.md)；
- [G7D-F2 任务单](M3_G7D_F2_R1正式A股Session订单执行状态转移任务单.md)与
  [F2 R2 主验](M3_G7D_F2_R2_referenceOpen与RejectionNotional闭包主Agent最终验收报告.md)。

若本文摘要与以上生产 API、`src/quant/domain/schemas.py`、`src/quant/domain/enums.py` 或
`src/quant/research/m3/contracts.py` 冲突，以代码 SSOT 和最新主验结论为准，并触发 §12 停止条件；不得由
实现者自行“调和”。

## 2. 冻结 public API、值对象与稳定错误

在 `src/quant/backtest/a_share_simulator.py` 增加：

```python
@dataclass(frozen=True)
class AShareSimulationFreshVerificationContext:
    release: VerifiedG1Release
    facts_fresh_context: AShareMarketFactsFreshVerificationContext

    def __reduce__(self) -> Any:
        raise TypeError("M3_A_SHARE_SIMULATION_INVALID")


class AShareSimulationError(ValueError):
    """Stable formal A-share simulation contract error."""


def simulate_formal_a_share_scenario(
    *,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    facts: VerifiedAShareMarketFacts,
    cost_periods: tuple[AShareCostPeriod, ...],
    multiplier: Decimal,
    initial_cash: Decimal,
    fresh_context: AShareSimulationFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> AShareSimulationResult: ...
```

`AShareSimulationResult` 复用现有 skeleton 值对象，字段保持：

```python
@dataclass(frozen=True)
class AShareSimulationResult:
    multiplier: Decimal
    nav: pl.DataFrame
    trades: pl.DataFrame
    positions: pl.DataFrame
    rejections: pl.DataFrame
    corporate_action_postings: pl.DataFrame
    daily_diagnostics: pl.DataFrame
    entitlements: pl.DataFrame
```

它只是含可变 DataFrame 引用的普通值，不提供 authority。G7F 不得接受 caller 传入该 result，而必须从
fresh upstream 自己调用本 API，并在消费/发布边界对七表逐 Schema、逐行、逐值重算与 whole-rehash。

正式函数的所有失败统一抛 `AShareSimulationError("M3_A_SHARE_SIMULATION_INVALID") from None`。不得向外泄露
路径、hash、内部函数消息、Polars 错误、G7C/F2 细节或 traceback 中的敏感输入。构造 context 时同样使用该稳定
消息；禁止吞错后返回空表或部分账户结果。

## 3. Fresh 链、身份闭包与访问顺序

以下检查必须在初始化 G7C replay、创建账户现金/持仓或读取任何 session batch 前完成：

1. exact type 校验所有 public 输入；`artifact_roots` 继续受 receipt/path SSOT 的 strict root 规则约束；
2. `multiplier` 必须是 finite `Decimal` 且精确属于
   `(Decimal("0.5"), Decimal("1"), Decimal("2"))`；bool、float、字符串均拒绝；
3. `initial_cash` 必须是 finite positive `Decimal`；
4. `cost_periods` 必须是非空 exact tuple，元素 exact `AShareCostPeriod`；所有 Decimal 分量 finite/nonnegative，
   日期闭区间连续无重叠，只有最后 period 的 `effective_to=None`，每个 execution date 精确匹配一个 period；
5. **exact once** 调用 public `verify_backtest_plan_artifact`：

```python
fresh_plan = verify_backtest_plan_artifact(
    root=plan.root,
    receipt_path=fresh_context.facts_fresh_context.plan_receipt_path,
    target=target,
    release=fresh_context.release,
    folds=fresh_context.facts_fresh_context.folds,
    experiment=fresh_context.facts_fresh_context.experiment,
    config=fresh_context.facts_fresh_context.config,
    fresh_context=fresh_context.facts_fresh_context.plan_fresh_context,
    artifact_roots=artifact_roots,
)
```

6. `fresh_plan` 的规范 root、manifest、manifest SHA-256、plan receipt SHA-256 必须与 outer `plan` exact；target
   由该 verifier 递归 fresh verification，不另写 target verifier 或自报 hash；
7. 全程只使用 `fresh_plan.scheduled_targets` 的本地 clone；禁止使用 outer `plan.scheduled_targets`；
8. 访问 `facts.identity` 触发唯一 F0 capability 的完整性验证，并要求其 G1 release id/hash、plan manifest/hash、
   plan receipt 与 fresh plan/release exact；再从 capability 属性取得所需八表 clone；
9. execution dates 非空、严格递增，精确等于 window，首尾等于 `first_execution_date`/
   `terminal_valuation_date`，每个日期在 facts 的 SH open calendar 中且 schedule batch 完整；
10. 完成上述闭包后，才允许 `initialize_formal_a_share_entitlement_replay(facts=facts)`。

禁止重新调用 `load_verified_a_share_market_facts`、复制其实现、制造第二 capability、接收裸 facts frames、
caller hash、裸 open-state、caller G7C replay/transition 或 caller F2 transition。G7C/F2 transition 只能由本函数
当日调用实际 public API 后立即消费。

## 4. 单 session 时序与账户状态边界

对 `fresh_plan.manifest.window.execution_dates` 每日严格执行：

```text
上一日买入 rollover 为 sellable
  -> G7C advance_formal_a_share_entitlements_pre_open
  -> 入账 cash_delta / settled_stock
  -> 独立 mark book 的盘前 mark 与 pre_trade_equity
  -> active batch 补完整目标域
  -> execute_formal_a_share_session（exact once）
  -> raw close / FULL_DAY 合法 carry 的收盘 mark
  -> close valuation
  -> G7C capture_formal_a_share_entitlements_record_close
  -> 当日最终七表投影
```

- rollover 只把此前 session 的 `unsettled_quantity` 转入 `sellable_quantity`；数量不变；
- G7C 当日结算红股加入总数量与 sellable，不能误记为当日买入 unsettled；cash delta 先于 F2 入账；
- capture 使用 F2 后实际总持仓，包含当日买入与原持仓，因而 record-date 当日买入有权；ex-date 当日买入不能
  追溯取得此前 record-close 权益；
- close valuation 在 capture 前计算；但七表是当日完整处理后的最终快照，必须在 capture 后投影，所以
  CAPTURE posting/entitlement 当日可见；CAPTURED leg 不进入 NAV 应收；
- terminal record-close 后 replay `phase` 必须为 `COMPLETE`，但尚未到 pay/list date 的 leg 可以保持未 SETTLED
  并出现在 entitlement 快照；
- CAPTURE posting 必须直接使用 G7C formal transition，金额、股数与 rounding delta 按其原值；禁止复制
  development `_capture_posting` 或在 G7E 伪造 capture 金额/股数。

## 5. 独立 mark book 与 FULL_DAY/公司行动估值

G7E 必须维护账户 `PositionBook` 之外的内部 Decimal mark book。其域至少覆盖：

```text
正持仓 ∪ 当日 active target ∪ 所有未双 leg SETTLED entitlement/event symbol
```

卖出到零不得删除最后合法 mark。原因是原持仓卖空后，已登记的 RECOGNIZED stock receivable 仍需每日估值；
stock-list-date 即使 FULL_DAY 无 bar，也必须用历史 mark 生成新的 sellable position。

mark 规则冻结为：

- 当日有唯一 raw bar：盘前使用 raw open，收盘使用 raw close；PARTIAL 或开盘阻塞只影响 F1/F2 可执行性，
  不抹掉已有 raw 估值事实；
- FULL_DAY 且无 bar 的普通日：沿用 previous mark；
- FULL_DAY 且为公司行动 effective date：只允许同一 `facts.corporate_action_reconciliation` 的唯一闭合事件集合
  与 positive `actual_factor_ratio`，调用 public
  `mark_full_day_event_from_factor(previous_mark=..., actual_factor_ratio=...)`；
- 禁止用现金/送转 entitlement 公式反推除权价、未来 close、forward-fill 数据表、0 或 caller mark 回退；
- 非 FULL_DAY 缺 bar、需要估值却无 previous mark、reconciliation 缺失/重复/event-set mismatch/ratio 非正均失败；
- 新结算 stock 从 mark book 取得 mark；若 mark 不存在则失败，不用 0 创建持仓。

F0 已关闭八表来源、窗口、reconciliation 和 `510300.SH` benchmark SSOT；G7E 不复制 facts 验证器或 benchmark
selector，也不读取 benchmark 计算收益。

## 6. 完整目标、F2 消费与 Decimal 账户恒等式

初始状态固定为 `cash=initial_cash`、空 `PositionBook`、空 entitlement replay。首个 execution open 的
`pre_trade_equity=initial_cash`。

每个 active batch 从 fresh scheduled targets 取出并移除 `execution_date` 投影；对所有当前正持仓但 batch 未列
证券补同一批次身份下的 `weight=0`。事件-only、无持仓证券不伪造订单。目标域排序与输入行序无关。

按日期选唯一 base `AShareCostPeriod`，然后 exact once 调：

```python
transition = execute_formal_a_share_session(
    facts=facts,
    date=date,
    targets=complete_targets,
    positions=pretrade_positions,
    cash=cash,
    pre_trade_equity=pre_trade_equity,
    base_cost_period=base_cost_period,
    friction_multiplier=multiplier,
)
```

G7E 只消费 transition 的 intents、post cash/positions、fills、rejections、reference opens/hash 与
`buy_allocation_lambda`；完整目标差量、先卖后买、T+1、分板块 lot、开盘状态、费用、滑点、现金门禁和
Fraction allocation 全部以 F2 为唯一实现，G7E 不复制或“校正”。阻塞卖出绝不提供预期现金。

金额、费率、价格、mark、现金、应收、权益、费用累计与 turnover 内部统一 `Decimal`；Float64 输入只允许
`Decimal(str(value))`。只有七表出口执行 `float(...)` 单向投影，任何现金可行性、守恒或验收不得用 float epsilon。

盘前与收盘恒等式：

```text
pre_trade_equity = cash
                 + Σ(position quantity * pre-open mark)
                 + RECOGNIZED cash receivable
                 + Σ(RECOGNIZED stock receivable * mark)

equity = close cash + close market value
       + RECOGNIZED cash receivable
       + RECOGNIZED stock receivable value
unit_nav = equity / initial_cash
daily_return = equity / previous_close_equity - 1
```

首日 `previous_close_equity=initial_cash`。CAPTURED 与 SETTLED leg 不重复计应收。

每日 realized turnover 必须为：

```text
gross_turnover = Σ(abs(fill.notional)) / pre_trade_equity
one_way_turnover = gross_turnover / 2
```

严禁复制 development 的 `max(buy_notional, sell_notional) / pre_trade_equity`。

## 7. 七张内存表、Schema 与交叉复算

直接复用 `src/quant/domain/schemas.py` 已有七个 `AShareSimulation*Schema`；本包不得修改 Schema 或 contracts。
精确列、dtype、nullable、唯一键与排序以 G7 骨架 §8 为准：

| result 字段 | 精确逻辑表 |
|---|---|
| `nav` | `date,pre_trade_equity,cash,market_value,cash_receivable,stock_receivable_value,equity,unit_nav,daily_return,cumulative_commission,cumulative_stamp_tax,cumulative_transfer_fee,cumulative_slippage_cost` |
| `trades` | `date,symbol,side,quantity,reference_open,execution_price,notional,commission,stamp_tax,transfer_fee,total_fee,slippage_cost` |
| `positions` | `date,symbol,quantity,sellable_quantity,unsettled_quantity,mark_price,market_value,target_weight,target_quantity,pending_exit` |
| `rejections` | `date,symbol,side,reason,requested_quantity,filled_quantity,rejected_quantity,rejected_notional` |
| `corporate_action_postings` | `date,event_id,symbol,posting_type,cash_amount,stock_quantity,cash_rounding_delta,cash_state_before,cash_state_after,stock_state_before,stock_state_after` |
| `daily_diagnostics` | `date,n_target_symbols,n_position_symbols,n_order_intents,n_trades,n_rejections,pre_trade_equity,gross_turnover,one_way_turnover,buy_allocation_lambda,cash_after` |
| `entitlements` | `date,event_id,symbol,record_quantity,cash_entitlement_gross,stock_entitlement,cash_state,stock_state,cash_receivable,stock_receivable,stock_receivable_value` |

要求：

- 空表仍有 exact Schema；nullable 只允许 skeleton 已冻结的四处；
- positions 只列 `quantity>0`，且 `sellable+unsettled=quantity`；mark/MV 来自独立 mark book；
- `target_quantity` 只在 F2 无可信 open、desired quantity 不可知时为 null；`pending_exit` 精确为目标 0 且仍持有；
- entitlements 列所有未双 leg SETTLED 事件；RECOGNIZED stock value 使用 mark book；
- postings 只列当日 G7C 状态变化，不由 G7E 合并或改写；
- diagnostics：`n_target_symbols` 是补零前 active batch symbol 数；`n_position_symbols` 是 F2 前正持仓数；
  intents/fills/rejections 分别按 F2 transition 对象/行计数；`cash_after` 是 F2 post cash；无 buy allocation 时
  lambda 为 null；
- 每日和最终用 Decimal 重算 NAV、position、trade fee/cumulative fee、cash/posting/rounding、数量守恒、
  cash_after 和 turnover；同一逻辑输入任意 row shuffle 返回相同排序与逻辑内容。

七表到此仍只是内存 DataFrame；不得在 G7E 写 Parquet、计算物理文件 hash 或把空表存在解释成 artifact 完整。

## 8. G7F、receipt、publication 与 whole-rehash 边界

以下全部明确排除在本包外：

- 0.5×/1×/2× 三场景 orchestration；
- `AShareScenarioMetricsV1`、benchmark return、退出成本、acceptance metrics；
- scenario/root manifest、JSON/Parquet writer、output root、StageRunner、receipt、final rename/no-clobber；
- `VerifiedBacktestArtifact` builder/verifier 与任何路线图/Gate 状态更新。

后续 G7F builder 必须自己从 fresh upstream 构造一次唯一 facts capability，用相同 target、fresh plan、facts 与
initial cash 独立调用 G7E 三次；不得复用 1× fills，不得接 caller result/transition/metrics/schedule。G7F verifier
再次独立重跑三场景并逐表 whole-rehash 后才有资格发布。

G7F 每场景才输出七表、`metrics.json`、`manifest.json`，根目录才输出 `backtest_metrics.json` 与
`backtest_manifest.json`。backtest receipt 输入闭包必须是 target bundle、plan bundle、experiment bundle、
G1 manifest/receipt 与 market-facts 八文件；输出精确覆盖 `3 * (7 tables + metrics + manifest) + 2 root files`，
少一张空表也失败。scenario `cost_periods_sha256` 由 config 派生的该场景 effective periods canonical JSON 计算；
plan `cost_schedule_sha256` 仍是全 schedule SSOT。G7E 不生成或接受这两个 digest。

## 9. 文件白名单与角色隔离

实现 Agent 唯一允许修改/新增：

1. `src/quant/backtest/a_share_simulator.py`；
2. `src/quant/backtest/__init__.py`；
3. `tests/unit/test_m3_g7e_formal_a_share_simulator.py`；
4. `tests/integration/test_m3_g7e_formal_a_share_simulator_golden.py`；
5. `docs/framework/agent/M3_G7E_R1正式A股单场景账户回放交付报告.md`。

独立初验 Agent 保持生产与实现测试只读，唯一可写：

- `docs/framework/agent/M3_G7E_R1正式A股单场景账户回放独立初验报告.md`。

主 Agent 最终验收唯一可写其验收报告：

- `docs/agent/M3_G7E_R1正式A股单场景账户回放主Agent最终验收报告.md`。

禁止修改本任务书、`a_share_execution.py`、`corporate_actions.py`、`a_share_plan.py`、`a_share_reporting.py`、
`contracts.py`、`schemas.py`、config、G7F、既有测试/报告/SSOT。禁止联网、访问真实 `data/`、凭据、真实账户、
券商 SDK、add/commit/push、删除或清理共享 worktree。

## 10. 必测反例与 golden fixture

实现测试至少覆盖：

1. facts 签发后 outer plan scheduled frame 被替换，或 target/plan manifest/receipt/release 混配：在账户创建前
   由 fresh verifier 拒绝；caller 自报相同 hash 不得通过；
2. API 无 caller F2 transition、G7C transition/replay、裸 facts/open-state/DataFrame 参数；伪造 capability 拒绝；
3. 原股 record-close 捕获后卖到零，stock leg 仍 RECOGNIZED；随后 FULL_DAY stock-list-date：last mark 保留，
   receivable 正确估值并转成 sellable position，不得为 0 或因当前 position 不存在而丢失；
4. record-date 当日买入计入 capture，ex-date 当日买入不得追溯享权；cash/stock 不同结算日独立；
5. CAPTURE posting 的 cash/stock/rounding 为 G7C 原值，CAPTURED 不进 NAV；RECOGNIZED 才进应收；
6. asymmetric buy/sell 使 `gross/2 != max(buy,sell)/equity`，输出必须取 `gross/2`；
7. blocked sell 不供买入、T+1 partial、主板/科创板 lot、最低佣金和 Fraction allocation 与 actual F2 transition
   精确一致，G7E 不二次撮合；
8. FULL_DAY 普通 carry 与 CA factor adjustment；missing/duplicate/mismatch/nonpositive reconciliation、
   非 FULL_DAY 无 bar、无 prior mark 均稳定失败；
9. 无 open 且正目标时 nullable target/rejection quantity 语义保持 F2，不用 close 反推；
10. terminal 未完成退出保留 position/pending_exit，不强平；terminal replay phase COMPLETE；
11. 三证券至少五个 session 的人工 golden：正常换仓、涨停买拒绝、全日停牌跨现金分红、factor-ratio mark、
    T+1 部分卖、blocked sell、最低佣金分配、周五信号周一终值；逐日核对七表；
12. target/facts/frame 输入行序打乱，七表排序与逻辑内容不变；返回 result 被篡改不能被后续 G7F 当 authority。

formal 测试的模块化边界以§13为准；禁止 `object.__new__`、monkeypatch type、伪 HMAC/registry/seal 或把
development wrapper 冒充 formal。

## 11. 双平台验证命令与通过条件

Windows 原生 Miniforge 只作快速反馈：

```powershell
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_g7e_formal_a_share_simulator.py tests/integration/test_m3_g7e_formal_a_share_simulator_golden.py -q
D:\Miniforge3\python.exe -m ruff check src/quant/backtest/a_share_simulator.py src/quant/backtest/__init__.py tests/unit/test_m3_g7e_formal_a_share_simulator.py tests/integration/test_m3_g7e_formal_a_share_simulator_golden.py
D:\Miniforge3\python.exe -m mypy src/quant/backtest/a_share_simulator.py
```

WSL Miniforge `base` 定向兼容验证必须在对应 worktree 路径执行：

```bash
cd /home/mabw/AI_Coding_win/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal
/home/mabw/miniforge3/bin/conda run -n base python -m pytest tests/unit/test_m3_g7e_formal_a_share_simulator.py tests/integration/test_m3_g7e_formal_a_share_simulator_golden.py -q
/home/mabw/miniforge3/bin/conda run -n base ruff check src/quant/backtest/a_share_simulator.py src/quant/backtest/__init__.py tests/unit/test_m3_g7e_formal_a_share_simulator.py tests/integration/test_m3_g7e_formal_a_share_simulator_golden.py
/home/mabw/miniforge3/bin/conda run -n base mypy src/quant/backtest/a_share_simulator.py
```

当前本机 WSL 路径若实际落在 `/mnt/f`/DrvFS，则绿色只算双平台兼容证据，不得宣称 Linux/ext4 Gate 已关闭。
独立初验通过后，主 Agent 依据里程碑风险在正式 WSL base 环境执行：

```bash
/home/mabw/miniforge3/bin/conda run -n base sh -lc 'ruff check src tests && mypy src && pytest -q'
```

通过条件：所有冻结反例与 golden 逐日手算通过；无网络/真实数据/发布副作用；diff 只含角色白名单；Windows
结果不替代 WSL；实现报告不得把自测称为初验、主验、G7、M3 或 Gate PASS。

## 12. 停止条件与外部闭环

以下任一出现，实施 Agent 必须停止扩大实现并在交付报告中给出脱敏最小证据；不得越过白名单修补：

- actual F0/G7C/F1/F2/public plan verifier 的签名、稳定类型或身份语义与本文冲突；
- 需要修改 `a_share_execution.py`、`corporate_actions.py`、`a_share_plan.py`、`a_share_reporting.py`、Schema、
  contracts 或 config 才能完成；
- 无法在本包内 exact-once fresh verify plan，或必须使用 outer/stale scheduled targets；
- 被迫接受 caller transition、replay、裸 frames、caller mark/hash，或创建第二 facts capability；
- 无法维护独立 mark book、FULL_DAY 估值或 Decimal 账户/turnover 恒等式；
- formal fixture 只能通过伪造 capability、弱化 fresh verifier 或读取真实数据建立；
- 需要联网、真实凭据、券商/账户、真实下单、文件发布或破坏性操作；
- shared worktree 出现与白名单重叠的并发写入，无法证明本包 diff 来源。

闭环固定为：

```text
主 Agent 冻结本任务书
  -> 全新外部实现 Agent 按白名单实现、自测并写交付报告
  -> 未参与实现的全新外部 Agent 只读独立初验并增加未公开反例
  -> 若失败，回原实现职责返工，再由新的独立上下文复验
  -> 独立初验 PASS 后，主 Agent 执行最终契约、fresh 链、whole-rehash、双平台与回归验收
```

实现者、独立初验者与主验职责不得合并。只有主 Agent 最终验收通过，G7E 才可标记 PASS；这仍不等于 G7F、
完整 G7、Linux/ext4 Gate 或 M3 完成。

## 13. Formal 测试的模块化信任边界补充（2026-08-09）

实现首轮实证：完整 public G1 chain 固定 exact 300 成分，单次在600秒内尚未完成；把成分缩到30会被
`G1BuildInputs` 正确拒绝。仓库没有可复用的真实 retained G1 release fixture；手工自签17个artifact+manifest再
调用 verifier 会伪造来源，禁止采用。把一千余行 G1→facts 长链复制进 G7E tests 也违反最小实现与测试分层。

因此 G7E 测试按已分别主验的模块边界冻结：

1. F0 R4 的任务、实现测试、独立复验与主验继续唯一负责“G1/G7B fresh → exact process-local facts capability”
   的来源闭包；G7E 不重复验收 G1 builder、G7B artifact或 F0 capability signer。
2. G7E unit/golden fixture可复用现有 F0 formal 测试的窄 `_issued_capability` 辅助来签发 exact、内容绑定、可被
   public property重验的测试 facts；这只构造 G7E 的直接上游输入，不进入生产，不证明 G1来源，不得复制/修改
   F0 HMAC/registry/closure，也不得新增 tests/support 长链文件。
3. G7E tests 可 monkeypatch其模块实际 import 的 public `verify_backtest_plan_artifact`：正向必须 exact一次调用并
   返回与outer plan逐字段相等的exact `VerifiedBacktestPlanArtifact`；另测 hostile异常、不同exact返回、stale outer
   scheduled frame，证明账户创建前fail closed且只使用fresh返回。不得monkeypatch G7E内部账户数学、G7C/F2 public
   API、facts property或稳定错误翻译。
4. G7C 与F2必须调用 actual public API；禁止 caller transition/replay/裸frame。F0 fake/dev/subclass仍由G7E public
   入口 exact type及property重验拒绝。
5. 实现、独立初验与主验必须把 F0 R4、G7B、G7C、F1、F2 的现有正式测试作为邻接回归一起执行，不能仅凭
   G7E测试宣称整条来源链；报告必须明确这种模块化fixture边界。
6. 删除当前未验证、超长且含诊断输出的 `tests/support/m3_formal_a_share_chain.py` 草稿；不得保留死代码或把
   30成分失败路径伪装成fixture。若使用上述边界仍无法覆盖G7E账户语义，停止并回主Agent。
7. 禁止为构造 `AShareSimulationFreshVerificationContext` 手工复制数百行 nested manifest/spec字段。两个新测试
   可按现有G7B测试相同的动态导入方式复用 `test_m3_formal_target_artifact.py::_context`，仅取得其已经由公开
   constructors建立的 exact folds/experiment/config/spec/path/artifact值，再用公开 constructor组装
   `BacktestPlanFreshVerificationContext` 与simulation context。该helper的release是低层空壳/development替换，禁止
   复用；新测试可额外用公开 `G1Release`、`G1ManifestV5`、`G1QualityReportV1`、`VerifiedG1Release`
   constructors建立一份约60行的exact test value，并令facts identity与其release id/hash一致。不得调用target
   support的publish作为G7E来源证据；这些release/context值只满足§13.3被mock plan verifier的exact参数，不得传给
   未被mock的上游 verifier或表述为verified来源。禁止bare/object.__new__/SimpleNamespace/Development manifest。
   生产context的nested exact校验保持不变；fixture helper只在两个新测试文件之一定义并由另一文件复用，不新增
   第三个support文件。

## 14. R1 独立初验 Float64 NAV 投影返工（2026-08-10）

### 14.1 现象、根因与必须保持的不变量

独立初验构造了合法的“record-date 空仓、ex-date 当日首次买入”场景。账户内部 Decimal 账严格满足
`60129.64 + 39800.0 + 0 + 0 = 99929.64`，但 `_formal_nav_row` 把四个分量与 `equity` 各自独立转为
Float64；权威 `AShareSimulationNavSchema` 随后在 Float64 域按
`cash + market_value + cash_receivable + stock_receivable_value` 精确复算，二进制舍入路径不同使合法结果
被 public API 自身拒绝。

R2 必须同时保持：

1. 所有账户经济计算、NAV、收益与守恒继续只在私有 Decimal context 中完成，并在投影前严格验证 Decimal
   恒等式；禁止 float epsilon 参与账户决策或反向修正 Decimal 账；
2. 不修改、不绕过、不放宽权威 Schema；
3. 七表出口先分别投影四个 Float64 分量，再严格按 Schema 的同一左结合运算顺序由这些已投影分量计算输出
   `equity`，确保输出域自身闭合；`unit_nav` 与 `daily_return` 的经济值仍来自原 Decimal equity，不得改用投影
   舍入值驱动后续 session；
4. 不改变 record/ex 权益时序、F0/G7C/F1/F2、mark book、费用、turnover 或 public API。

### 14.2 新增回归与通过条件

- 把独立初验的 ex-date 首次买入固化为 public regression：必须产生 BUY，但不得追溯产生该事件 entitlement 或
  CAPTURE posting；public API 返回全部七表且通过现有 Schema；
- 至少包含一组“Decimal 恒等、各字段独立 `float()` 后不满足 Schema exact 加和”的数值，并断言最终输出的
  Float64 `equity` 精确等于 Schema 顺序的四分量和；
- 原六项 G7E unit/golden、hostile Decimal context、fresh exact-once、独立 mark book、gross/2 与所有邻接保持
  绿色；Windows 与 WSL base 均运行定向测试、Ruff、mypy、cold import、diff-check；
- 唯一 R2 交付报告为 `M3_G7E_R2_Float64NAV投影闭包返工交付报告.md`。返工后必须由未参与 R2 的全新独立
  上下文复验；PASS 也只解锁主验，不等于 G7F、ext4 或 M3 Gate。
