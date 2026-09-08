# M3 G7C R1：正式 A 股公司行动 Entitlement 状态机任务单

日期：2026-08-09  
状态：**R3 tests-only 返工、全新独立复验与主 Agent 最终验收均 PASS；G7D-F1 已解锁**  
性质：formal 纯状态转移合同；不发布 stage/artifact/receipt，不等于完整账户回测、真实全 work、Linux/ext4 或 M3 Gate

## 1. 目标、前置与唯一职责

G7C 把 G7D-F0 已验真的公司行动事实与账户的 record-close 总持仓绑定，形成可逐 SH session 重放的 cash/stock
双 leg entitlement 状态机。它只负责捕获、除权日前确认、到期结算、posting 与 replay 状态；不负责读取 G1、
构造市场事实、调整 FULL_DAY mark、生成目标、撮合、估值或发布产物。

冻结顺序为：

```text
G7P0 -> G7A -> G7B -> G7D-F0 -> G7C -> G7D remaining -> G7E -> G7F
```

实现前置必须同时满足：

1. [`M3_G7D_F0_R1正式A股八表MarketFacts任务单.md`](M3_G7D_F0_R1正式A股八表MarketFacts任务单.md)
   已经经过实现、自测、独立初验和主 Agent 最终验收并明确为 PASS；
2. G7D-F0 公共 exact `VerifiedAShareMarketFacts`、portable identity 与错误合同未再变化；
3. 主 Agent 确认本任务与届时真实 G7D-F0 API 一致。若任一项不满足，停止并重冻，禁止用 mock formal 类型先行实现。

## 2. 唯一事实入口与 formal/development 边界

- 每个 formal 入口只接受 `type(facts) is VerifiedAShareMarketFacts`。其八表、窗口、SH calendar、ledger 与
  `input_market_facts_sha256` 均来自该 capability；不得接收 caller 提供的 ledger、session tuple、terminal、
  release id、manifest hash、裸路径或自报 digest。
- 不另建 corporate-action facts capability、artifact、manifest、sidecar、receipt、signer 或 formal DataFrame
  构造器；G7D-F0 是八表及 release/window/freshness 的唯一 SSOT。
- 现有 `capture_record_close_entitlements(... corporate_actions, sh_sessions, ...)`、
  `recognize_ex_date_entitlements(...)`、`settle_due_entitlements(...)` 与
  `mark_full_day_event_from_factor(...)` 作为 development/raw-frame primitive 保留，并保持现有开发测试可用；
  它们的返回值、raw frame 或调用成功不得 cast、包装、复制字段或重签为 formal 结果。
- formal API 不接受 `VerifiedDevelopmentExampleAShareMarketFacts`、裸 `pl.DataFrame`、target、plan、release、
  account artifact 或 network callback。formal/dev 混配须在读取 facts 任一 DataFrame 前失败。
- G7A/G7B 已在 G7D-F0 读取八表前完成 fresh 验证。G7C 不回调 target/plan verifier，不把 ledger 的未来
  `pay_date/stock_list_date` 或任何 entitlement 信息写回 target、plan、manifest、receipt 或日志；由此保持
  “未来派付/上市事实不暴露给 target 构造”的时序边界。

## 3. Formal replay 值对象与接口

实现应在 `corporate_actions.py` 新增账户状态而非事实 capability。命名可做不改变语义的微调，但以下字段、
exact-type 边界和状态顺序不得弱化：

```python
class EntitlementReplayPhase(str, Enum):
    PRE_OPEN = "PRE_OPEN"
    RECORD_CLOSE = "RECORD_CLOSE"
    COMPLETE = "COMPLETE"

@dataclass(frozen=True)
class AShareEntitlementReplayState:
    input_market_facts_sha256: str
    next_session_index: int
    phase: EntitlementReplayPhase
    positions: tuple[EntitlementPosition, ...]
    processed_record_event_ids: tuple[str, ...]
    record_quantities: tuple[tuple[str, int], ...]

@dataclass(frozen=True)
class AShareEntitlementReplayTransition:
    replay: AShareEntitlementReplayState
    postings: tuple[EntitlementPosting, ...]
    cash_delta: Decimal
    settled_stock: tuple[tuple[str, int], ...]

def initialize_formal_a_share_entitlement_replay(
    *, facts: VerifiedAShareMarketFacts,
) -> AShareEntitlementReplayState: ...

def advance_formal_a_share_entitlements_pre_open(
    *, date: dt.date, replay: AShareEntitlementReplayState,
    facts: VerifiedAShareMarketFacts,
) -> AShareEntitlementReplayTransition: ...

def capture_formal_a_share_entitlements_record_close(
    *, date: dt.date, replay: AShareEntitlementReplayState,
    total_quantities: Mapping[str, int], facts: VerifiedAShareMarketFacts,
) -> AShareEntitlementReplayTransition: ...
```

`input_market_facts_sha256` 必须从 exact facts identity 投影；不得由 caller 传入。`next_session_index + phase`
绑定 G7D-F0 window 的 execution sessions：初始化指向首日 `PRE_OPEN`；盘前成功后同日进入 `RECORD_CLOSE`；
收盘捕获成功后推进下一 session；末日收盘后为 `COMPLETE`。状态不得 pickle；repr 不含 facts、路径、原始行或
构造 seal。不得公开能够跳过 phase、替换 identity 或从裸 positions 签发 formal replay 的构造/恢复 API。
`record_quantities` 按 event_id 严格递增，exact覆盖全部processed event；value为该事件record close已验真的账户总
quantity。窗前事件与首版初始零持仓、record-close零持仓均显式记录0；创建position的事件必须记录正数。该证据
用于双向证明“零持仓无position”与“正持仓position被删”不同，不能仅靠processed IDs猜测。

首版 formal backtest 在首个 execution open 以现金、零证券持仓启动，不接受 caller 注入的窗前持仓。G7D-F0
可能为审计保留 `record_date < first_execution_date`、`ex_date` 在 window 的 ledger 行；初始化必须把这些 event_id
确定性记为“窗前 record 已处理且本账户无 entitlement”，不建立 position/posting。不得等到 ex-date 再假定持仓，
也不得因该类审计行存在而阻断零持仓账户。这样完整 release replay 才能覆盖 G7D-F0 selected ledger，而不会把
窗前未知持仓伪造成权益。

同一个 immutable input state、date、facts、quantity mapping 重算必须给出逐字段相同结果（纯函数幂等）。把
已经推进的 state 再用于旧 date/旧 phase、同一 event 不同经济字段、同一 event 不同 record quantity、换 facts
identity 或乱序 session 属于冲突，必须 fail closed；不得二次 posting 或“取第一次/最后一次”。

## 4. 事件选择、record-close 捕获与 RIGHTS

每个 record-close phase 必须扫描 facts ledger 中 `record_date == date` 的完整事件集，并把每个 event_id 精确
记录为 processed，并同步写入exact `record_quantities`，无论账户 quantity 是正、零还是事件类型为 RIGHTS。
事件处理顺序固定为 `event_id`；禁止
通过 `.sort()` 修复 G7D-F0 本应拒绝的物理乱序 facts。

- record quantity 是当日收盘后的账户**总 quantity**，包含当日买入未结算数量；只允许 exact `Mapping[str,int]`，
  key 为 facts 窗口证券，value 为非负 exact int，bool/float/负数/未知证券均失败。不得用 sellable quantity。
- `DIVIDEND_DISTRIBUTION`：quantity > 0 时按 cash/stock 非零 leg 建立 position；quantity == 0 只记 processed，
  不建立 position/posting。
- `SHARE_CONSIDERATION`：按 ledger 的 `stock_ratio` 建立 stock-only position；必须遵守 record-close 数量、
  `stock_list_date == ex_date`、整数红股与同日 recognize-then-settle，不能误当 RIGHTS 或普通拆股 silently skip。
- `RIGHTS`：首版账户不模拟认购和资金缴纳。它由 market facts/bar/reconciliation 保留以解释市场价格；
  record close quantity>0 时属于“影响持仓的未支持权益事件”，整场景必须 fail closed。quantity==0 时才允许
  确定性标记 processed 后跳过；不得创建 cash/stock 均 `NOT_APPLICABLE` 的空 `EntitlementPosition`，不得生成
  CAPTURE/RECOGNIZE/SETTLE posting，也不得转成免费红股。权威 `CorporateActionLedgerSchema` 要求 RIGHTS
  保留非空 `stock_list_date`；G7C将其视为市场事实/价格解释元数据，不解释为免费股票的due或settlement，
  不得因此创建position。
- 对实际创建的 position，至少一个 leg 非零。`ABSENT` 只允许 CAPTURE posting 的 before 语义，不进入 position；
  零 leg 恒为 `NOT_APPLICABLE`，非零 leg 从 `CAPTURED` 开始。
- CAPTURE posting 每个实际创建的event/position exact一条；mixed dividend仍只有一条，该posting同时表达cash与
  stock两leg的before/after状态。posting记录record-close date；cash_amount、stock_quantity与rounding delta在
  CAPTURE均为零，不提前入现金或持仓。一个非零leg时另一个leg保持NOT_APPLICABLE；两个非零leg同时从
  CAPTURED起步。RIGHTS零持仓不生成posting，RIGHTS正持仓在此之前即失败。

每个 ledger event 必须满足 `record_date < ex_date` 且两者是 facts 中权威 SH open session；即使上游通用 Schema
允许同日，本层仍失败。对 `DIVIDEND_DISTRIBUTION/SHARE_CONSIDERATION`，cash > 0 才允许且要求pay，stock > 0
才允许且要求list，零entitlement leg对应due必须为空。该零leg/due规则不适用于不建position的RIGHTS
`stock_list_date`。
due 是供应商事实日，settlement session 是 facts SH calendar 中首个 `>= due` 且 `<= terminal` 的 session；超过
terminal/history 时为 `None`。

## 5. 盘前 recognize、settle 与漏日失败语义

每个 session 的 `PRE_OPEN` 必须先对当日 `ex_date` 的所有 CAPTURED leg 做 recognize，再对当日 exact settlement
session 的所有 RECOGNIZED leg 做 settle。两组内部都按 `event_id`、cash-before-stock；整体 posting 顺序为
所有 recognize 在前、所有 settle 在后。因此 `SHARE_CONSIDERATION` 或 dividend 的 ex/list 同日严格
recognize-then-settle，上市红股在该日开盘执行前进入 quantity 且 sellable。

- 调用日已晚于某个仍为 CAPTURED 的非零 leg 的 `ex_date`：说明漏过确认日，失败；不得在迟到日补确认。
- 调用日已晚于某个 RECOGNIZED leg 的非空 settlement session：说明漏过结算日，失败；不得在迟到日入账。
- 到期日仍为 CAPTURED、SETTLED 日期早于 due、状态跳级/倒退或 phase/date 不一致均失败。
- due 超过 terminal 时 settlement session 为 `None`；该 leg 在 ex-date 仍正常 RECOGNIZED，并作为 cash/stock
  receivable 保留到终值，`COMPLETE` 不强制结算，也不伪造 terminal settlement。
- terminal 内非空 due 必须在 exact due session 结算；不得用 `due <= current_date` 的迟到逻辑。
- 已成功推进后的新 state 不重复 posting；拿旧 immutable state 重算得到相同结果，拿新 state 重放旧操作报冲突。

## 6. 算术、日期、状态与防伪闭包

每个 formal 入口在产生任何输出前，必须用 facts ledger/calendar 与 replay phase 对全部 position 做双向复算；
仅依赖 dataclass `__post_init__` 或 caller 已经构造成功不够。至少拒绝以下 forgery：

1. 非 exact dataclass/enum/date/int/Decimal，bool 冒充 int，NaN/Infinity/负数，event_id/symbol 格式错误；
2. event_id 不在 exact ledger、symbol/action/date/due/ratio 与 ledger 不同、重复 position、RIGHTS position、
   processed IDs或record quantities少/多/重复/乱序、二者event集合不同、quantity与已处理输入冲突，或与当前
   phase可达事件集合不闭合；正quantity事件缺position、零quantity事件多position均失败；
3. `record_quantity <= 0`、`cash_per_share_gross/stock_ratio` 与 `Decimal(str(ledger value))` 不同、
   `cash_entitlement_gross != record_quantity * cash_per_share_gross`；
4. `record_quantity * stock_ratio` 不是 exact integer，或 `stock_entitlement` 与 exact product 不同；
5. settlement session 不是权威 SH calendar 的首个合法 session、日期在 terminal 外却伪造 session、应有 session
   却置空；
6. leg 的 `NOT_APPLICABLE/CAPTURED/RECOGNIZED/SETTLED` 与经济分量、当前 replay date/phase、ex/due 不一致，
   或同一 event 的 cash/stock 状态组合在冻结顺序下不可达；
7. transition/posting 的 before/after、posting type、date、金额、股数、rounding delta、聚合 cash/stock delta
   不能由输入 replay 唯一复算。

所有金额/比率从 G1 Float64 只允许 `Decimal(str(value))`；不得 `Decimal(float)` 或 float tolerance。formal
乘法与 quantize 必须使用模块私有、显式 precision/rounding/trap 的 Decimal context（至少 50 位，并拒绝发生
unrounded product 的 Inexact/Rounded），不得依赖或修改进程 ambient context；同一输入在 hostile ambient
precision/rounding 下结果必须相同。现金 entitlement 在 capture/recognize 阶段保持税前 CNY gross Decimal；只在
`CASH_SETTLE` **一次**按 `Decimal("0.01")`、`ROUND_HALF_UP` 到分，posting 的
`cash_rounding_delta = settled_amount - gross`，且 transition `cash_delta` 精确等于当日 settlement posting 之和。
首版不扣个人红利税。stock entitlement 必须 exact integer，只在 `STOCK_SETTLE` 一次进入持仓；禁止四舍五入、
截断或残股缓存。

## 7. Release 级 replay 与完整性

定向测试除单事件外，必须用一个 exact `VerifiedAShareMarketFacts` 从初始化按完整 window 逐 session 执行
`PRE_OPEN -> RECORD_CLOSE`，覆盖 ledger 中全部 selected event_id。终态必须证明：

- 每个 record_date 在 window 的 ledger event 恰好于 record close processed；窗前 record/event 在初始化恰好标记
  一次且无 position/posting；RIGHTS 零持仓有 processed 证据但无 position，RIGHTS 正持仓终止场景；
- 每个创建 position 可由同 release ledger 行和 record-close quantity 唯一复算；
- terminal 内到期 leg 全部 SETTLED，terminal 外到期 leg 恰为 RECOGNIZED receivable；无 CAPTURED leg 的 ex_date
  已经过 terminal；
- posting `(date, event_id, posting_type)` 唯一；mixed capture以单posting表达双leg，且transition delta与posting
  汇总一致；
- 同 facts identity 重放逐字段一致，换 release/plan/window 或合法重签但经济行改变时不能复用旧 replay。

release 级 replay 不读取磁盘、不重新验证 G1/G7B、不发布结果；它消费 G7D-F0 已固定的内存 frames。FULL_DAY
mark 与 reconciliation event-set 闭包仍属于 G7D-F0/G7E；G7C 只保留 strict
`mark_full_day_event_from_factor` development primitive，不新增 entitlement 反推 mark 路径。

## 8. 稳定、脱敏错误与零副作用

formal 公共错误唯一稳定消息为 `M3_A_SHARE_ENTITLEMENT_INVALID`（可新增同名公开异常类型）；所有 exact-type、
identity、phase、arithmetic、ledger、Polars 与 hostile mapping 异常都必须在离开 active `except` 后翻译，最终
`__cause__ is None` 且 `__context__ is None`。message/repr/traceback 不得包含路径、raw row、symbol/event_id、
quantity、日期、TOKEN、SQL、PID 或嵌套异常文本。development primitive 既有 `ValueError` 合同无需冒充 formal
稳定错误。

禁止网络、文件读写、mkdir、日志、artifact/receipt、pickle、data/legacy、账户数据库、凭据、target/label；
禁止 import Qlib、LightGBM、MLflow。hostile facts property、DataFrame、Mapping 的递归异常图也必须脱敏。

## 9. 必测反例

1. exact formal facts happy path；development facts、裸 frame、subclass、fake same-fields 在 frame access 前失败。
2. RIGHTS+正持仓立即稳定失败；RIGHTS+零持仓 processed 且零 position/zero posting；禁止双 NOT_APPLICABLE 空 position。
3. DIVIDEND cash-only、stock-only、mixed；SHARE_CONSIDERATION 同日 stock recognize/settle；多个 event 固定排序。
4. record close 使用 total quantity（含 unsettled），后续卖出仍得权益，ex-date 买入无权益，零 quantity 不 capture。
5. 漏过 ex 后 CAPTURED、漏过 cash/stock settlement 后 RECOGNIZED 均失败；exact 同日 recognize 后 settle 通过。
6. 周末 due 映射首个 SH session；terminal 外 cash/list 保留 receivable；terminal 内 due 置空或迟到结算失败。
7. HALF_UP 边界（含 `1.005 -> 1.01`）、只舍入一次、rounding delta、hostile ambient Decimal context；fractional
   stock、截断和 float Decimal 失败。
8. forged EntitlementPosition：amount/product/due/state/date/symbol/event/action 任一漂移；伪 posting/transition 汇总失败。
9. processed IDs/record quantities任一少、多、重复、换序或集合不一致；正quantity删position、零quantity加position；
   同event冲突quantity；旧state重放、新state重复、phase/session乱序。
10. 完整 release replay 包含多个证券、多个事件、RIGHTS、SHARE_CONSIDERATION、terminal 外 due；换 facts identity
    与 whole-frame 合法重签后旧 replay 均失败。
11. 未来 pay/list 不进入 target/plan verifier/callback；network/file/log/publish 均零调用；cold import 无重研究依赖。
12. hostile facts/Polars/Mapping 异常无 cause/context 且只暴露稳定错误码。

独立初验必须新增实现者未使用的至少两个反例，其中至少一个是完整 release replay 的中途旧 state/换 facts
冲突，另一个是伪造 position 的可达状态或日期算术反例；不能只复述测试数量。

## 10. 文件白名单、禁止项与停止条件

实现 Agent 可写：

- `src/quant/backtest/corporate_actions.py`
- `src/quant/backtest/__init__.py`（仅必要安全导出）
- `tests/unit/test_m3_formal_corporate_actions.py`（新增）
- 本任务单的状态行
- `docs/framework/agent/M3_G7C_R1正式A股公司行动Entitlement状态机交付报告.md`（新增）

独立初验只读生产代码/实现测试，只允许新增自己的
`docs/framework/agent/M3_G7C_R1正式A股公司行动Entitlement状态机独立初验报告.md`。主 Agent 最终验收报告另行写入唯一
对应路径。禁止修改 G1/G7A/G7B/G7D-F0、G7D/G7E/G7F、domain Schema/enum、development tests/config、正式
artifact/journal；若确需新增 domain enum、改变 G7D-F0 API、改现有 development primitive 行为或触碰其他文件，
立即停止并由主 Agent 重冻白名单。

不得联网、add/commit、触碰正式 G1 数据或运行真实 I/O。不得将 development 测试通过表述为 formal 或 Gate。

停止并升级条件：

- G7D-F0 主验未 PASS 或 exact API 与本文不同；
- facts 未提供完整 SH session、terminal、ledger identity 或 `input_market_facts_sha256`；
- SHARE_CONSIDERATION/RIGHTS 的真实 ledger 语义与当前 Schema 冲突；
- 需要读取 raw/reconciliation、排序修复、forward-fill、理论除权价、税务猜测或账户持仓之外的未来信息；
- 需要新的 facts capability/artifact/receipt、generic signer、磁盘恢复或公开伪造入口。

## 11. 验证命令与通过条件

先跑新增 formal 测试与现有 development 邻接测试，再跑 G7D-F0/G7E 邻接测试（以届时实际文件名为准）。所有
命令必须用 worktree 自身 `src`，防止误导入根工作区。

Windows 原生反馈环：

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_formal_corporate_actions.py tests/unit/test_m3_corporate_actions.py -q
D:\Miniforge3\python.exe -m ruff check src/quant/backtest/corporate_actions.py src/quant/backtest/__init__.py tests/unit/test_m3_formal_corporate_actions.py
D:\Miniforge3\python.exe -m mypy src/quant/backtest/corporate_actions.py
git diff --check -- docs/framework/agent/M3_G7C_R1正式A股公司行动Entitlement状态机任务单.md src/quant/backtest/corporate_actions.py src/quant/backtest/__init__.py tests/unit/test_m3_formal_corporate_actions.py
```

WSL Miniforge base 兼容验证：

```bash
cd /home/mabw/AI_Coding_win/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal
PYTHONPATH="$PWD/src" /home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_m3_formal_corporate_actions.py tests/unit/test_m3_corporate_actions.py -q
PYTHONPATH="$PWD/src" /home/mabw/miniforge3/bin/conda run -n base python -m ruff check \
  src/quant/backtest/corporate_actions.py src/quant/backtest/__init__.py tests/unit/test_m3_formal_corporate_actions.py
PYTHONPATH="$PWD/src" /home/mabw/miniforge3/bin/conda run -n base python -m mypy \
  src/quant/backtest/corporate_actions.py
```

当前 WSL 路径位于 `/mnt/f`/wslfs/DrvFS；WSL 绿色只算双平台兼容证据，不能声称 Linux/ext4 Gate。只有实现
自测、未参与实现者独立初验、主 Agent 对 G7D-F0+G7C+邻接 G7E 的最终验收全部 PASS 后，才能把状态更新为
主验 PASS 并解锁 G7D remaining。任务书冻结、单平台绿色或 development replay 均不等于 formal Gate 关闭。

## 12. R1 失败与 R2 冻结闭环（2026-08-09）

R1 独立初验发现三项阻断：

1. 对真实 CAPTURE 或同日mixed recognize+settle transition执行
   `replace(postings=(), cash_delta=0, settled_stock=())` 后仍被普通dataclass接受，transition未证明完整输出。
2. 模块级 `_expected_positions + _register_formal_replay` 可从裸quantity构造并登记index=1/PRE_OPEN state，跳过
   RECORD_CLOSE/CAPTURE后仍被public advance接受。
3. 跨日event_id逆序（早日`b...`、晚日`a...`）时，按日期append的record quantities与“全局event_id排序”
   不变量冲突，合法第二次capture失败。

R2保持RIGHTS、日期、Decimal和经济语义不变，冻结以下最小来源闭包：

- `AShareEntitlementReplayState` 与 `AShareEntitlementReplayTransition` 改为由一次性模块初始化closure产生的
  exact runtime类型；public constructor拒绝，普通dataclass `replace`、`object.__new__`、slots/字段clone不能形成
  可消费formal对象。类型字段/属性名称与任务§3保持不变。
- closure内分别维护issued-instance registry与内容attestation。state证明绑定facts identity、phase/index、positions、
  processed IDs、record quantities；transition证明绑定输入state证明、operation/date、facts identity、输入quantity
  mapping、输出state、完整ordered postings、cash delta与settled stock。每个property/repr返回前重验。
- public initialize/advance/capture是唯一签发路径；所有可从module或public callable graph取得的函数都不能接受裸
  state payload/positions/quantities后直接登记。`_expected_positions`等纯计算helper可以保留，但只能返回普通值，
  不得接触registry/attestation。模块不得暴露register/sign/mint/key/factory surface。
- advance/capture完成完整经济重算后才在同一调用栈局部登记state与transition。transition删/多/换序posting、
  delta/settled stock漂移、跨operation复用、输入state/facts/date/quantity变化均在任一消费前失败。
- `record_quantities` 与 `processed_record_event_ids` 是截至当前phase全部已处理event的全局canonical event_id顺序。
  每日新事件先验证当天物理/处理顺序，再与既有集合合并并按event_id规范排序；不得把全局canonical顺序误当
  跨日处理时间。position与可达性仍从ledger record/ex/due日期和quantity双向复算。
- reload旧state/transition反例使用fresh subprocess，不能污染后续development/G7D-F0/G7E类型身份。

R2新增测试至少覆盖：真实transition删全部/单个posting及全字段重签；module raw register旁路不存在；constructor/
new/clone/字段漂移；早日高event_id+晚日低event_id合法完整replay；同日posting仍按event_id且recognize全部先于settle；
旧state换facts/date/quantity；fixed-order reload后development与邻接回归。完成双平台复验后换全新独立上下文。

## 13. R2 独立失败与 R3 测试证据闭环（2026-08-09）

R2 独立复验未发现新的运行时功能缺陷：Windows 与 WSL base 组合回归各 74 项通过，静态检查和 cold import
均通过，窗前零持仓加窗内跨日逆序 event_id 的独立业务样例也通过。失败仅因为 §12 明文要求的若干持久化
对抗测试没有落入正式测试文件，不能用实现静态上“看起来会拒绝”代替可复现证据。

R3 是严格的 tests-only 返工：

- 生产文件 `src/quant/backtest/corporate_actions.py` 和包导出不得修改；实现 Agent 必须记录 R3 前后生产文件
  SHA256 或等价 diff 零变化证据。
- 只在 `tests/unit/test_m3_formal_corporate_actions.py` 增补最小、确定的持久化回归，至少逐项覆盖：
  1. mixed transition 仅删除一个合法 posting；
  2. 增加额外 posting，以及改变合法 posting 顺序；
  3. 单独漂移 `cash_delta` 与 `settled_stock`；
  4. 把合法 transition 跨 operation 复用；
  5. 旧 state/transition 改用另一份 exact facts identity 或另一份 quantity 输入；
  6. 上述变体均须在 property/repr 或后续 public 消费边界 fail closed，同时原始合法对象仍可正常消费。
- 不新增 parallel capability、signer、测试专用生产旁路或宽松 helper；不得为了测试可写性放宽 runtime exact type。
- 回归仍须覆盖 formal、development、G7D-F0/G7E/M4 ledger 邻接，双平台 Ruff/mypy/cold import 与 scoped
  diff-check。R3 交付报告固定为
  `docs/framework/agent/M3_G7C_R3_正式Transition完整性回归证据交付报告.md`。

R3 完成后必须由未参与 R3 的全新独立上下文复验；独立报告固定为
`docs/framework/agent/M3_G7C_R3_正式Transition完整性回归证据独立复验报告.md`。只有该复验明确 PASS，才进入主 Agent
最终验收；不得因 R2 运行时实现已基本闭合而跳过这一轮职责分离。
