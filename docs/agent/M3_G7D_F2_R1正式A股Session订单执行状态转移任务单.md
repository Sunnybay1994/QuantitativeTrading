# M3 G7D-F2 R1：正式 A 股 Session 订单执行状态转移任务单

日期：2026-08-09  
状态：**R3 null-gap ambient Decimal 实现、全新独立复验与主 Agent 最终验收 PASS；仍等待 F1 R2 后恢复 G7E**  
性质：formal 内存订单执行纯状态转移合同；不运行完整账户、不发布 artifact/receipt，不等于完整 G7E、真实成本 Gate、Linux/ext4 或 M3 Gate

## 1. 目标、前置与唯一职责

G7D-F2 把一个 execution session 的 exact formal market facts、盘前账户值、完整目标权重和显式成本值，确定性
映射为一次“目标差量 -> 先卖 -> 后买”的内存状态转移。它负责：

- 在同一次 public 调用内重新构造 G7D-F1 open-state；
- 完整目标差量、分板块数量规则与可审计 intent；
- 停牌/开盘未知/涨跌停方向拒绝；
- 卖出 T+1 residual、lot residual、卖款与费用；
- 买入真实费用下的 exact `Fraction` breakpoint 与离散余量分配；
- 返回排序、守恒且绑定 facts identity/date/显式成本输入的 session transition。

冻结顺序为：

```text
G7P0 -> G7A -> G7B -> G7D-F0 -> G7C -> G7D-F1 -> G7D-F2 -> G7E -> G7F
```

实现前置必须同时满足：

1. [`M3_G7D_F0_R1正式A股八表MarketFacts任务单.md`](M3_G7D_F0_R1正式A股八表MarketFacts任务单.md)
   保持 R3 主 Agent 最终验收 PASS；
2. [`M3_G7C_R1正式A股公司行动Entitlement状态机任务单.md`](M3_G7C_R1正式A股公司行动Entitlement状态机任务单.md)
   保持 R3 主 Agent 最终验收 PASS；
3. [`M3_G7D_F1_R1正式A股开盘执行事实任务单.md`](M3_G7D_F1_R1正式A股开盘执行事实任务单.md)
   已经实现、全新独立初验和主 Agent 最终验收 PASS；
4. F1 exact public API、`AShareExecutionError` 与 `M3_A_SHARE_EXECUTION_INVALID` 未变化。

本包不负责 G7C replay、盘前公司行动 cash/stock 入账、买入 rollover、FULL_DAY/公司行动 mark、盘前权益构成、
收盘估值、record-close capture、NAV、七张结果表、指标或 artifact。上述职责全部保留给串行后续 G7E。

## 2. SSOT 与当前 primitive 边界

- 高层账户顺序、目标、T+1、离散现金和费用语义：[`docs/M3实施与Agent交接.md`](../M3实施与Agent交接.md)
  §4.11。
- G7D/G7E 机械合同：[`M3_G7目标到账户回测分包骨架与外部闭环任务单.md`](M3_G7目标到账户回测分包骨架与外部闭环任务单.md)
  §7–§8。
- formal facts 与潜在持仓域：G7D-F0 任务单 §2–§7。
- entitlement/account 边界：G7C 任务单 §3–§7。
- formal open-state、instrument/lifecycle/board：G7D-F1 任务单 §3–§7。
- 枚举 SSOT：`src/quant/domain/enums.py` 中的 `AShareBoard`、`ExecutionRejectReason`、`OrderSide`。
- target/open-state Schema SSOT：`src/quant/domain/schemas.py`。
- 成本 period 与 plan cost identity：`src/quant/research/m3/contracts.py` 的 `AShareCostPeriod`、
  `BacktestPlanManifestV1`，以及 G7B 已验真的 `cost_schedule.json`/scientific config。

现有 `build_target_order_intents`、`execute_sell_intents`、`allocate_buy_lots`、
`compute_a_share_fee_components` 是 development/raw-value primitive。它们接收 caller 裸 `open_states`，部分内部还按
symbol 排序或只调用无 facts 的板块 resolver；因此不能直接作为 formal public 边界。F2 可以在保持既有公开行为
和 development 测试不变的前提下抽取、复用或收紧私有计算核心，但不得把 raw primitive 的成功包装/重签为 formal。

## 3. 冻结 public API 与 transition 值对象

在 `src/quant/backtest/a_share_execution.py` 新增并安全导出：

```python
@dataclass(frozen=True)
class AShareSessionExecutionTransition:
    input_market_facts_sha256: str
    date: dt.date
    pre_trade_cash: Decimal
    pre_trade_positions: PositionBook
    pre_trade_equity: Decimal
    base_cost_period: AShareCostPeriod
    friction_multiplier: Decimal
    effective_cost_period: AShareCostPeriod
    intents: tuple[TargetOrderIntent, ...]
    post_trade_cash: Decimal
    post_trade_positions: PositionBook
    fills: tuple[ExecutionFill, ...]
    rejections: tuple[ExecutionRejection, ...]
    buy_allocation_lambda: Fraction | None

def execute_formal_a_share_session(
    *,
    facts: VerifiedAShareMarketFacts,
    date: dt.date,
    targets: pl.DataFrame,
    positions: PositionBook,
    cash: Decimal,
    pre_trade_equity: Decimal,
    base_cost_period: AShareCostPeriod,
    friction_multiplier: Decimal,
) -> AShareSessionExecutionTransition: ...
```

public 参数必须 keyword-only。禁止新增或接受 `open_states`、release/plan/target artifact、裸 path、sessions、
caller 自报 facts hash、price tick、rounding mode、network/account callback 或 output root。

transition 是一次函数调用的不可变审计值，不是上游 facts/plan/account capability，不建立 signer、seal、registry、
mint、restore 或 generic factory。后续 G7E **不得提供“接受 caller 传入 transition”入口**；它必须自己调用
`execute_formal_a_share_session` 并立即消费返回值。transition 的 `__post_init__` 仍须 exact-type、排序、金额、数量
和局部守恒 fail closed，但不得把普通可构造值对象宣称为 fresh upstream authority。

## 4. Formal facts、F1 重建与输入访问顺序

formal public 入口顺序固定为：

1. 在任何 facts property、target frame 行或账户字段的深读取前，先检查 exact
   `VerifiedAShareMarketFacts`、`dt.date`、`pl.DataFrame`、tuple、`Decimal`、`AShareCostPeriod` 类型；bool 不得冒充
   int/date/Decimal。
2. 从 `facts.identity.input_market_facts_sha256` 取得唯一 facts identity；property access 触发 F0 既有内容/来源重验。
3. 从 targets 与 positive positions 构造严格 symbol 升序的并集；不得接收 caller 自报 symbols。
4. exact 一次调用 public
   `build_formal_a_share_open_execution_states(facts=facts,date=date,symbols=symbols)`；不得复制 F1 parser、从裸
   bars/limits/suspensions 另建第二实现，也不得接收调用前已存在的 open-state frame。
5. 每个 symbol 的 quantity rule 必须由
   `resolve_formal_a_share_order_quantity_rule(facts=facts,date=date,symbol=symbol)` 得到；现有 raw resolver 只可作为
   计算 helper，结果必须与 formal resolver exact 一致。
6. 所有 target/account/cost 数学成功后构造 transition；返回前逐项重算守恒和固定顺序。

F2 不回调 G1/G7A/G7B verifier，不读 plan root/cost file，不访问 corporate actions/reconciliation/benchmark
close、label 或未来行情。formal/dev facts 混配、fake/subclass 必须在任何 frame/property access 前稳定失败。

## 5. 显式账户与完整目标域

### 5.1 盘前账户输入

- `positions` 必须 exact tuple，物理顺序严格 symbol 升序、symbol 唯一；每项 exact `AccountPosition`，且
  `quantity>0`、`sellable_quantity>=0`、`unsettled_quantity>=0`、二者之和 exact 等于 quantity，mark 为 finite 正
  Decimal。空 tuple 合法。
- 每个 position symbol 必须属于当日 F1 formal 请求域。F2 不接收零 quantity 行；卖尽后的 post state 删除该行。
- `cash` 必须 finite、非负 exact Decimal；`pre_trade_equity` 必须 finite、正 exact Decimal。
- F2 不接收 receivable 明细，因此只验证
  `pre_trade_equity >= cash + sum(quantity * mark_price)`；G7E 负责证明差额 exact 等于 RECOGNIZED cash/stock
  receivable。F2 不得自行重算或猜应收。
- G7E 调用 F2 前必须已经完成：上一 session 买入 rollover；G7C pre-open recognize/settle；cash delta 和 settled
  stock 入账；FULL_DAY/公司行动盘前 mark；盘前权益。G7C 同日 settled stock 进入 F2 时为 sellable。

### 5.2 target 输入与完整差量

- `targets` 必须是非空、exact `TargetWeightSchema` 五列
  `as_of,strategy,strategy_version,symbol,weight`，dtype/nullable/唯一键 exact；物理顺序严格 symbol 升序，禁止
  `.sort()`/去重修复。
- 全表只有一个 exact as_of、strategy 和 strategy_version；`as_of < date`。F2 不证明“严格下一 SH session”，该
  lineage/scheduling 由 G7B/G7E fresh 验证。
- 每个 target symbol 必须属于 facts/instrument/F1 当日域。weight 从 Float64 只用 `Decimal(str(value))`，finite、
  非负；总权重必须不超过 Decimal 1，不用 float tolerance。
- G7B target batch 是 eligible domain 的完整目标；F2 再把“当前正持仓但 target 缺行”的 symbol 补为显式 0，
  得到 `(target symbols ∪ position symbols)` 完整账户差量域。补零只用于账户退出语义，不修改 caller frame、不写
  artifact，也不能掩盖 target 内部缺失/重复/乱序。
- 对每个 symbol：
  `target_notional = Decimal(str(weight)) * pre_trade_equity`。有 open 时
  `raw_target_quantity=floor(target_notional/open)`，再按 formal board rule 得到 target position；target=0 请求清空
  全部持仓。
- 任意正 target 只要因最小申报量映射到 0，都必须保留 BUY intent 并产生 `LOT_CONSTRAINT` 名义缺口；包括
  `raw_target_quantity=0`、主板/创业板 1–99 股与科创板 1–199 股，不能作为“无差量成功”跳过。
- 无可信 open 且 target value 与 current marked value 不同：side 由两者比较，raw/target/requested quantity 均为
  null；`rejected_notional=abs(target_notional-current_mark_value)`。禁止用未来 close 反推数量，禁止对 0 target
  卖出写 0 名义拒绝。
- intent 物理顺序严格 symbol 升序；每个 symbol 至多一条。无差量不写 intent/rejection。

## 6. 成本、滑点、tick 与 Decimal

- `base_cost_period` 必须 exact `AShareCostPeriod`，且 `effective_from <= date <= effective_to`（开放末段允许
  `effective_to=None`）。F2 只验证并使用 caller 显式 period，不证明它来自哪份 schedule。
- `friction_multiplier` 必须 exact finite Decimal，且 exact 为 `Decimal("0.5")`、`Decimal("1")` 或
  `Decimal("2")`。
- `effective_cost_period` 只缩放 `commission_rate`、`commission_min`、`slippage`；`stamp_tax_sell` 与
  `transfer_fee` 必须逐字段保持 base 值。不得缩放税费、日期或另建平行费率。
- CNY tick 私有固定为 `Decimal("0.01")`；执行价按 `BUY_CEIL_SELL_FLOOR_TICK_V1`：open 施加比例 slippage，
  BUY 向上、SELL 向下取 tick，然后夹在合法 limit 内。
- 费用逐分项 Decimal：
  `commission=max(notional*rate,minimum)`，stamp 仅 SELL，transfer 双边；每项独立
  `EACH_COMPONENT_HALF_UP_CENT_V1` 到分，总 fee 为三项精确和。slippage cost 为成交量乘 open 与 execution price
  的方向差，不能再重复从 cash 扣一次。
- 所有中间运算使用模块私有 `localcontext`，precision 至少 50；普通乘除在该 context 中不得静默因 ambient
  precision/rounding 改变，只有明确的 tick/cent 步骤允许指定 rounding。不得修改进程 ambient Decimal context，
  不得 `Decimal(float)` 或 float epsilon。

G7B `cost_schedule.json` 和 scientific config 是成本来源 SSOT。F2 接受显式值，因此 F2 PASS 只证明数学合同；
后续 G7E 必须 fresh 验证 plan、从已验真 schedule 选择 date 唯一 base period，并证明其 canonical digest exact 等于
plan manifest，再调用 F2。若要让 F2 自己证明 cost provenance，必须先重冻并由 G7B/G7E 提供窄 verified cost view；
不得在 F2 中读取 caller path 或伪造 capability。

## 7. 卖出状态转移、拒绝优先级与守恒

先处理全部 SELL intent，symbol 升序：

1. 无/不可信 open-state；
2. 对应方向涨跌停；
3. `sellable_cap=min(requested,sellable_quantity)`，`requested-sellable_cap` 为 `T_PLUS_ONE` residual；
4. 从 sellable cap 向下取满足盘前总持仓板块规则的最大合法数量，其余为 `LOT_CONSTRAINT` residual；
5. 对合法数量按 execution price 成交，cash 增加 `notional-total_fee`。

同一 requested share 只能被 fill、T+1 或 lot exact 一次计数。不得因部分未结算整单拒绝，不得把裸
`min(requested,sellable)` 当成交易所合法订单。例如主板盘前持仓 257、sellable 120、请求卖 157，必须是
fill 100、T+1 37、lot 20。

FULL_DAY、开盘停牌/未知、lower-limit 阻断产生零 fill；blocked sell 的预期收入绝不能进入后续 buy cash。卖尽后
position 从 post book 删除；部分卖出保持原 unsettled，sellable 减少实际 fill。

## 8. 买入 Fraction 分配、现金与 post state

全部 SELL 完成后，使用实际 sell cash 处理 BUY：

- 每个买单以期望股数 `d_i` 与 formal board 合法集合 `V_i` 建模；先分离因 target quantity rule 产生的
  `LOT_CONSTRAINT`。
- breakpoint exact 为 `{0,1} ∪ {q/d_i | q∈V_i,q<=d_i}`，使用 `fractions.Fraction`；选择整组真实执行价和完整
  分项费用可付的最大共同 lambda。
- 基础数量为 `V_i` 中不超过 `lambda*d_i` 的最大值。余量按 exact
  `(d_i-current_i)/d_i` DESC、symbol ASC 尝试下一合法数量，每步重算该订单增量真实成本。
- 主板/创业板从 0 起每次 100；科创板从 0 激活为 200，之后每次 1。不得把科创板写成 100 股 lot。
- 实现不得物化与账户规模线性增长的巨大 `V_i`/breakpoint tuple；可用 exact 单调候选/有序迭代，但结果必须与
  数学集合等价，且在合理大目标数量反例中保持有界内存。
- 最终每个 `q_i<=d_i`，post cash exact 非负。未因 lot 被计数的剩余买量才记 `CASH_CONSTRAINT`；同一股不能同时
  记 lot 与 cash residual。
- 新买 quantity 全部进入 `unsettled_quantity`，不增加 sellable；已有持仓 sellable 保持卖后值。新建 position
  临时 mark 可用 execution price，G7E 必须在同 session close 用正式收盘 mark 覆盖。

最终 transition：post positions 只含 quantity>0、严格 symbol 升序；fills 为 SELL 后 BUY、各自 symbol 升序；
rejections canonical 为 side（SELL 在前）、symbol、固定原因优先级。`buy_allocation_lambda=None` 只允许没有可执行
buy allocation；否则为 `[0,1]` exact Fraction。

## 9. Transition 局部完整性与 G7E 边界

返回前至少重算并证明：

- facts identity/date、base/effective cost、multiplier 与调用输入一致；
- pre/post position key 唯一、数量分解成立、零仓已删除；
- intents/fills/rejections 的 symbol、side、quantity rule、open、执行价、notional、fee、slippage 和 reason 可由本次
  输入唯一复算；
- 每个 intent 的 requested quantity 在 fill 与各 residual 间守恒；null quantity rejection 的 notional gap正确；
- `post_cash = pre_cash + sell_notional - sell_fees - buy_notional - buy_fees`，且非负；slippage 已体现在 execution
  notional 中，不重复扣减；
- post positions exact 等于 pre positions 加买 fill、减卖 fill，买入全部 unsettled；
- 合法 canonical target 下，私有 primitive 的 iterable/append 顺序变化不能改变最终 intents/fills/rejections 的
  canonical transition；caller target 的非法物理乱序必须在计算前失败，不能用排序修复后接受。

G7E 的固定调用顺序是：rollover -> G7C pre-open -> apply cash/stock -> account marks/receivables/pre-trade equity ->
F2 -> close mark/NAV/七表 -> G7C record-close。F2 不得读取或更新 entitlement replay，不得调整 previous/close mark，
不得创建 reporting row、Schema、manifest 或 receipt。

## 10. 稳定错误、脱敏与零副作用

复用 exact `AShareExecutionError`，唯一稳定消息：

```text
M3_A_SHARE_EXECUTION_INVALID
```

所有 facts/F1、target/Schema、position、cost、Decimal、Fraction、primitive 和 transition 校验异常必须在离开 active
`except` 后翻译；最终 `__cause__ is None` 且 `__context__ is None`。message、repr、traceback 不得包含 path、symbol、
date、weight、cash、position、raw row、TOKEN、SQL、PID 或嵌套异常文本。

成功与失败均禁止文件读写、mkdir、network、日志、账户数据库、artifact/receipt 或凭据访问；cold import 不加载
Qlib、LightGBM、MLflow。不得添加 debug dump、测试专用生产旁路或全局 mutable state。

## 11. 必测反例

1. exact F0 facts + canonical target/account/cost happy path；development/fake/subclass facts 在 property/frame access 前
   失败；public signature 不存在 `open_states` 参数。
2. spy 证明每次 formal session exact 一次调用 public F1 builder，参数 symbols 为 target∪positive positions 严格升序；
   caller 构造的裸 open-state 即使内容/Schema完全相同也无入口进入 formal execution。
3. targets：错列/dtype/null、空、重复/逆序 symbol、多 as_of/strategy/version、as_of>=date、unknown symbol、负/NaN/
   Inf、总权重>1；均不得排序、填充或 float tolerance 后接受。
4. positions：duplicate/逆序/零仓、sellable+unsettled不守恒、mark非正/非finite、foreign symbol；cash负/NaN、
   equity不大于0或小于cash+market value。
5. 正 target 的 raw quantity 0、主板 1/99、科创板 1/199 都生成 LOT_CONSTRAINT 名义缺口；target=0 清空全部；
   held symbol 缺 target 自动作为0持续退出。
6. 无 open 的正目标和0目标退出：quantity字段均null，rejected_notional exact 为目标与当前 marked value之差；禁止
   使用 close 或写0名义成功。
7. FULL_DAY/开盘停牌/OPEN_UNKNOWN/upper-limit buy/lower-limit sell 固定拒绝；半 tick 语义完全复用 F1，blocked sell
   不向买单提供现金。
8. 主板持仓257、sellable120、请求157必须 fill100/T+1 37/lot20；部分未结算不整单拒绝；公司行动零股尾数只能
   合法一次带走。
9. 两个买单均触发最低佣金，粗略名义比例会透支时，Fraction 结果现金非负；对合法 canonical target，改变私有
   executable iterable 顺序仍得到同一结果；equal remainder 用 symbol ASC。
10. 科创板 0->200 激活、200 后逐1；合理大 desired quantity 不物化巨大合法数量 tuple，结果与小规模穷举 oracle
    等价。
11. lot residual 先于 cash residual且每股只计一次；sell cash可买、blocked sell不可买；全部 fill/fee/cash/position
    守恒。
12. 0.5/1/2 只缩 commission rate/min/slippage；stamp/transfer 不变；BUY/SELL tick方向、limit夹取、最低佣金、
    卖出印花税、双边过户费与逐项 HALF_UP cent。
13. hostile ambient Decimal precision/rounding/traps 下 transition逐字段相同，函数返回后 ambient context 未改变；
    bool/float/NaN/Inf成本与乘数稳定失败。
14. transition intents/fills/rejections/post positions 固定顺序；伪造局部不守恒值对象不能通过其
    `__post_init__`。G7E 不存在接受 caller transition 的旁路。
15. hostile F1/Schema/Polars/Fraction异常只暴露稳定码且 cause/context为空；file/network/log/account/publish零调用；
    fixed-order F0->G7C->F1->F2->development G7E 无类型身份污染。

独立初验必须新增实现者未使用的至少两个反例：其中一个必须是 blocked sell 与最低佣金共同造成的离散买入现金
反例，另一个必须是极小正目标、null quantity notional gap、或大科创板 desired 的 exact oracle/有界内存反例。

## 12. 文件白名单、禁止项与停止条件

实现 Agent 可写：

- `src/quant/backtest/a_share_execution.py`
- `src/quant/backtest/__init__.py`（仅新增 F2 安全导出）
- `tests/unit/test_m3_formal_a_share_session_execution.py`（新增）
- 本任务单状态行
- `docs/agent/M3_G7D_F2_R1正式A股Session订单执行状态转移交付报告.md`（新增）

独立初验只读生产代码与实现测试，只允许新增
`docs/agent/M3_G7D_F2_R1正式A股Session订单执行状态转移独立初验报告.md`。主 Agent 最终验收报告使用唯一对应路径。

禁止修改 `corporate_actions.py`、`a_share_simulator.py`、`costs.py`、F0/F1/G7C、domain Schema/enum、research
contracts/config、development 测试、正式 artifacts/journal。禁止 add/commit、联网、真实数据或账户 I/O。

出现以下任一情况立即停止并回主 Agent 重冻：

- F0、G7C 或 F1 主验状态回退，或 actual F1 exact API/错误合同与本文不同；
- 必须接受 caller 裸 open-state、caller facts hash、裸路径或复制 F1 parser 才能实现；
- 必须修改 G7C/F1/G7E API、Schema/enum/config/cost schedule SSOT，或新增 facts/cost/account capability、signer、
  receipt；
- 无法在不读取 plan root 的情况下区分“纯成本数学”与“cost provenance”；此时不得猜测，留给 G7E 重冻窄
  verified cost view；
- 现有 primitive 的 development 公共行为必须破坏性改变，且不能用共享私有核心 + formal wrapper 保持兼容；
- 需要 entitlement、mark、receivable、close/NAV 或未来行情才能决定订单；
- 发现冻结的板块、费用、T+1、lot、slippage 或 rounding 语义与权威 SSOT/真实规则冲突。

## 13. 验证命令与通过条件

所有命令必须在 `artifacts/dev_worktrees/m3-g4-formal` 内使用工作树自身 `src`。先运行 F2/F1 与现有 execution
邻接，再运行 F0/G7C/development G7E；普通实现和初验不机械运行全量测试。

Windows 原生 Miniforge：

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
D:\Miniforge3\python.exe -m pytest -q `
  tests/unit/test_m3_formal_a_share_session_execution.py `
  tests/unit/test_m3_formal_a_share_open_execution.py `
  tests/unit/test_m3_a_share_execution.py `
  tests/unit/test_m3_a_share_allocation.py
D:\Miniforge3\python.exe -m pytest -q `
  tests/unit/test_m3_formal_a_share_market_facts.py `
  tests/unit/test_m3_formal_corporate_actions.py `
  tests/unit/test_m3_a_share_simulator.py
D:\Miniforge3\python.exe -m ruff check `
  src/quant/backtest/a_share_execution.py `
  src/quant/backtest/__init__.py `
  tests/unit/test_m3_formal_a_share_session_execution.py
D:\Miniforge3\python.exe -m mypy src/quant/backtest/a_share_execution.py
D:\Miniforge3\python.exe -c "import inspect,sys; from quant.backtest.a_share_execution import execute_formal_a_share_session; assert 'open_states' not in inspect.signature(execute_formal_a_share_session).parameters; assert all(name not in sys.modules for name in ('qlib','lightgbm','mlflow'))"
git diff --check -- `
  docs/agent/M3_G7D_F2_R1正式A股Session订单执行状态转移任务单.md `
  src/quant/backtest/a_share_execution.py `
  src/quant/backtest/__init__.py `
  tests/unit/test_m3_formal_a_share_session_execution.py
```

WSL Miniforge base 兼容验证：

```bash
cd /home/mabw/AI_Coding_win/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal
export PYTHONPATH="$PWD/src"
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q \
  tests/unit/test_m3_formal_a_share_session_execution.py \
  tests/unit/test_m3_formal_a_share_open_execution.py \
  tests/unit/test_m3_a_share_execution.py \
  tests/unit/test_m3_a_share_allocation.py
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q \
  tests/unit/test_m3_formal_a_share_market_facts.py \
  tests/unit/test_m3_formal_corporate_actions.py \
  tests/unit/test_m3_a_share_simulator.py
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check \
  src/quant/backtest/a_share_execution.py \
  src/quant/backtest/__init__.py \
  tests/unit/test_m3_formal_a_share_session_execution.py
/home/mabw/miniforge3/bin/conda run -n base python -m mypy \
  src/quant/backtest/a_share_execution.py
/home/mabw/miniforge3/bin/conda run -n base python -c \
  "import inspect,sys; from quant.backtest.a_share_execution import execute_formal_a_share_session; assert 'open_states' not in inspect.signature(execute_formal_a_share_session).parameters; assert all(name not in sys.modules for name in ('qlib','lightgbm','mlflow'))"
```

当前 WSL 路径位于 `/mnt/f`/wslfs/DrvFS；WSL 绿色只算双平台兼容证据，不能声称 Linux/ext4 Gate。

只有“实现与自测 -> 未参与实现者独立初验 -> 主 Agent 对 F0+G7C+F1+F2+development G7E 邻接最终验收”
全部 PASS，才可把本任务标为主验 PASS 并解锁 formal G7E。任务书冻结、单平台绿色、纯成本数学绿色或
development simulator 均不得表述为 G7D/G7/M3 Gate 已完成。

## 14. 已有持仓与极小正目标的交叉语义重冻（2026-08-09）

实现前审计发现 §5.2 的三项原要求不能按字面同时由一条 `TargetOrderIntent` 表达：同一 symbol 至多一条 intent；
极小正 target 映射为 0 时保留 BUY intent；已有正持仓时完整差量又要求 SELL 到规则化目标 0。现冻结为以下唯一
语义，其他章节相应按本节解释：

1. `current_quantity == 0` 且正 target 因最小申报量映射到 0：保留一条 BUY intent，并产生 BUY-side
   `LOT_CONSTRAINT`；`requested_quantity` 可为 0，诊断 rejection 的 requested/rejected quantity 使用
   `raw_target_quantity`（允许 0），`filled_quantity=0`，`rejected_notional=target_notional`。
2. `current_quantity > 0` 且同一正 target 映射到 0：唯一 intent 必须是 SELL，目标 position 为 0，requested
   quantity 为当前持仓。不得再生成第二条 BUY intent，也不得把该情形当“无差量”。
3. 第 2 项除正常 SELL fill/rejection 外，必须额外生成一条 BUY-side `LOT_CONSTRAINT` **目标可达性诊断**：
   `requested_quantity=raw_target_quantity`、`filled_quantity=0`、`rejected_quantity=raw_target_quantity`、
   `rejected_notional=target_notional`。该诊断直接由 target row、pre-trade equity、open 与 formal quantity rule
   复算，不要求存在第二条 BUY intent。
4. SELL intent 的 requested shares 与 BUY-side 目标可达性诊断的 theoretical raw target shares 是两个明确不同的
   守恒域；前者只能归 fill/T+1/sell-lot/market-block，后者只归 target-lot，不违反“同一 requested share 只计
   一个原因”。rejections 仍按 SELL 在前、BUY 在后 canonical 排序。
5. 即使 SELL 被停牌/跌停、T+1 或 sell-lot 部分阻断，第 3 项 target-lot 诊断仍保留，因为它证明的是正 target
   本身不可形成合法持仓，而不是卖单成交结果。报告层不得把两类 rejection 数量相加冒充同一订单 fill 守恒；
   transition `__post_init__` 必须分别复算 SELL 执行域与 target-attainability 域。
6. 该特殊“无对应 BUY intent 的 LOT 诊断”是唯一例外。其他任何 fill/rejection 都必须归属于同 symbol/side 的
   唯一 intent；不得借本节接受 caller 注入的孤儿 rejection。

新增必测：主板/科创板分别覆盖 current=0 与 current>0，raw target 为 0 及正但低于 minimum；已有持仓情形必须
恰一 SELL intent、恰一额外 BUY LOT 诊断，并分别覆盖 SELL 全成、FULL_DAY/跌停全拒与 T+1 部分残差，证明两个
守恒域不混算、固定顺序且 post state 正确。独立初验须新增至少一个“blocked SELL + target-attainability LOT”反例。

## 15. R1 独立失败与 R2 rejection notional 局部闭包（2026-08-09）

R1 独立初验在当前最终 revision 复现同一阻断：从 public builder 取得合法 transition，只将单条普通 rejection 的
`rejected_notional` 增加 `0.01`，`T_PLUS_ONE`、SELL/BUY `LOT_CONSTRAINT`、`CASH_CONSTRAINT`、
`SELL_AT_LOWER_LIMIT` 均仍可由 dataclass `replace` 重构。根因是 `__post_init__` 对普通 non-null rejection 只累计
quantity residual，没有保存并复算本 session 的 trusted reference open；现有 §14 target-attainability LOT 与
null-quantity gap 是仅有的 notional 已闭合分支。

R2 保持交易、费用、Fraction、§14 和 development API 语义不变，冻结以下最小演进：

1. `AShareSessionExecutionTransition` 新增公开只读值字段：

   ```python
   reference_opens: tuple[tuple[str, Decimal], ...]
   ```

   它不是 capability、签名或第二份 open-state；只保存本次 transition 中所有 `requested_quantity is not None` intent
   的 exact F1 reference open。物理顺序严格 symbol 升序、symbol 唯一；每个 inner item 必须 exact 二元 tuple、
   exact str 与 finite positive Decimal。不得保存 close/high/low/limit、FULL_DAY 的伪 0/None open 或 caller 值。
2. public session builder 必须从本次 exact 一次 F1 返回的 open-state frame，在 intent 已构造后生成
   `reference_opens`。其 symbol set 必须 exact 等于 non-null intents 的 symbol set；null intent 不得有 entry，任何
   extra/missing/duplicate/reverse entry fail closed。
3. transition `__post_init__` 在私有 Decimal context 中重验：
   - 每个 fill 的 `reference_open` exact 等于对应 entry；
   - 每个普通 non-null rejection（除 §14 target-attainability LOT 唯一例外）的
     `rejected_notional == reference_open * rejected_quantity`；
   - §14 target-attainability LOT 仍 exact 等于 `target_notional`，不能误改为 open×raw；
   - null-quantity gap 仍用 target notional 与 pre-position mark 复算，且不得查 reference open。
4. 单独漂移任一普通 rejection notional、单独漂移 reference open、增删换序 reference entry、fill reference 与
   entry 不同必须拒绝。同步修改 reference open 与所有相关金额而形成另一套普通自洽值仍只是 plain value 的
   whole-rehash，不在本地 dataclass 来源证明范围；G7E 必须继续自己调用 public F2 并立即消费，禁止接受 caller
   transition。本包不得引入 seal/HMAC/registry 来伪装来源真实性。
5. R2 必须把独立报告中的五类 exact minimal repro 持久化为正式测试，并保留 §14 blocked SELL + target LOT、
   hostile Decimal、极小正 target 与大 STAR oracle。R2 完成后在当前最终 revision 重新运行双平台 `111 + 37`
   邻接，不得沿用 R1 收紧前结果。

R2 文件白名单保持 §12 不变，唯一新增交付报告为
`docs/agent/M3_G7D_F2_R2_referenceOpen与RejectionNotional闭包交付报告.md`；全新独立复验报告固定为
`docs/agent/M3_G7D_F2_R2_referenceOpen与RejectionNotional闭包独立复验报告.md`。只有 R2 全新独立复验 PASS
后才进入主验。

## 16. Special-only reference open 的可证明边界补充（2026-08-09）

R2 首轮测试证明：若一个 non-null intent 只有 §14 target-attainability LOT、没有 fill 或普通 rejection，微小修改
`reference_open` 可能保持 `floor(target_notional/reference_open)` 不变，因而没有其他数值字段可用于 exact 比较。
把测试换成“有 fill 的 symbol”会遗漏这一可达情形，禁止以测试场景替换掩盖合同缺口。

为满足 §15“单独漂移任一 reference entry 必须拒绝”，在 transition 再新增普通自摘要字段：

```python
reference_opens_sha256: str
```

冻结规则：

1. digest payload exact 为 canonical JSON
   `['m3-formal-reference-opens-v1', [[symbol, decimal_plain_text], ...]]`；entry 顺序就是已验证的 symbol 升序，
   Decimal 必须 finite positive并用无指数 canonical plain text，禁止 `str(float)`、repr、路径、平台 identity 或时钟。
2. public builder 从同一次 F1 生成 `reference_opens` 后立即计算 digest；transition `__post_init__` fresh 重算并
   `compare_digest`/exact compare。digest 必须 bare lowercase 64hex。
3. 单改 special-only reference、单改 digest、增删换序 entry 均拒绝；至少覆盖 current=0 raw=0/raw<min、
   current>0 §14 SELL+target LOT、FULL_DAY/null intent 无 reference 三类。
4. 同步修改 reference entries 并重算 digest形成另一套自洽普通值，仍属于任务已承认的 whole-rehash 边界；该
   self-digest 不是签名、capability、首次来源或防篡改锚。G7E 仍必须自己调用 F2，不得接受 caller transition。
5. `reference_opens_sha256` 只补 reference exact 内容绑定；普通 rejection notional 仍必须按 §15 逐项
   `reference_open * rejected_quantity` 复算，不能用 digest 代替经济校验。

本补充不允许 HMAC、随机 key、registry、seal、pickle token 或新文件；白名单和 R2 报告路径保持 §15 不变。

## 17. R2 主验后 null-gap ambient Decimal R3 闭环（2026-08-10）

G7E golden 对照发现：F2 formal null/open-unknown rejection 构造先用私有80位 context计算
`target_notional - current_value`，随后调用 ambient-sensitive `abs(...)`；validator同样先私有subtract再ambient abs。
在caller `prec=50`时，两次舍入位置不同，导致 public F2 自己生成的合法 transition 被自身 `__post_init__`
稳定拒绝；默认prec=28偶然通过。违反§7“所有中间运算使用私有context”和§11 hostile ambient不变量。

R3 只修该局部算术，不改变F2 API、值对象、§14-§16语义或G7E：

1. formal构造与validator中的两处 null-gap absolute 必须使用 exact、ambient-independent 的 Decimal absolute
   primitive（例如私有subtract结果的`copy_abs()`）；禁止用调整caller context或固定G7E precision掩盖。
2. development line中的整数quantity `abs`不在本缺口范围，不做无关修改。全文件其他formal Decimal unary/
   arithmetic必须定向审查，若发现同类ambient逃逸一并以同一私有原语关闭，不扩业务语义。
3. 新增同一合法null-gap case在caller contexts：默认28、prec50、prec4+ROUND_DOWN+Inexact trap下的
   build→transition `__post_init__`，要求逐字段exact相等；caller precision/rounding/Emax/Emin/traps/flags前后不变。
4. 对合法transition低层仅漂移null-gap rejected_notional后仍拒绝；ordinary五类notional、§14 special、reference
   digest/whole-rehash回归保持绿色。
5. 白名单仅 `src/quant/backtest/a_share_execution.py`、
   `tests/unit/test_m3_formal_a_share_session_execution.py`、本任务状态与唯一R3交付报告
   `M3_G7D_F2_R3_nullGapAmbientDecimal返工交付报告.md`。禁止改G7E simulator/tests、F0/F1/G7C、Schema/config。
6. Windows与WSL base重跑最终F2 formal及F0/F1/F2邻接、Ruff/mypy/cold/diff；全新独立复验必须增加
   实现者未用的中等precision/rounding/trap组合，并写唯一
   `M3_G7D_F2_R3_nullGapAmbientDecimal独立复验报告.md`。主验PASS前G7E保持暂停。
