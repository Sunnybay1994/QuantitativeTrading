```python

@dataclass(frozen=True)
class BacktestIdentity:
    experiment_key: str
    work_key: str
    g1_release_id: str
    dataset_snapshot_id: str
    model: str
    model_version: str
    fold: str
    horizon_sessions: int
    strategy_version: str
    scenario: Literal["0p5x", "1p0x", "2p0x"]
    cost_multiplier: float
    order_quantity_rule_version: str

@dataclass(frozen=True)
class VerifiedBacktestArtifact:
    root: Path
    metrics: BacktestMetricsV1
    manifest: BacktestBundleManifestV1
    manifest_sha256: str
    backtest_receipt_sha256: str

def build_target_artifact(
    *, release: VerifiedG1Release, feature: VerifiedFeatureArtifact,
    prediction: VerifiedPredictionArtifact, folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity, config: LoadedM3Config,
    spec: TargetBuildSpec, output_root: Path,
) -> TargetManifestV1: ...

def build_backtest_plan_artifact(
    *, target: VerifiedTargetArtifact, release: VerifiedG1Release,
    folds: VerifiedFoldPlanArtifact, experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    output_root: Path,
) -> BacktestPlanManifestV1: ...

def simulate_a_share_scenario(
    *, target: VerifiedTargetArtifact, plan: VerifiedBacktestPlanArtifact,
    facts: VerifiedAShareMarketFacts, cost_periods: tuple[AShareCostPeriod, ...],
    multiplier: Decimal, initial_cash: Decimal,
) -> AShareSimulationResult: ...

def build_backtest_artifact(
    *, target: VerifiedTargetArtifact, plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release, experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, output_root: Path,
) -> BacktestBundleManifestV1: ...

def verify_backtest_artifact(
    *, root: Path, receipt_path: Path, target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact, release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity, config: LoadedM3Config,
    artifact_roots: Mapping[str, Path],
) -> VerifiedBacktestArtifact: ...
```

目标权重是完整目标组合语义：在某个 `(as_of,strategy,strategy_version)` 切片中未出现的证券目标为 0，
显式 0 只用于审计，并不改变语义。策略仍不读取账户；模拟器用“当前持仓 ∪ 当日目标 ∪ 当日公司行动
相关证券”计算差量。禁止只遍历当日有 bar 的证券，否则停牌持仓会从 NAV 消失。

`build_backtest_plan_artifact` 的调度阶段只接受 SH/SZ，使用 verified G1 中已审计一致的 SH session；
`execution_date` 必须严格晚于
`as_of`。尾部没有下一 session、区间外信号或同一切片重复目标都进入 diagnostics；不得静默当日成交。
同一信号日若包含多个策略版本或预测身份，必须在进入本函数前分片，不能自动混合。

模拟器只接收 `VerifiedTargetArtifact` 与 `VerifiedBacktestPlanArtifact`；target 文件 hash、策略身份
与 manifest 不符时在账户状态创建前失败。结果 manifest 继承其 snapshot/fold/horizon/model lineage，
每个 fold×horizon×cost multiplier 独立发布，禁止把多个预测切片拼成一条连续 NAV。
账户引擎使用的受控 market-facts view 只能从同一个 `VerifiedG1Release.artifact_paths` 重建；八个事实文件还
必须包含 corporate-action reconciliation，供 FULL_DAY event-date mark 使用。只分别通过 Schema 但 release
identity 不同仍然失败。

单日账户事件顺序冻结为：

1. session 开始前结算上一 session 买入，使其变为可卖；
2. 根据 record-date 收盘持仓生成的 entitlement，在 ex-date 确认现金/红股应收；cash/stock 两个 leg 独立
   `CAPTURED→RECOGNIZED→SETTLED`，pay-date 转为现金，
   stock-list-date 转为持仓；买入 ex-date 的证券不得取得该次权益；
3. 用当日未复权 open 计算盘前权益和目标股数；卖出先于买入；
4. 执行涨跌停、停牌、T+1、分板块申报数量和现金门禁；被拒部分保留目标但不得假装成交；
5. 用未复权 close 估值并写 NAV、持仓、拒绝和诊断；
6. 收盘后按实际持仓捕获当日 record-date entitlement，供未来 ex/pay/list date 使用。

单一 entitlement `state` 不足以表达 cash pay 与 stock list 不同日，禁止实现。CAPTURED 只证明登记日数量，
证券仍按含权价交易，因此不计入 NAV 应收；只有 ex-date RECOGNIZED leg 才进入现金/红股应收。cash
receivable 保留未舍入 gross Decimal，pay-date 入现金时按 HALF_UP cent 并显式记录 rounding delta；不得在
捕获日提前计价或静默吞掉舍入差。

对实际持仓相关事件，`record_date/ex_date` 必需且 `record_date < ex_date`；通用 G1 Schema 虽允许 `<=`，
但同日无法先在 record close 捕获、再在 ex-date 盘前确认，G7 必须 fail-closed。仅当
`cash_per_share_gross>0` 时 `pay_date` 必需，仅当
`stock_ratio>0` 时 `stock_list_date` 必需。相关结算日期缺失、事件版本冲突、应收股无法确定为整数，或 factor 跳变
无法由公司行动解释时回测 fail-closed；现金分量为 0 不得伪造 pay date，送转分量为 0 不得伪造 list date，
也不得把非零现金或红股静默提前到 ex-date。首版现金使用税前金额，
不模拟个人持有期红利税；不参与配股，发现影响持仓的未支持权益事件即失败，并在报告披露限制。
全日停牌且无 bar 的普通日持仓不能归零，沿用上次 mark；公司行动 ex-date 则不允许现金/送转公式回退。P3
真实探针已证明 dividend 两字段不能总能恢复交易所最终除权参考价。event ex-date 有实际 bar 时直接估值；
FULL_DAY 无 bar 时只能从同一 verified G1 release 的 corporate-action reconciliation 取得该日唯一已闭合的
`actual_factor_ratio`，按 `previous_mark/actual_factor_ratio` 调整 market mark。缺 evidence、ratio 非正、
event 集不匹配或非 FULL_DAY 无 bar 均 fail-closed；不得 forward-fill 或用账户 entitlement 反推。账户只对
record-close 已捕获的持仓确认现金/红股应收。

开盘执行采用保守日频口径：FULL_DAY 停牌不成交；PARTIAL detail 按精确 `" | "` 拆分，每段只接受
`HH:MM-HH:MM` 半开区间；全部可解析且 09:30 不落入任何区间才证明开盘可交易，未知文本保守拒绝；
`open` 与 `up_limit/down_limit` 在半个最小价位内分别视为买入/卖出不可成交。A 股执行不得使用统一
`board_lot`：沪深主板/创业板买入按 100 股整数倍，科创板按最少 200 股、之后 1 股递增；卖出还要分别处理
零股尾数和不足最小申报量的全余额退出。代码 prefix 分类、合法卖量、官方依据、版本常量及反例只以现行
G7 任务书 §5/§7 为 SSOT；未知板块 fail-closed。阻塞卖出后不得假设其现金可用于买入。

目标卖出量超过 sellable 时，先分离 `T_PLUS_ONE` residual，再把可卖上限向下裁到该板块允许的最大合法申报
数量，第二段残差记 `LOT_CONSTRAINT`；不能把裸 `min(requested,sellable)` 当成合法订单，也不得因为一部分
未结算而整单拒绝。跌停/停牌导致的 0 目标退出会在之后每个 ACTIVE batch 继续尝试，
直到卖出或测试窗口结束；结果必须报告终止时未完成退出市值。

现金不足时，先把每只可执行买单表示为期望股数 `d_i` 和该板块合法数量集合 `V_i`。以当日场景执行价和
完整逐单费率（含滑点、最低佣金等非线性项）定义 `cash_required(q)`；在 `{q/d_i | q∈V_i}` 的精确
`Fraction` breakpoints 上选择最大可行 `lambda`，再按动态余量和 symbol 稳定顺序尝试下一合法数量。科创板
从 0 激活是 200 股、激活后递增 1 股，不能把它误写成逐 100 股 lot。每次重算整组精确费用和现金；全程
`q_i<=d_i`、现金不得为负，也不得使用被拒卖单的预期收入。
禁止按名义金额粗略比例、最终总 fee 乘倍数或输入行序先到先得。每日输出 `gross_turnover=sum(abs(notional))/pre_trade_equity`
和 `one_way_turnover=gross_turnover/2`，研究报告以 one-way 为主并同时保留 gross。

金额、费率和现金可行性内部统一使用 `Decimal`。执行价按 `BUY_CEIL_SELL_FLOOR_TICK_V1`，佣金/印花税/
过户费逐分项按 `EACH_COMPONENT_HALF_UP_CENT_V1`，现金权益结算按 `HALF_UP_CENT_V1`；三项策略进入版本化
backtest scientific config。无 open 且正目标时 desired quantity 不可知，拒绝数量写 null、以
`rejected_notional` 表达缺口，不得伪造 0 股成功或用未来 close 反推数量。

成本按日期选择唯一闭区间 period；重叠、缺口或交易早于首个 period 均失败。`cost_multiplier` 只缩放
可协商/模拟摩擦 `commission_rate,commission_min,slippage`，法定印花税和过户费保持历史期值不变；
报告名称必须写“摩擦压力 0.5×/1×/2×”，不得误称税费也被缩放。基准收益独立读取
`510300.SH`，成本后超额不得用训练标签拼接计算。

每个 fold×horizon 从同一初始现金独立开始，只允许 test 日期产生信号；第一个估值收益时点是首个目标
执行日 open，最后一个 test 信号必须在下一 SH session open 执行并在该日 close 终值估值。因此 G1 tail
至少覆盖该执行日。首版 `force_liquidation=false`，不为美化结果强平；另报按终值价格和 1×成本估算的
退出成本及未完成退出。benchmark 使用完全相同的 first execution open 和 terminal close。重叠 fold
不能顺序复合。`net_excess_return` 固定为组合总收益减基准总收益，同时另报
`relative_wealth=(1+portfolio_return)/(1+benchmark_return)-1`。

G7B 前必须先完成独立 G7P0 config 增量：三种舍入方法与 `annualization_sessions=252` 进入 scientific
selector；当前 `config.py`/示例 TOML 尚未实现，任何 G7 handler 不得先硬编码绕过。精确 strict metrics、七张
输出表、market-facts identity 与 stage receipt 闭包以现行 G7 任务单为准，主文档不再复制第二套字段清单。

turnover 同时报 target 与 realized 两套；前者基于相邻完整目标权重，后者基于实际成交。`test_turnover`
指 realized one-way turnover，分母为逐日 pre-trade equity。轻量版假设非停牌、非开盘封板且有合法
open 时可按开盘价加固定滑点成交，不模拟成交量参与率、部分成交或市场冲击，报告必须明确该限制。

现行 G7P0 加 G7A–G7F 七包机械实现与独立初验要求见
[`M3_G7目标到账户回测分包骨架与外部闭环任务单.md`](agent/M3_G7目标到账户回测分包骨架与外部闭环任务单.md)；
旧 [`M3_G7统一回测实现与初验任务单.md`](../../M3_G7统一回测实现与初验任务单.md) 仅保留历史。

## 5. 可直接交给另一个 Agent 的任务包

每个任务包都可以独立提交。Agent 开始前必须阅读根目录 `AGENTS.md` 和
`karpathy-guidelines.md`，不得读取 `archive/legacy_pre_greenfield/` 或 `data/legacy/`。

本节 D1–D8 是首轮骨架的历史拆分；当前返工与新增实现不得只按下文摘要执行。现行机械任务唯一入口：

- D1/D4/D5/D7 二次返工：[`M3_D1-D8二次返工任务单.md`](agent/M3_D1-D8二次返工任务单.md)；
- E0/E3 staging/run-state：[`M3_G2-G8另一个Agent任务单.md`](../../M3_G2-G8另一个Agent任务单.md)；
- C0 配置：[`M3_C0配置加载与身份哈希实现初验任务单.md`](agent/M3_C0配置加载与身份哈希实现初验任务单.md)；
- E3 严格 receipt 增量：[`M3_E3严格Receipt增量返工任务单.md`](agent/M3_E3严格Receipt增量返工任务单.md)；
- G1-P1 L0A/B1/B2B 核心映射：
  [`M3_G1_L0A_B1_B2B核心映射外部闭环任务单.md`](agent/M3_G1_L0A_B1_B2B核心映射外部闭环任务单.md)；
- G1-P1 当前终验返工：[`M3_G1_P1主验一次返工任务单.md`](agent/M3_G1_P1主验一次返工任务单.md)；
- G1-P1 最新终验返工：[`M3_G1_P1主验二次返工任务单.md`](agent/M3_G1_P1主验二次返工任务单.md)；
- G1-P1 最终验收：[`M3_G1_P1主Agent最终验收报告.md`](agent/M3_G1_P1主Agent最终验收报告.md)；
- G1-P2-0 信号边界与成员方法配置修正：
  [`M3_G1_P2_0信号边界与成员方法配置修正外部闭环任务单.md`](agent/M3_G1_P2_0信号边界与成员方法配置修正外部闭环任务单.md)；
- G1-P2-0 最终验收：[`M3_G1_P2_0主Agent最终验收报告.md`](agent/M3_G1_P2_0主Agent最终验收报告.md)；
- G1-P2 B3 PIT 成员状态：
  [`M3_G1_P2_B3PIT成员状态外部闭环任务单.md`](agent/M3_G1_P2_B3PIT成员状态外部闭环任务单.md)；
- G1-P2 B3 最终验收：
  [`M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md`](agent/M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md)；
- G1-P3 B2C 执行事实：
  [`M3_G1_P3_B2C执行事实外部闭环任务单.md`](agent/M3_G1_P3_B2C执行事实外部闭环任务单.md)；
- G1-P4 B4 candidate/跨源/release 三段式闭环：
  [`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](agent/M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md)；
- G2–G3 snapshot/provider/标签五段式闭环：
  [`M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md`](agent/M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md)；
  旧合并任务与一致性历史见 [`M3_G2-G3Provider与标签对账实现初验任务单.md`](../../M3_G2-G3Provider与标签对账实现初验任务单.md)、
  [`M3_G2-G3跨文档一致性初验报告.md`](agent/M3_G2-G3跨文档一致性初验报告.md)；
- G4–G6 研究链七段式闭环：
  [`M3_G4_G6研究链分包骨架与外部闭环任务单.md`](agent/M3_G4_G6研究链分包骨架与外部闭环任务单.md)；
  旧合并任务与设计历史见
  [`M3_G4-G6研究链实现与初验任务单.md`](../../M3_G4-G6研究链实现与初验任务单.md)、
  [`M3_G4-G6设计审查与修订记录.md`](agent/M3_G4-G6设计审查与修订记录.md)；
- G7 六段式闭环：
  [`M3_G7目标到账户回测分包骨架与外部闭环任务单.md`](agent/M3_G7目标到账户回测分包骨架与外部闭环任务单.md)；
  旧合并任务与根因历史见 [`M3_G7统一回测实现与初验任务单.md`](../../M3_G7统一回测实现与初验任务单.md)、
  [`M3_G7设计审查与修订记录.md`](agent/M3_G7设计审查与修订记录.md)；
- G8 六段式闭环：
  [`M3_G8Continuation编排恢复追踪分包骨架与外部闭环任务单.md`](agent/M3_G8Continuation编排恢复追踪分包骨架与外部闭环任务单.md)；
  旧合并任务与设计历史见
  [`M3_G8编排与追踪实现初验任务单.md`](../../M3_G8编排与追踪实现初验任务单.md)、
  [`M3_G8设计审查与修订记录.md`](agent/M3_G8设计审查与修订记录.md)；
- G9 七段式闭环：
  [`M3_G9最终准入分包骨架与外部闭环任务单.md`](agent/M3_G9最终准入分包骨架与外部闭环任务单.md)；
  旧合并任务与设计历史见
  [`M3_G9最终验收实现与独立初验任务单.md`](../../M3_G9最终验收实现与独立初验任务单.md)、
  [`M3_G9设计审查与修订记录.md`](agent/M3_G9设计审查与修订记录.md)。

若历史 D 摘要与上述任务或 4.x SSOT 冲突，以 4.x SSOT 和现行独立任务书为准。

### D1：运行时就绪审计（历史标题曾含“配置加载”）

- 新增：`readiness.py`、`tests/unit/test_m3_readiness.py`。
- 只实现 4.1 的接口；不得安装依赖、不得联网。
- TOML 加载与分层 hash 已移至 C0；D1 不得另建 parser 或默认值。
- fixture 覆盖每个 ERROR code；错误排序固定为 `severity,code,message`。
- 验收：缺 PIT 成分、缺 benchmark、短历史、低截面、缺 factor、embargo 小于最大 horizon 均被拒绝。

### D2：交易日 fold 与 embargo

- 新增：`folds.py`、`tests/unit/test_m3_folds.py`。
- 只实现 4.4；复用 `TemporalFold`，不得复制 dataclass。
- 验收：周末/节假日不计数、窗口不重叠、尾部不足完整 test 时不生成 fold、训练标签可知时点过滤正确。

### D3：独立标签计算

- 新增：`labels.py`、`tests/unit/test_m3_labels.py`。
- 只实现 4.3；不 import Qlib。
- 验收：5/10 日手算值、基准相减、跨节假日、停牌缺价、尾部截断、重复行情拒绝。
- 停牌缺价不得 forward-fill；该证券该样本不输出并计入质量报告。

### D4：确定性 staging 与 manifest

- 新增：`snapshot.py` 中除 `materialize_qlib_provider` 外的函数和单测。
- 文件名统一为 Qlib 标准化证券代码的小写形式；映射规则写独立纯函数并测试 SH/SZ。
- 验收：输入顺序打乱后 manifest hash 不变；修改任一价格后 hash 改变；manifest 不含绝对路径和时间戳。

### D5：预测指标

- 新增：`evaluate.py`、`tests/unit/test_m3_evaluate.py`。
- 只实现 4.7；不 import Qlib/MLflow。
- 与 SciPy/Pandas 手算 fixture 对账；若不新增 SciPy 依赖，使用 Polars/Pandas 已有能力。

### D6：分数标准化与无状态 Top-k

- 新增预测 DataFrame 标准化函数；实现不带持仓状态的等权 Top-k 第一版。
- `n_drop` 状态化策略暂不做，先形成接口评审记录。
- 验收：分数并列、空截面、资格过滤、现金缓冲、最大权重、显式零目标均有测试。

### D7：MLflow 薄适配器

- 新增：`tracking.py`、mock 单测。
- 只在函数内部 import MLflow；默认测试不能创建真实 server。
- 验收：所有必需 params/tags/metrics/artifacts 被调用；token、绝对本机路径和个人信息不会进入日志。

### D8：固定版本 Qlib dump 工具获取器

- 新增：`src/quant/research/m3/fetch_qlib_tool.py` 和 mock 网络单测。
- 只接收 C0 从已验证配置构造的 `QlibDumpToolSpec`，不得自行读取 TOML；下载到临时文件，URL、字节数和 SHA-256
  全部匹配后再原子移动到 `data/external/qlib/v0.9.7/dump_bin.py`。
- 已存在文件先验 hash；相同则复用，不同则拒绝，禁止静默覆盖。
- 默认测试不得联网；真实网络测试显式标记。不得把上游脚本内容复制进项目源码。

## 6. 主 Agent 决策与未关闭门禁

### 6.1 G0：Qlib/Python 兼容

当前证据：

- WSL Miniforge base 是 Python `3.13.13`；
- Qlib 0.9.7 官方支持矩阵仅列 Python 3.8–3.12；
- PyPI 0.9.7 只有 CPython 3.8–3.12 wheel，没有 sdist 和 CPython 3.13 wheel；
- 本机 `pip index versions pyqlib` 返回 `No matching distribution found`。

决策：不在 Python 3.13 上进行不受支持的源码硬装，也不修改核心代码来复刻 Alpha158。项目日常开发、
测试和运行继续使用 WSL Miniforge `base`。按 `AGENTS.md` §8 的通用版本隔离规则，当前 G0 可使用名为
`py312` 的 WSL Miniforge 隔离环境；非交互调用固定为
`/home/mabw/miniforge3/bin/conda run -n py312 <command>`。`py312` 是当前 G0 的具体环境，不是唯一可授权的
版本隔离环境；其他第三方 Python 版本问题须由主 Agent 先确认真实兼容证据和任务边界。不得降级、升级或
修改 `base`，也不得使用 Windows Python/conda。

`py312` 已取得 Python 3.12.13、官方 `pyqlib==0.9.7` wheel、`pip check`、Alpha158/LGBModel import、
readiness 与 base 不变性证据；见
[`M3_G0_py312环境创建与兼容探针主Agent最终验收报告.md`](agent/M3_G0_py312环境创建与兼容探针主Agent最终验收报告.md)。
这只关闭 G0 Python 子项；`meta.enabled` 在真实 G1 数据、provider 和正式 Gate 未完成前仍保持 `false`。源码安装
Qlib 即使偶然成功也不满足可复现验收，不作为方案。

### 6.2 Qlib dump 工具供应链（决策已完成）

固定版本信息已经写入 M3 TOML：

- tag：`v0.9.7`；
- URL：`https://raw.githubusercontent.com/microsoft/qlib/v0.9.7/scripts/dump_bin.py`；
- 原始字节数：`21847`；
- SHA-256：`b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f`。

不把上游脚本复制进 `src/`。D8 获取器负责下载、完整性校验和缓存；snapshot manifest 必须记录
上述版本和哈希。只有 hash 匹配的脚本可以执行。

### 6.3 G1：本地数据审计

2026-07-12 的只读审计结果：

| 资产 | 当前证据 | G1 判断 |
|---|---|---|
| `universe_membership` | 仅 `SH_CONNECT`/`SZ_CONNECT`，均从 2026-07-10 起；无目标 M3 universe | 不通过 |
| 股票日线 | Tushare 4 只×1日；BaoStock 1只×5日；AKShare 股票仅1只×1日 | 不通过 |
| 股票复权因子 | Tushare/BaoStock 均只覆盖 1 只股票 | 不通过 |
| ETF 长历史 | 11 只 ETF，2023–2026，共 9,361 行 | 不能替代股票 Alpha158 |
| 证券主表 | SH/SZ/HK 股票共 8,756 条，含上市/退市请求结果 | 可作代码和生命周期基础 |

因此当前不能生成 M3 snapshot，更不能训练模型。

### 6.4 G1：Tushare 2000 积分取数计划

用户已明确当前泄露过的 token 在研究阶段仍可使用，实盘前再轮换。调用必须脱敏，禁止把 token 放入
日志、receipt、命令输出或 MLflow。严格分四阶段执行，每阶段 raw 不可覆盖并可断点续跑：
