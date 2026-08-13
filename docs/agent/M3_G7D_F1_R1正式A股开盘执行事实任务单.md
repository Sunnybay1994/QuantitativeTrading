# M3 G7D-F1 R1：正式 A 股开盘执行事实任务单

日期：2026-08-09  
状态：**R2 实现、全新独立复验与主 Agent 最终验收 PASS；允许恢复 G7E**  
性质：formal 只读执行事实投影合同；不运行账户、不撮合、不计算费用、不发布 artifact/receipt，不等于完整 G7D、真实全 work、Linux/ext4 或 M3 Gate

## 1. 目标、前置与唯一职责

G7D-F1 是 G7D-F0 formal 八表 MarketFacts 与后续订单执行之间唯一的开盘事实投影。它只把 exact
`VerifiedAShareMarketFacts` 中的证券、未复权 open、盘前停牌和涨跌停事实投影为当日
`OpenExecutionStateSchema`，并用同一证券事实解析 A 股板块申报数量规则。

冻结顺序为：

```text
G7P0 -> G7A -> G7B -> G7D-F0 -> G7C -> G7D-F1 -> G7D-F2 -> G7E -> G7F
```

开始实现前必须同时满足：

1. [`M3_G7D_F0_R1正式A股八表MarketFacts任务单.md`](M3_G7D_F0_R1正式A股八表MarketFacts任务单.md)
   保持 R3 主 Agent 最终验收 PASS；
2. [`M3_G7C_R1正式A股公司行动Entitlement状态机任务单.md`](M3_G7C_R1正式A股公司行动Entitlement状态机任务单.md)
   已完成 R3 实现、全新独立复验和主 Agent 最终验收并明确 PASS；
3. G7D-F0 的 exact formal 类型、identity、八表属性与稳定错误合同未再变化。

任一前置不满足时，本文件只作为设计，不得修改生产代码或测试。G7D-F1 与 G7D-F2 都写
`a_share_execution.py`，必须串行；F1 主验 PASS 后才可冻结并实现 F2。

本包不负责：公司行动 capture/recognize/settle、FULL_DAY 公司行动 mark、盘前权益、目标差量、T+1、撮合、
费用、滑点、现金分配、持仓变更、NAV、七张结果表或发布。

## 2. 权威事实与 SSOT

- 高层账户和执行语义：[`docs/M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.11。
- G7D/G7E 机械合同：[`M3_G7目标到账户回测分包骨架与外部闭环任务单.md`](M3_G7目标到账户回测分包骨架与外部闭环任务单.md)
  §7–§8。
- formal 八表、窗口、潜在持仓域和 FULL_DAY 闭包：G7D-F0 任务单 §2–§7。
- 公司行动与账户状态边界：G7C 任务单 §3–§7。
- `AShareBoard`、`ExecutionRejectReason`、`OrderSide`：`src/quant/domain/enums.py`。
- `OpenExecutionStateSchema`：`src/quant/domain/schemas.py`。
- `AShareOrderQuantityRule` 和既有 development 执行原语：`src/quant/backtest/a_share_execution.py`。

不得复制枚举字符串、另建 open-state Schema、从 `board_lot`/name 猜板块，或在本任务中修改费率、规则有效期、
公司行动或账户语义。

## 3. 冻结 public API 与 formal/development 隔离

在 `src/quant/backtest/a_share_execution.py` 新增并安全导出：

```python
class AShareExecutionError(ValueError): ...

def build_formal_a_share_open_execution_states(
    *,
    facts: VerifiedAShareMarketFacts,
    date: dt.date,
    symbols: tuple[str, ...],
) -> pl.DataFrame: ...

def resolve_formal_a_share_order_quantity_rule(
    *,
    facts: VerifiedAShareMarketFacts,
    date: dt.date,
    symbol: str,
) -> AShareOrderQuantityRule: ...
```

formal 入口只接受 `type(facts) is VerifiedAShareMarketFacts`、exact `dt.date`、exact tuple/str。现有
`build_open_execution_states(*, facts: VerifiedDevelopmentExampleAShareMarketFacts, ...)`、
`resolve_a_share_order_quantity_rule(*, symbol, date)` 及 development 测试原样保留；不得 cast、复制字段、包装或
重签 development 结果为 formal。

F1 返回的 DataFrame 是可审计的只读投影值，不是新的 facts capability，也不携带 signer、seal、token、root、
receipt 或恢复 API。caller 可以复制或修改该返回值，因此后续 F2 **不得接收 caller 提供的裸 open-state
DataFrame 作为 formal 信任边界**；F2 必须重新接受 exact facts/date，并在同一次调用栈内调用相同的私有投影核心。

## 4. Fresh 链、消费顺序与零 I/O

每个 formal 入口的顺序固定为：

1. 在访问 facts 任一 property 前完成所有轻量 exact-type 检查；formal/dev/fake/subclass 混配必须零 frame access
   失败。
2. 读取 `facts.identity`，触发 G7D-F0 已有 issued-instance、内容和来源重验。
3. 只读取本函数必需的 facts property；每次 property access 继续使用 G7D-F0 既有 verifier 和 clone 语义。
4. 验证 date/symbol/instrument/request domain 后，投影开盘状态或数量规则。
5. 在返回前用权威 Schema 和跨字段规则重验结果。

F1 不得回调 `verify_g1_release`、G7A/G7B verifier 或 formal loader，不得读取磁盘、裸路径、plan root、配置、
`data/legacy`、账户或凭据；不得联网、mkdir、写日志、artifact、sidecar 或 receipt。不得检查、枚举或复制
`VerifiedAShareMarketFacts` 的私有 slots、attestation、provenance 或 closure。

## 5. 日期、证券、instrument 与生命周期域

- `date` 必须 exact 出现在 facts `benchmark_bars` 的 `H00300.CSI` trade-date 域。G7D-F0 已证明该域 exact 等于
  `plan.window.execution_dates`；F1 不接受 caller 自报 sessions/window，也不从自然日、calendar 补日期。
- `symbols` 必须是 exact tuple，元素为 exact str、严格字典序、唯一。允许空 tuple，并返回具有精确列/dtype 的空
  `OpenExecutionStateSchema`；不得用 `.sort()` 或去重修复 caller 请求。
- 每个 symbol 必须在 facts `instruments` 中 exact 一行，且为 `instrument_type=STOCK`、`currency=CNY`、
  `market=SH|SZ`，suffix 与 market 一致。
- 请求日必须处于该证券 inclusive `[list_date, delist_date]` 生命周期；`delist_date=None` 表示开放末段。
- 每个请求 `(symbol,date)` 必须属于 G7D-F0 已验真的潜在持仓域：存在 exact bar，或存在 exact FULL_DAY
  suspension，二者 XOR。请求 facts 域外证券/日期立即稳定失败，不投影为伪造的 0 股、0 价或普通缺行情成功。
- 板块只按冻结 prefix/suffix 解析：`600/601/603/605*.SH`、`688/689*.SH`、
  `000/001/002/003*.SZ`、`300/301*.SZ`。未知 prefix、suffix 错配、非股票、非 CNY、上市前/退市后均失败。
  科创板规则不得用于 2019-07-22 前；所有规则还必须晚于等于证券自身 `list_date`。

G7D-F0 已在 capability 签发时证明完整 instrument/D 生命周期闭包；F1 仍须对本次请求做窄重验，但不得复制整个
八表 verifier 或允许构造一个绕过 F0 的平行 facts 入口。

## 6. Open-only 投影与停牌/涨跌停语义

`build_formal_a_share_open_execution_states` 只允许读取：

- instrument 的身份、市场、币种和生命周期字段；
- benchmark 的 benchmark/trade-date 键，仅用于 execution-date 域；
- bar 的 `symbol,trade_date,source,open`；
- suspension 的 `symbol,trade_date,source,suspension_scope,suspension_detail`；
- price limit 的 `symbol,trade_date,source,has_price_limit,up_limit,down_limit`。

禁止读取或基于 `close/high/low/volume/amount`、未来公司行动 pay/list、reconciliation、target、label 或账户状态作
决定。改变同一合法 open 事实之外的 close/high/low/volume 不得改变投影结果。

逐 key 规则固定为：

1. `FULL_DAY`：必须无 bar；有 bar 冲突失败。输出 `open=null,has_open=false,full_day_suspended=true`，
   `partial_open_status=NOT_APPLICABLE`，双边不允许，`reason=SUSPENDED`。limit 可缺或恰一行，但不能因此开放交易。
2. 非 FULL_DAY：必须 exact 一条 bar、exact 一条 limit，且 `has_price_limit=true`、上下限均为 finite 正值；缺、
   重复、单侧空或 false 均失败。formal capability 的合法 D key 不产生 `MISSING_OPEN`；该 enum 值继续只为既有
   development/防御接口保留。
3. 无 suspension：`partial_open_status=NOT_APPLICABLE`。有 suspension 时只能为 `PARTIAL`，bar 不能覆盖它。
4. PARTIAL detail 只按精确分隔符 `" | "` 分段；每段必须为 `HH:MM-HH:MM` 24 小时格式并解释为半开区间。
   09:30 落入任一区间时 `SUSPENDED_AT_OPEN`、双边不允许、`reason=SUSPENDED`；全部可解析且 09:30 不落入时
   `PROVEN_OPEN_TRADABLE`；任一未知/不可解析文本为 `OPEN_UNKNOWN`、双边不允许、`reason=OPEN_UNKNOWN`。
5. 交易价位固定为 CNY `Decimal("0.01")`。open 与 upper limit 的距离小于等于半 tick 时 buy 不允许；open 与
   lower limit 的距离小于等于半 tick 时 sell 不允许。比较只用 `Decimal(str(value))`，含等号，不用 float epsilon。
   limit 方向阻断由 `buy_allowed/sell_allowed` 表达，不用全天 high/low/close 推断。

输出列、顺序和 dtype 精确复用 `OpenExecutionStateSchema`：

```text
date,symbol,open,has_open,full_day_suspended,partial_open_status,
has_price_limit,up_limit,down_limit,buy_allowed,sell_allowed,reason
```

非空输出物理顺序必须严格 `(date,symbol)`；唯一键为 `(date,symbol)`。不得先接受乱序 facts 再 `.sort()` 修复；
F0 应拒绝的源事实不能由 F1 调和。

## 7. 数量规则解析边界

`resolve_formal_a_share_order_quantity_rule` 使用同一 exact facts/date/symbol 域检查后，复用唯一
`AShareOrderQuantityRule`：

- 沪深主板、创业板：买入最少 100 且按 100 递增；卖出一般按 100，零股只允许按盘前总持仓 remainder 一次带走；
- 科创板：买入最少 200，激活后按 1 股递增；卖出一般最少 200，盘前总持仓 `<200` 时只允许全余额卖尽；
- `rule_version` exact 为 `sse_szse_limit_order_quantity_v1`。

F1 只解析规则，不接收持仓、不计算合法买卖数量、不生成 intent/rejection/fill。`largest_valid_*`、T+1 residual 和
现金门禁属于串行后续 F2。

## 8. 稳定错误、脱敏与副作用

两个 formal public 入口的唯一稳定错误消息为：

```text
M3_A_SHARE_EXECUTION_INVALID
```

所有 exact-type、facts property、Polars、Schema、日期、证券、生命周期、PARTIAL parser 与算术异常都必须在离开
active `except` 后翻译为 exact `AShareExecutionError`；最终 `__cause__ is None` 且 `__context__ is None`。
message、repr 和 traceback 不得包含 path、symbol、日期、raw row、detail、TOKEN、SQL、PID 或嵌套异常文本。

任何失败必须零文件、零网络、零日志、零账户、零 artifact 副作用。package cold import 不加载 Qlib、LightGBM、
MLflow；F1 不新增可序列化 capability、全局 mutable registry、signer、mint、restore 或 generic factory。

## 9. 必测反例

1. exact formal facts happy path；development facts、裸 frame、fake same-fields、subclass 在任一 facts property access
   前稳定失败。
2. 空 symbols 返回 exact empty Schema；bool/date-like、list 代 tuple、重复、逆序、未知 symbol、非 execution date、
   weekend 均失败，且不通过排序/去重/自然日修复。
3. instrument 非 STOCK/CNY/SH|SZ、suffix 错配、未知 prefix、上市前、退市后由 F0 邻接或 F1 请求域 fail closed；
   不从 name/board_lot 猜规则。
4. FULL_DAY 无 bar/可缺 limit 双拒；bar+FULL_DAY 冲突不能被 bar 覆盖；请求域缺 bar 且非 FULL_DAY 不得返回
   `MISSING_OPEN` 继续执行。
5. PARTIAL exact `" | "`、09:30 起点命中、09:30 终点不命中、跨 09:30、多段、错误 delimiter、非法时分、
   空/未知文本；未知必须保守双拒。
6. upper/lower limit 的半 tick 内、精确半 tick、刚超过半 tick；buy/sell 方向分别验证，禁止 float tolerance。
7. open 相同而 close/high/low/volume 不同的两份合法 fresh facts 投影逐字段相同；测试还须证明 F1 不访问
   corporate-actions/reconciliation/target/label/account callback。
8. formal 输出精确 12 列、dtype、唯一键、物理顺序；输入 frame clone 或返回 frame 后 caller 修改不影响原 facts，
   且该返回值不能被任何 formal downstream 入口直接信任。
9. hostile facts property/Polars/Schema/parser 异常递归图只暴露稳定码，cause/context 为空；pickle/写文件/mkdir/
   network/log 均零调用。
10. fixed-order 邻接：F0 facts、G7C formal、F1、development facts/execution、development G7E 顺序运行不发生
    reload/type identity 污染。

独立初验必须新增实现者未使用的至少两个反例，其中至少一个是 open-only 未来字段/禁止 property 访问，另一个是
PARTIAL 边界或 symbol/date/instrument 请求域反例；不能只复述测试数量。

## 10. 文件白名单、禁止项与停止条件

未来实现 Agent 可写：

- `src/quant/backtest/a_share_execution.py`
- `src/quant/backtest/__init__.py`（仅新增 F1 安全导出）
- `tests/unit/test_m3_formal_a_share_open_execution.py`（新增）
- 本任务单状态行
- `docs/agent/M3_G7D_F1_R1正式A股开盘执行事实交付报告.md`（新增）

独立初验只读生产代码与实现测试，只允许新增
`docs/agent/M3_G7D_F1_R1正式A股开盘执行事实独立初验报告.md`。主 Agent 最终验收使用唯一对应报告。

禁止修改：`corporate_actions.py`、`a_share_simulator.py`、`costs.py`、G1/G7A/G7B/G7D-F0、domain
Schema/enum、research contracts/config、development 测试、正式 artifact/journal。禁止 add/commit、联网或真实数据 I/O。

出现以下任一情况立即停止并回主 Agent 重冻：

- G7C R3 独立复验或主验未 PASS；
- exact F0 capability/API 与本文不同，或不能从 benchmark exact 推导 execution-date 域；
- 必须公开裸 DataFrame signer、第二 facts capability、seal/token、restore 或 generic factory；
- 必须读取 plan/cost 裸路径、回调 fresh verifier、改 F0/G7C API 或访问账户/entitlement/mark/NAV 才能实现；
- 必须修改 Schema/enum/config/规则有效期或用排序、forward-fill、0 价、close/high/low/volume 补事实；
- 真实板块或停牌口径与冻结 SSOT 冲突。

## 11. 验证命令与通过条件

所有命令必须在 `artifacts/dev_worktrees/m3-g4-formal` 内使用工作树自身 `src`。先运行 F1 与 F0 定向测试，再运行
G7C/development 邻接；普通实现和初验不机械运行全量测试。

Windows 原生 Miniforge：

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
D:\Miniforge3\python.exe -m pytest -q `
  tests/unit/test_m3_formal_a_share_open_execution.py `
  tests/unit/test_m3_formal_a_share_market_facts.py `
  tests/unit/test_m3_a_share_market_facts.py `
  tests/unit/test_m3_a_share_execution.py
D:\Miniforge3\python.exe -m pytest -q `
  tests/unit/test_m3_formal_corporate_actions.py `
  tests/unit/test_m3_a_share_simulator.py
D:\Miniforge3\python.exe -m ruff check `
  src/quant/backtest/a_share_execution.py `
  src/quant/backtest/__init__.py `
  tests/unit/test_m3_formal_a_share_open_execution.py
D:\Miniforge3\python.exe -m mypy src/quant/backtest/a_share_execution.py
D:\Miniforge3\python.exe -c "import sys; import quant.backtest.a_share_execution; assert all(name not in sys.modules for name in ('qlib','lightgbm','mlflow'))"
git diff --check -- `
  docs/agent/M3_G7D_F1_R1正式A股开盘执行事实任务单.md `
  src/quant/backtest/a_share_execution.py `
  src/quant/backtest/__init__.py `
  tests/unit/test_m3_formal_a_share_open_execution.py
```

WSL Miniforge base 兼容验证：

```bash
cd /home/mabw/AI_Coding_win/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal
export PYTHONPATH="$PWD/src"
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q \
  tests/unit/test_m3_formal_a_share_open_execution.py \
  tests/unit/test_m3_formal_a_share_market_facts.py \
  tests/unit/test_m3_a_share_market_facts.py \
  tests/unit/test_m3_a_share_execution.py
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q \
  tests/unit/test_m3_formal_corporate_actions.py \
  tests/unit/test_m3_a_share_simulator.py
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check \
  src/quant/backtest/a_share_execution.py \
  src/quant/backtest/__init__.py \
  tests/unit/test_m3_formal_a_share_open_execution.py
/home/mabw/miniforge3/bin/conda run -n base python -m mypy \
  src/quant/backtest/a_share_execution.py
/home/mabw/miniforge3/bin/conda run -n base python -c \
  "import sys; import quant.backtest.a_share_execution; assert all(name not in sys.modules for name in ('qlib','lightgbm','mlflow'))"
```

当前 WSL 路径是 `/mnt/f`/wslfs/DrvFS；WSL 绿色只算双平台兼容证据，不能声称 Linux/ext4 Gate。

只有“实现与自测 -> 未参与实现者独立初验 -> 主 Agent 对 F0+G7C+F1+development 邻接最终验收”全部 PASS，
才可把本任务状态更新为主验 PASS 并冻结 G7D-F2。任务书冻结、单平台绿色或 development 示例均不得表述为
formal G7D/G7/M3 Gate 已完成。

## 12. R1 主验后 half-tick ambient Decimal R2 闭环（2026-08-10）

G7E/F2 hostile Decimal 对照发现：formal F1 open-state在计算涨跌停半tick边界时直接执行
`_PRICE_TICK / 2`，随后用ambient `upper - half` / `lower + half`。caller设置低precision与`Inexact` trap时，合法
有open证券会在F1抛出decimal异常；这违反formal投影不受caller ambient precision/rounding/traps影响的确定性合同。

R2仅关闭这两条边界算术：

1. half tick必须用exact `Decimal("0.005")`（或等价无除法常量），upper/lower阈值通过模块已有私有80位
   `_formal_subtract/_formal_add` 计算；禁止临时修改全局context或要求G7E包裹prec80。
2. buy/sell含等号拒绝、open/limit Decimal(str(float))、FULL_DAY/PARTIAL/板块/数量规则不变；不得改F0/F2/G7C。
3. 新增同一合法F0 capability在default28、prec50、prec4+ROUND_DOWN+Inexact trap下调用两个F1 public API，
   open-state逐字段与quantity rule exact相同，caller precision/rounding/Emax/Emin/traps/flags前后不变。
4. 半tick上下等号、刚内/刚外控制组均保留；hostile fake/dev/subclass仍在任何property访问前拒绝。
5. 白名单仅`a_share_execution.py`、`test_m3_formal_a_share_open_execution.py`、本任务状态与唯一交付报告
   `M3_G7D_F1_R2_halfTickAmbientDecimal返工交付报告.md`。双平台重跑F0/F1/F2邻接、Ruff/mypy/cold/diff；
   全新独立复验报告固定为`M3_G7D_F1_R2_halfTickAmbientDecimal独立复验报告.md`。

F1 R2 与正在进行的F2 R3均完成实现、全新独立复验和主Agent主验前，G7E保持暂停；不得以G7E自己的私有
context掩盖任一上游ambient缺口。
