# M4 P8 RUN-0B2B：Formal A股 PAPER Policy/Config Loader 任务单

日期：2026-08-09  
状态：主 Agent 最终验收通过（仅 development 工程合同；formal runtime/ext4/soak Gate仍开放）  
性质：development 工程前置；不创建正式 runtime/store/root，不启动 PAPER

## 1. 目标

新增一个只读、零网络、零状态写入的正式 A股 PAPER policy/config loader。它只能从已经 fresh 验证的
`VerifiedPaperRuntimeEnvironment` 及其 allowlisted `policy_selector` 推导项目内版本化 policy 文件，fresh
验证 TradingConfig、SH/SZ 费用覆盖、规则/适配器版本和 session effective window 后，签发 exact
`VerifiedPaperExecutionPolicy`。

本包不实现 gateway/service/runner，不修改 RUN-0B1 broker store，不消费 M3 target，不关闭 ext4、28日 soak
或 M4 Gate。它只关闭下一步正式装配所需的 policy 来源缺口。

## 2. 权威前置与诚实边界

- RUN-0A R3 `VerifiedPaperRuntimeEnvironment` 是唯一 formal 环境输入；不得接受 development 环境、caller path、
  caller hash、mapping、classification 或普通 proof。
- `quant.execution.config.TradingConfig`、`load_trading_config` 的字段与不变量仍是交易配置 SSOT；本文件不复制
 另一套语义实现。
- `quant.backtest.costs.ExecutionCostPeriod/Schedule` 是费用计算公共类型；本包只构造并 fresh 验证，不复制费用
 计算器。
- 第一版严格只支持 A股 `SH`、`SZ` 与 CNY；不签 HK、FX、SettlementRule 或 calendar capability。
- policy 数值是 **PAPER 模拟假设**，不是券商报价或实时法规声明。正式文件冻结为 2026 PAPER 运行假设：
  commission rate `0.00025`、minimum `5` CNY、sell stamp `0.0005`、transfer fee `0.00001`，SH/SZ相同；
  slippage/fill行为由版本 selector 表达，不把 research friction 当成交事实。上述数值与已验收研究基线一致，
  但本包新建独立 PAPER SSOT，不读取或依赖 research config。
- policy session window 从 `2026-01-01` 开始、open-ended；仅用于当前 2026 PAPER 工程链。未来费率或规则变化
  必须新增版本文件/selector，不原地覆盖 v1。

## 3. 文件与配置 SSOT

新增：

- formal：`configs/trading/policies/paper_a_share_v1.toml`
- development 示例：`configs/trading/policies/paper_a_share.example.toml`

formal 文件必须是 canonical UTF-8 TOML 业务输入，包含 exact：

1. policy meta/schema/version/effective window/supported markets；
2. 一个嵌套的完整 TradingConfig document（PAPER、`auto_trade=false`、`manual_approval=true`）；
3. SH/SZ exact cost periods 与 CNY settlement；
4. `adapter_policy_version`、`fill_policy_version`、`fault_policy_version`、`finality_policy_version`、
   `clock_policy_version`；
5. 明确 `classification="formal-paper-simulation"` 与 `assumption_notice`，禁止伪装券商/法规实时来源。

TradingConfig 的 `store.sqlite_uri` 必须 exact 为 `sqlite:///<environment.config.oms_sqlite_filename>`；
`fee_schedule_selector` 必须等于 policy cost selector，A股 rule selector必须等于 policy rule selector，
`fx_schedule_selector="cny_only_no_fx_v1"`。HK selector因 TradingConfig v1必填，只允许
`hk_connect_disabled_v1`，且 verified capability 的 supported markets 仍 exact `(SH,SZ)`。

example/development/fixture/unknown selector 或文件永远不能签 formal capability。

为消除实现自由度，formal v1 的其余 exact 值冻结如下；这些都是版本化 PAPER 模拟/安全参数，不是券商报价或
法规事实：

```text
classification = "formal-paper-simulation"
assumption_notice = "Versioned local PAPER simulation assumptions; not broker quotes or live-trading authority."
policy_schema_version = "paper-execution-policy-v1"
policy_version = "paper_a_share_v1"
effective_from = 2026-01-01
effective_to = absent/open
supported_markets = ["SH", "SZ"]

execution.mode = "PAPER"
execution.auto_trade = false
execution.manual_approval = true
execution.sell_only = false
execution.frozen_symbols = []
data.snapshot_max_age_seconds = 86400

risk effective_from = 2026-01-01, effective_to = absent/open
max_order_notional = 1000000.0
max_symbol_weight = 0.10
max_gross_exposure = 1.0
max_daily_notional = 5000000.0
max_orders_per_day = 50
max_cancels_per_day = 20

a_share_rule_selector = "a_share_execution_rules_v1"
hk_connect_rule_selector = "hk_connect_disabled_v1"
fee_schedule_selector = "paper_a_share_cost_schedule_v1"
fx_schedule_selector = "cny_only_no_fx_v1"
adapter_policy_version = "paper_durable_a_share_adapter_v1"
fill_policy_version = "paper_deterministic_fill_v1"
fault_policy_version = "paper_controlled_fault_drills_v1"
finality_policy_version = "paper_session_eod_finality_v1"
clock_policy_version = "utc_system_clock_v1"
```

SH 与 SZ cost period 各恰一条，均 `effective_from=2026-01-01`、open-ended、CNY，且 exact decimal strings：
`commission_rate="0.00025"`、`commission_min="5.00"`、`stamp_tax_sell="0.0005"`、
`transfer_fee="0.00001"`。policy不另含 slippage 数值；成交行为仅由 frozen fill policy version 标识，具体实现
属于下一包。formal文件内 `store.sqlite_uri` 是唯一按 environment OMS filename 动态比较的值，文件本身固定为
`sqlite:///oms.sqlite3`；因此只有 `environment.config.oms_sqlite_filename == "oms.sqlite3"` 才能签 v1。

example 文件使用相同结构但 exact `classification="development-example"`、
`policy_version="paper_a_share_example_v1"`，文件名含 `.example`；formal loader必须在解析业务内容前即拒绝其
selector/路径。除上述 explicit absent/open 字段外，不允许实现者自行增加默认值或新版本字符串。

## 4. 公共接口

新增 `src/quant/execution/paper_policy.py`：

```python
@dataclass(frozen=True, slots=True)
class VerifiedPaperExecutionPolicy:
    schema_version: str
    selector: str
    session_date: date
    source_path: Path
    source_file_identity: str
    source_parent_identity: str
    raw_sha256: str
    trading_config: TradingConfig
    trading_config_identity: str
    supported_markets: tuple[Market, ...]
    execution_cost_schedule: ExecutionCostSchedule
    cost_schedule_identity: str
    minimum_order_notionals: tuple[MoneyAmount, ...]
    a_share_rule_selector: str
    adapter_policy_version: str
    fill_policy_version: str
    fault_policy_version: str
    finality_policy_version: str
    clock_policy_version: str
    fx_snapshot_identity: None
    policy_identity: str
    verified_at: datetime
    # private process-local attestation, repr/compare excluded

def load_verified_paper_execution_policy(
    *, environment: VerifiedPaperRuntimeEnvironment,
    session_date: date,
    now: datetime,
) -> VerifiedPaperExecutionPolicy: ...

def verify_existing_paper_execution_policy(
    *, policy: VerifiedPaperExecutionPolicy,
    environment: VerifiedPaperRuntimeEnvironment,
    now: datetime,
) -> VerifiedPaperExecutionPolicy: ...
```

formal mint 必须是模块私有 closure 内唯一签发路径；模块不得暴露 generic signer/builder/key/factory。existing verifier
必须 fresh 调同一 public loader并 exact compare，不得只验 token。exact type，不接受 subclass、dict、
`object.__new__` 伪对象或 development值。

`now` 必须 aware UTC且与 environment verified window相容；`session_date` exact date且落在 policy/risk/cost完整
覆盖内。成功结果 `fx_snapshot_identity is None`。

## 5. 路径、读取与身份闭包

- 唯一路径为
  `environment.config.project_root/configs/trading/policies/<environment.config.policy_selector>.toml`；selector先按
  runtime既有严格语法和 formal禁词验证，禁止 caller path与目录遍历。
- project root必须与 environment exact physical identity一致；policy父目录/文件必须 regular、无
  symlink/junction/reparse/hardlink alias，且位于项目root内。
- 使用 anchored open-instance读取并冻结 file/parent physical identity、length、SHA；解析后、签发前 fresh复核
  environment、project/parent/file identity与可观察内容。不可观察真ABA及拥有trusted config root写权限者仍是明确
  信任边界，不宣称密码学防篡改。
- 失败不得创建任何 runtime leaf、DB、journal、receipt、日志或缓存。

## 6. 语义验证

1. policy TOML exact字段集、canonical text/value类型，无未知字段、float金额或隐式默认；所有金额/费率用
   canonical decimal string。
2. 嵌套 TradingConfig 必须通过现有构造器 fresh验证；mode=PAPER、auto_trade=false、manual_approval=true。
3. `risk.limits` 对 session_date exact唯一覆盖，无gap/overlap；store URI与environment OMS filename exact。
4. supported markets exact `(Market.SH, Market.SZ)`；每个市场恰有一个覆盖 session_date的
   `ExecutionCostPeriod`，区间无gap/overlap，CNY settlement；缺一个市场即拒绝。
5. cost schedule由公共 `build_execution_cost_schedule`构造；policy identity绑定 canonical raw、TradingConfig
  identity、schedule、minimum notionals、版本 selectors、session date及environment verification identity。
6. rule/cost/fill/fault/finality/clock selector均为非空版本标识，不能包含path/URI/secret/control字符。
7. policy不实现 fill/fault具体算法；只冻结下一包 factory必须 exact匹配的版本声明。

`minimum_order_notionals` 必须复用 `OrderPlannerConfig` 的权威形态，exact 为
`(build_money_amount(Currency.CNY, Decimal("1.00")),)`；它是 PAPER 模拟中的最小经济金额过滤阈值，SH/SZ
共同使用 CNY，不按 Market 复制两份。board lot、价格和费用仍由各自既有规则决定；该阈值不是佣金下限、
券商最小委托额或法规陈述。formal TOML 使用 canonical decimal string `"1.00"`，example不得进入formal。

## 7. 稳定失败语义

唯一公开错误类型 `PaperExecutionPolicyError`，稳定码至少区分：

- `PAPER_POLICY_ENVIRONMENT_INVALID`
- `PAPER_POLICY_SELECTOR_UNSUPPORTED`
- `PAPER_POLICY_SOURCE_INVALID`
- `PAPER_POLICY_SEMANTICS_INVALID`
- `PAPER_POLICY_STALE`

所有公开异常 cause/context均为None，repr/traceback不含路径、raw、SQL、TOKEN或hostile marker。任一失败零
网络、零root/DB/journal写、零下游gateway/service调用。

## 8. 白名单

- 新 `src/quant/execution/paper_policy.py`
- 新 `configs/trading/policies/paper_a_share_v1.toml`
- 新 `configs/trading/policies/paper_a_share.example.toml`
- 新 `tests/unit/test_paper_policy.py`
- 必要时最小同步 `configs/trading/paper_runtime.example.toml` 的 selector示例
- 本任务单、唯一交付报告、唯一独立复验报告

禁止修改 `paper_runtime.py`、`paper_broker_store.py`、gateway、service、CLI、store/migration、P4-P8、soak、
package root、M1/M3或正式 artifacts/journal。

## 9. 必测正例与反例

正例：纯合同模拟 formal WSL2/ext4环境下，2026边界日与普通session均签 exact SH/SZ policy；existing fresh返回
exact相等；development config只能产生非formal结果或稳定拒绝。

反例至少覆盖：

- unknown/path-traversal/example/development selector；caller path/hash/mapping/classification注入；
- runtime environment subclass/伪对象/旧token/nested config-layout-platform drift；Windows/DrvFS development值；
- policy symlink/junction/reparse/hardlink、同bytes换inode、parent/project replacement、读取中persistent drift；
- TOML unknown/missing/duplicate/非canonical、float decimal、secret/path/SQL marker；
- mode/auto_trade/manual approval/store URI/rule/fee/FX selector漂移；
- effective window/risk gap或overlap、日期边界缺口；SH有费率但SZ缺、跨市场重复、币种错误；
- whole-file重写并重算普通hash但保留旧capability；existing必须fresh拒绝；
- hostile reader/parser/TradingConfig/cost builder ValueError及RuntimeError，固定码、空异常链、零写；
- 模块表面无generic signer、factory、32-byte key；import不加载broker/soak/LightGBM/Qlib且零网络。

Windows原生与WSL base运行定向 pytest、Ruff、mypy、cold import；DrvFS只算开发兼容。实现和独立初验必须
使用不同上下文；初验补至少一个未使用的path/whole-rehash/hostile反例。

## 10. 停止条件与完成边界

若实现需要引入HK/FX/calendar、修改TradingConfig schema或B1/P4-P8业务语义、用development policy打通formal、
创建runtime root/store、联网或从research config运行时读取，则停止并回主Agent重冻。

B2B通过只解锁下一包 formal gateway/store/service factory 的policy输入；TargetLoader仍等待M3 G7A，
LedgerContextProvider仍等待verified calendar/settlement来源。不得注册scheduler或启动soak。
