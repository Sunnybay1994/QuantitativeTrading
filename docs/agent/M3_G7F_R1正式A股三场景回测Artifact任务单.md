# M3 G7F R1：正式 A 股三场景回测 Artifact 任务单

日期：2026-08-10
状态：**R4 release/context 实体绑定工程主验 PASS；G8 同步返工已解锁；Linux/ext4 与 M3 Gate 仍开放**
环境：Windows 原生 Miniforge 定向反馈；WSL Miniforge `base` 正式兼容与 Gate 验证；默认不联网、不触真实账户

## 1. 目标、硬前置与唯一职责

G7F 是 G7 的唯一正式 backtest stage：从 freshly verified target/plan/experiment/G1 release 与 scientific config
构造一次唯一 formal market-facts capability，以相同初始现金、基础成本日程和 facts 独立调用 actual G7E 三次，
生成 `0p5x/1p0x/2p0x` 七表、严格指标、scenario manifest、root metrics/manifest，并由后续 StageRunner 发布
exact receipt。

硬前置：

1. [G7E R1 任务单](M3_G7E_R1正式A股单场景账户回放任务单.md)对应实现、独立复验、主验全部 PASS；
2. [G7F-P0 nested publication 任务单](M3_G7F_P0_R1共享NestedArtifactPublication任务单.md)对应主验 PASS；
3. G7B、G7D-F0 R4、G7C R3、G7D-F1/F2 R2 的既有主验继续有效。

任一前置未 PASS，本任务只能保持设计冻结，禁止实现。G7F 不改变交易逻辑、G7E 七表、contracts/config/Schema，
不实现 StageRunner 或 receipt writer，也不更新路线图/Gate。

权威来源：

- [G7 分包骨架 §9/§9.1](M3_G7目标到账户回测分包骨架与外部闭环任务单.md)；
- [M3 实施 SSOT §4.8](../M3实施与Agent交接.md)；
- `src/quant/research/m3/contracts.py` 中现有 `AShareScenarioMetricsV1`、`BacktestMetricsV1`、
  `BacktestScenarioManifestV1`、`BacktestBundleManifestV1`、`VerifiedBacktestArtifact`；
- actual `load_verified_a_share_market_facts`、`verify_backtest_plan_artifact` 与
  `simulate_formal_a_share_scenario`；
- P0 主验后的共享 nested `ArtifactPublication` 与现有 strict receipt verifier。

## 2. Development reporting 三个已知缺口

现有 `a_share_reporting.py` 的 development/example 路径只能作结构参考，以下结论禁止复制到 formal：

1. `rejection_count=result.rejections.height` 错把 rejection reason 行数当成“有 residual 的 order intent 数”；一个
   intent 可同时有 T+1/lot 等多段 residual，正式值必须按 order identity 去重；
2. portfolio/annualized/benchmark/relative wealth/fee aggregate 等大量直接 float 运算；正式计算必须先用冻结
   Decimal context 重算，最后单向投影 finite float；
3. terminal exit cost 用 mark notional 计 fee，再用 `notional * slippage` 粗估，未应用 formal SELL floor-to-tick
   execution price；正式值必须按 terminal mark、1× sell slippage、0.01 tick、实际 execution notional 与逐分项
   HALF_UP fee 估算。

开发 builder 还使用 development facts/G7E、逐子目录普通 mkdir/write，不具 formal fresh/whole-root transaction
资格。正式实现不得给 development 函数改名后冒充通过，也不得破坏现有 development 行为。

## 3. 冻结 public API、fresh context 与稳定错误

在 `src/quant/backtest/a_share_reporting.py` 增加：

```python
@dataclass(frozen=True)
class BacktestArtifactFreshVerificationContext:
    facts_fresh_context: AShareMarketFactsFreshVerificationContext
    upstream_paths: BacktestArtifactUpstreamPaths

    def __reduce__(self) -> Any:
        raise TypeError("M3_A_SHARE_BACKTEST_ARTIFACT_INVALID")


class AShareBacktestArtifactError(ValueError):
    """Stable formal A-share backtest artifact contract error."""


def build_backtest_artifact(
    *,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestArtifactFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
    output_root: Path,
) -> BacktestBundleManifestV1: ...


def verify_backtest_artifact(
    *,
    root: Path,
    receipt_path: Path,
    target: VerifiedTargetArtifact,
    plan: VerifiedBacktestPlanArtifact,
    release: VerifiedG1Release,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config,
    fresh_context: BacktestArtifactFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> VerifiedBacktestArtifact: ...
```

`BacktestArtifactUpstreamPaths` 复用现有四字段值对象：target/plan/experiment/G1 receipt path；formal boundary 必须
把其 exact path、physical identity 与 verified bundle/nested fresh context 对齐，不信任 caller 路径。

普通 formal 失败稳定为 `M3_A_SHARE_BACKTEST_ARTIFACT_INVALID`；P0 无法证明精确 rollback 时单独稳定为
`M3_A_SHARE_BACKTEST_ARTIFACT_ROLLBACK_FAILED`。两者均为 `AShareBacktestArtifactError`，`cause/context=None`，
不得泄露 path、hash、symbol、date、TOKEN、SQL、PID、private marker 或嵌套异常。

## 4. Builder fresh 链与三次 actual G7E

builder 必须先进入 P0 `ArtifactPublication(output_root)` lease；`output_root` 是 caller/StageRunner 已创建的 exact
empty real directory。lease 覆盖全部 fresh verification、三次回放、指标、序列化、readback 和 commit，关闭
“长计算后首写前 root 被替换”的窗口。

在写第一个内容字节前依次：

1. exact type/identity 校验 outer bundles、config、context、roots；upstream paths 与 nested context exact；
2. 校验 config scientific identity、`friction_multipliers` 精确为 `0.5,1.0,2.0`、scaled components 精确为
   `commission_rate,commission_min,slippage`、rounding versions、annualization=252、initial cash finite positive；
3. public `verify_backtest_plan_artifact(...)` exact once，得到 `fresh_plan`；要求 outer plan 的 root/manifest/hash/
   receipt/scheduled frame 与 fresh result exact，后续 target turnover 只使用 `fresh_plan.scheduled_targets`；
4. public `load_verified_a_share_market_facts(release=release, plan=fresh_plan,
   fresh_context=facts_fresh_context, artifact_roots=...)` exact once；不得复制 F0 或创建第二 facts capability；
5. facts identity 与 fresh plan、release、config benchmark `510300.SH` exact；
6. 从 config 唯一派生 base `AShareCostPeriod` tuple、initial cash、annualization；不接受 caller multiplier、schedule、
   metrics、result、fills、transition 或 digest；
7. 构造 `AShareSimulationFreshVerificationContext(release=release,
   facts_fresh_context=facts_fresh_context)`，按固定顺序调用 actual G7E **恰三次**：

```python
for scenario, multiplier in (
    ("0p5x", Decimal("0.5")),
    ("1p0x", Decimal("1")),
    ("2p0x", Decimal("2")),
):
    result = simulate_formal_a_share_scenario(
        target=target,
        plan=fresh_plan,
        facts=facts,
        cost_periods=base_periods,
        multiplier=multiplier,
        initial_cash=initial_cash,
        fresh_context=simulation_fresh_context,
        artifact_roots=artifact_roots,
    )
```

三个 scenario 从相同初始状态独立回放；禁止沿用前一场景 cash/position/replay、复用 1× fills 或对结果按费用差
后处理。三个 result 的 multiplier 必须与 scenario exact，facts digest 必须完全相同。低成本 NAV 不保证逐日支配
高成本；反常只可诊断，不得换标签或篡改 fills。

## 5. 成本日程与 canonical cost hash

base periods 只从 `config.section("costs")["a_share_periods"]` 构造，连续/覆盖规则与 fresh plan 已验真
`cost_schedule.json` exact。G7E 始终接 base periods + multiplier，由 F2 缩放可协商摩擦；stamp tax 与 transfer fee
保持 base 历史值。

scenario manifest 的 `cost_periods_sha256` 对该 scenario 的 effective period tuple 计算：commission rate/min 与
slippage 乘 multiplier，stamp/transfer 不变；日期 ISO、Decimal `format(value,"f")`、sorted-key compact JSON、
UTF-8、`allow_nan=false`，然后 SHA-256。它不是 caller hash，也不替代 plan 的全 schedule
`cost_schedule_sha256`。三场景 hash 可不同，三个 plan/facts identity 必须相同。

## 6. Strict metrics：统一 Decimal 后单向 float 投影

所有输入数值先 `Decimal(str(value))`，在固定 80 位、`ROUND_HALF_UP` local context 中计算；count 保持 exact int；
构造 `AShareScenarioMetricsV1` 时才 `float(...)`，所有值必须 finite。公式：

- `n_sessions = nav.height`，精确等于 fresh plan execution dates 数；
- `terminal_equity` 取末日 close equity；`portfolio_return=terminal_equity/initial_cash-1`；
- `annualized_return=(1+portfolio_return) ** (Decimal(annualization_sessions)/n_sessions)-1`；terminal equity 为 0
  特判 `-1`；
- max drawdown 在 close unit NAV 前 prepend Decimal 1，逐点计算 `nav/peak-1` 的最小值；
- benchmark 只用 facts 中 `510300.SH` raw bars，日期键精确覆盖 execution dates，收益为
  `terminal raw close / first execution raw open - 1`；不得用 `000300.SH`、`H00300.CSI`、label 或 adjusted price；
- `test_net_excess_return=portfolio_return-benchmark_return`；
  `relative_wealth=(1+portfolio_return)/(1+benchmark_return)-1`；分母不合法即失败；
- target gross turnover 从首日前完整前权重全 0 开始，按 fresh scheduled target 全域逐日
  `Σ abs(w_t-w_t-1)`；target one-way 为 gross/2；
- realized gross 为 daily diagnostics `gross_turnover` 之和；`test_turnover` 为 daily `one_way_turnover` 之和；
  必须保持 G7E 的 gross/2 口径；
- commission/stamp/transfer/slippage 分别从 trades Decimal 求和；`total_fees` 为前三项和，
  `total_trading_cost=total_fees+slippage`，并与 NAV cumulative fields exact 对账；
- `requested_order_count=Σ daily n_order_intents`；`rejection_count` 是 rejections 中有任一 residual 的唯一
  `(date,symbol,side)` 数，不是 reason 行数；rate=该数/requested，denominator 0 时 null；
- `unfilled_notional=Σ rejection rows rejected_notional`；unexecutable date 是有 rejection 的唯一日期数；
- `cash_rounding_delta_total` 为 posting 中 signed delta 之和；posting count 为 posting rows；
- average cash ratio 为逐 close `cash/equity` 等权均值，每日 equity 必须 positive；
- terminal position value 为末日全部 position MV；pending exit value 只计末日 `pending_exit=true`。

## 7. Terminal estimated 1× exit cost

只作披露，不生成 fill、不改变 cash/NAV/position。对 terminal 每个正持仓：

1. reference price = terminal `mark_price`；quantity = terminal total quantity；使用 terminal date 唯一 **base 1×** period；
2. raw sell price = `mark * (1 - slippage)`；按 `BUY_CEIL_SELL_FLOOR_TICK_V1` 以 `0.01` tick 向下取整；
3. execution price 必须 positive；execution notional = price * quantity；
4. commission/stamp/transfer 对 execution notional 分项 `EACH_COMPONENT_HALF_UP_CENT_V1`；
5. slippage cost = `quantity * (mark - execution_price)`；
6. 全证券估计退出成本 = 三项 fee + slippage cost 的 Decimal 和。

不得使用 `mark_notional * slippage` 粗估、不得套当前 scenario multiplier、不得扣减 NAV、不得模拟 limit/suspension
或强平。全余额卖出含 odd lot，只是成本披露，不声称 terminal 当日可成交。

## 8. 精确目录、文件、manifest 与 root bundle

P0 事务的 expected files 精确为 29 个普通文件：

```text
0p5x/{corporate_action_postings,daily_diagnostics,entitlements,nav,positions,rejections,trades}.parquet
0p5x/metrics.json
0p5x/manifest.json
1p0x/（同九文件）
2p0x/（同九文件）
backtest_metrics.json
backtest_manifest.json
```

每个 scenario 七表必须与 G7E result exact Schema、排序和值一致；空表仍写 canonical Parquet。Parquet 参数固定
`zstd/level=3/statistics=true/row_group_size=65536/use_pyarrow=false`。JSON strict canonical，无 BOM、NaN、重复键、
尾随换行、绝对路径、时间戳、PID 或机器状态。

每个 `BacktestScenarioManifestV1.output_files` 精确 8 项：七表 + metrics，不含 manifest 自身；按 path 排序。
Parquet entry 记录 physical SHA-256、size、包括 0 的 row_count、exact Schema 名；metrics entry row_count=null、
Schema=`AShareScenarioMetricsV1`。manifest identity 全从 fresh bundles/config/facts 投影，rule version 必须等于生产常量。

`BacktestMetricsV1.scenarios` 和 root `scenario_manifest_sha256s` 顺序固定 `0p5x,1p0x,2p0x`。root manifest 的
common target/facts、plan/release/experiment/config identity exact；`backtest_metrics_sha256` 是 root metrics bytes hash。
scenario/root manifest 均不把自身纳入自身 hash。

所有 table/JSON 在写后通过 P0 owned handle readback；表重新 strict read 并与 result exact equals，JSON bytes exact；
最后 `commit(29 exact paths)`，禁止普通 mkdir/write、分场景 commit、partial recovery、overwrite 或 resume。

## 9. Formal verifier、whole-rehash 与 hostile tree

verifier 不信任 caller manifest、metrics、result 或 receipt 自洽。它必须：

1. 对 root、三个 child、29 files 建立 stable physical identity snapshot；拒绝 root/ancestor/child/leaf
   symlink/junction/reparse、hard-link alias、非普通文件、额外/缺失/大小写 alias、深度漂移；
2. 完整执行 §4 fresh 链，重新构造一次 facts 并实际调用 G7E 三次；
3. 以相同 canonical writer 重建七表 bytes，逐文件 byte equality + strict Schema/order/value；空表不可省略；
4. 以 Decimal 重算全部 scenario/root metrics，strict canonical bytes equality；
5. 从实际文件 bytes/stat/row_count 重建三个 manifest 和 root manifest，逐字段与 canonical bytes exact；
6. 复验结束前重查 whole-tree identity，任何 verify 窗口替换失败；
7. 最后验证 receipt exact closure，成功才返回 `VerifiedBacktestArtifact`，root 使用规范绝对 Path，manifest/receipt
   SHA-256 来自实际 bytes。

必须覆盖 wholesale 攻击：同时替换七表、metrics、scenario/root manifests 并重算 caller hashes，甚至 receipt 内部
自洽，仍因 fresh G7E 重放或 exact receipt inputs/outputs 失败。G7E result 是普通值，formal API 没有 caller result
入口；row order 改变、float 微调、空表缺失、schema cast、manifest path/hash 自洽均不得通过。

## 10. Exact backtest receipt 闭包

builder 不写 receipt；StageRunner 在 builder 成功并发布 final root 后用既有 `publish_stage_receipt` 写。verifier 要求：

```text
stage     = backtest
scope     = WORK
scope_key = fresh work_key
```

inputs 精确 21 个普通文件：

```text
target: target_manifest.json, target receipt, target_weights.parquet, target_daily.parquet
plan: manifest.json, plan receipt, scheduled_targets.parquet,
      schedule_diagnostics.parquet, cost_schedule.json
experiment: experiment_manifest.json, experiment receipt
G1: release manifest, G1 receipt,
    bar_1d.parquet, benchmark_bar_1d.parquet,
    corporate_action_ledger.parquet, corporate_action_reconciliation.parquet,
    instrument.parquet, price_limit_1d.parquet, suspension_1d.parquet,
    trade_calendar.parquet
```

outputs 精确为 root 下 29 files。receipt 自身不得进入 inputs/outputs，不允许两个 alias 指向同一物理文件；
parent/child artifact root alias、hard-link、自引用、receipt root 外、missing parent、错误 stage/scope/key、额外或遗漏
任一空表均失败。receipt verifier 必须复算 bytes，不只信 digest 文本。

## 11. 文件白名单

实现 Agent 唯一允许修改/新增：

1. `src/quant/backtest/a_share_reporting.py`；
2. `src/quant/backtest/__init__.py`；
3. `tests/unit/test_m3_g7f_formal_backtest_artifact.py`；
4. `tests/integration/test_m3_g7f_formal_backtest_artifact_golden.py`；
5. `docs/agent/M3_G7F_R1正式A股三场景回测Artifact交付报告.md`。

独立初验 Agent 只可新增 `docs/agent/M3_G7F_R1正式A股三场景回测Artifact独立初验报告.md`；主 Agent 只写最终
验收报告。禁止修改 G7E、P0 helper、G7B/F0/C/D、contracts、schemas、config、receipt/StageRunner、既有测试与
其他文档。禁止联网、真实数据/账户/券商、add/commit/push、删除共享 worktree 内容。

## 12. 必测反例

至少覆盖：

1. 三次 actual G7E call count/order/multiplier；三场景初始状态独立，caller result/fills/transition/schedule 无入口；
2. outer plan/target/experiment/release/context/receipt 混配或在 facts 创建后被替换，fresh 前失败；
3. 0.5/1/2 只缩 commission rate/min/slippage，stamp/transfer exact不变；三个 facts hash 相同；
4. benchmark 只能 510300，首 open/末 close Decimal 手算；缺日、重复、错symbol、adjusted/label 值拒绝；
5. asymmetric turnover 保持 gross/2；target turnover 从全现金权重开始；
6. 一个 intent 两条 residual：rejection rows=2、rejection_count=1、rate<=1；denominator 0 时 null；
7. Decimal annualized/max drawdown/relative wealth/fee/cash ratio 与独立手算；float 先算产生差异的 fixture；
8. terminal exit 以 sell floor tick 后 execution notional 计 fee，最低佣金、odd lot、slippage rounding 反例；粗略
   `mark_notional*slippage` 必须与正确值不同；
9. 每个 scenario 七表含 empty table；29 files exact，scenario output entries=8，manifest self-exclusion；
10. row shuffle、column dtype drift、空表删除、whole-bundle 替换并重算所有 manifests/hashes/receipt；
11. P0 root/child/leaf replacement、并发占名、writer/flush/fsync/readback/commit failure、owned-only rollback；
12. strict JSON duplicate/BOM/CRLF/trailing/NaN/extra field；Parquet bytes/Schema/order drift；
13. receipt 21 inputs/29 outputs exact，hard-link/alias/self-reference/extra/missing；
14. 三证券至少五 session golden 与 G7E 七表一致，三场景 metrics/manifest/root 手算；不要求低成本 NAV 逐日支配。

## 13. 双平台验证

Windows 定向：

```powershell
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_g7f_formal_backtest_artifact.py tests/integration/test_m3_g7f_formal_backtest_artifact_golden.py -q
D:\Miniforge3\python.exe -m ruff check src/quant/backtest/a_share_reporting.py src/quant/backtest/__init__.py tests/unit/test_m3_g7f_formal_backtest_artifact.py tests/integration/test_m3_g7f_formal_backtest_artifact_golden.py
D:\Miniforge3\python.exe -m mypy src/quant/backtest/a_share_reporting.py
```

WSL base 在对应 worktree 运行同一 pytest/Ruff/mypy，并追加 G7E、P0 nested publication、G7B/F0/C/D 定向回归。
若 worktree 实际在 `/mnt/f`/DrvFS，绿色只算兼容证据，不声称 Linux/ext4 Gate。主验按里程碑风险执行：

```bash
/home/mabw/miniforge3/bin/conda run -n base sh -lc 'ruff check src tests && mypy src && pytest -q'
```

Windows 绿不替代 WSL；不得从 WSL 调 Windows conda。测试默认只用最小 formal temp fixture，不联网、不读取
正式数据或真实 receipt。

## 14. 停止条件与外部闭环

以下任一出现立即停止并提交脱敏证据：G7E 或 P0 未主验 PASS；actual G7E/F0/G7B API 漂移；需修改白名单外
production/contracts/schema/config/receipt；P0 不能一次事务提交 29-file nested tree；无法从 fresh plan 取得 target
turnover；必须接 caller result/transition/hash；formal terminal exit 语义需改 F2；无法 Decimal 重算；formal fixture
只能伪 capability；receipt exact集合与真实 artifact path 冲突；需要联网、凭据、真实账户、发布 final 或破坏性操作；
共享 worktree 出现白名单重叠写入。

闭环固定：主 Agent 冻结 → 全新外部实现 Agent → 未参与实现的全新外部独立初验 Agent并增加 whole-bundle/
nested hostile 反例 → 失败返工并重新独立复验 → 主 Agent fresh、三回放、Decimal、29-file transaction、21/29 receipt、
双平台与全量回归终验。只有主 Agent 最终 PASS 才能标记 G7F 完成；这不自动等于 Linux/ext4 Gate、完整 G7 或 M3
PASS。

## 15. Formal 测试的模块化来源边界裁决（2026-08-10）

实现首轮证实：现有 `test_m3_formal_backtest_plan_artifact._context` 中的 `VerifiedG1Release` 被上游 target
测试 helper 改写为 development manifest 与 `SimpleNamespace` release，不能被 actual F0 loader 消费；仓库没有
可复用的 retained formal G1→G7B bundle。重新运行完整300成分 G1→G7B链已在G7E阶段证明超过600秒，把30成分
伪装成formal又会被权威G1合同正确拒绝。禁止伪造capability、patch私有issuer或把development release当formal。

G7F测试因此沿用已由F0、G7B、G7E分别主验的模块边界：

1. production builder/verifier仍必须调用其真实import的public plan verifier、F0 loader与actual G7E三次；public API、
   exact type与全字段比对不得放宽；
2. G7F unit/golden可在G7F模块import边界mock public plan verifier与public F0 loader，返回现有G7E §13 fixture构造的
   exact plan与exact、内容绑定且可由public property重验的F0 capability；同时按G7E §13只在G7E模块import边界
   mock其public plan verifier。G7E账户、G7C、F1/F2不得mock，三次actual G7E必须真实执行；
3. 正向必须分别断言G7F public plan verifier与F0 loader exact一次、actual G7E exact三次及参数/顺序；另测
   nonexact/hostile/stale返回在任何P0输出前拒绝。不得mock G7F指标、terminal exit、manifest、receipt或P0；
4. G7B、F0、G7E、P0各自现有formal套件必须作为邻接回归；报告必须明确G7F fixture不重复证明完整G1来源，
   不得把模块化fixture表述为真实formal release；
5. 继续仅使用两个G7F测试文件，不新增support长链，不读取正式artifact或联网。若此边界仍不能使actual G7E三次、
   29-file事务与21-input receipt完整运行，立即停止回主Agent，不进一步弱化。

## 16. R1 独立初验 reload 顺序污染 R2 返工（2026-08-10）

### 16.1 现象、根因与裁决

R1 独立初验的强制邻接153项为`148 passed / 5 failed`；最小顺序为先运行
`test_m3_corporate_actions.py::test_corporate_action_core_import_does_not_load_qlib`，再运行G7E formal正向，稳定
`1 passed / 1 failed`。单跑G7E通过。

前一节点在pytest已收集并导入G7E simulator后，对`quant.backtest.corporate_actions`执行原地
`importlib.reload`。reload在同一module dict中创建新enum/state/transition identity；simulator保留reload前通过
`from ... import ...`取得的旧identity，而旧函数的globals已指向新identity，生产者与消费者分裂后被formal exact
边界正确拒绝。

R2裁决为tests-only隔离：把该cold-import/reload检查完整移入fresh subprocess，主pytest进程不得reload会被其他
已收集consumer使用的production module。禁止放宽G7C/G7E exact type、issuer、phase、fresh或reload旧capability
拒绝语义；G7F production与两个G7F测试保持不变。

### 16.2 白名单、测试与通过条件

R2唯一新增修改范围：

1. `tests/unit/test_m3_corporate_actions.py`：将cold-import/reload节点改为fresh subprocess，并在子进程内保留原
   `qlib/lightgbm/mlflow`未加载、public surface与reload旧/new capability边界断言；
2. 任务状态与唯一`M3_G7F_R2_corporateReload测试隔离返工交付报告.md`。

生产`corporate_actions.py`、`a_share_simulator.py`、G7F production/tests及其他上游文件SHA必须保持不变。新增或
明确执行固定顺序：cold-import节点→G7E正向/hostile Decimal/golden，Windows与WSL base均PASS；同一进程153项
必须`153 passed`，不得通过排除节点、改顺序或把整套拆进程掩盖；G7F双平台10项、Ruff/mypy/cold/diff保持绿色。
返工后由未参与R2的全新独立上下文复验；PASS只解锁主验，不等于G8、ext4或M3 Gate。

## 17. R3：正式 G1 `quality.json` 来源闭包与路径类型分离

### 17.1 现象、根因和权威规则

当前 formal G7F 21-input 仍通过 `BacktestArtifactUpstreamPaths.g1_receipt_path` 引用正式 G1 root 下不存在的
`receipt.json`，并尝试绑定 `VerifiedG1Release.receipt_sha256`。该值对象同时服务 development，导致 formal 与
development 信任域无法在类型边界 exact 隔离。权威规则以 `docs/M3实施与Agent交接.md` §4.8、G7A R3 和
G7B R2 主验结论为准：正式 G1 使用 manifest + quality + 八张 market facts；development 继续使用其真实 receipt。

### 17.2 冻结公共类型与 21-input

1. 保留现有 `BacktestArtifactUpstreamPaths` 作为 development-only 四路径值对象，不改 development API/语义。
2. 新增并安全导出 exact `@dataclass(frozen=True) FormalBacktestArtifactUpstreamPaths`，只含
   `target_receipt_path`、`plan_receipt_path`、`experiment_receipt_path` 三个 `Path`；exact type、绝对化/去重规则
   与现有窄值对象一致，不允许 caller 传 G1 path。
3. `BacktestArtifactFreshVerificationContext.upstream_paths` exact 改为 formal 三路径类型；formal G1 quality path
   只能从 exact `VerifiedG1Release.release.quality_path` 派生，caller 不得覆盖。
4. formal 21-input 保持数量和其余顺序不变：target 4；plan 5；experiment 2；G1 manifest、G1 quality、八张
   market facts共10。即第13项从伪 G1 receipt 改为 exact quality；不得新增或删除其他项。
5. formal identity、stable bytes、receipt path/digest、public `backtest_artifact_input_paths`、pre/final tree verifier、
   builder/verifier whole-replay 必须共享同一来源闭包；quality bytes绑定 `release.quality_sha256`，path精确为
   `release.root/quality.json`，拒绝 missing/drift/alias/root replacement。不得从 G7A/G7B import 私有 helper。
6. development `_receipt_inputs`/`_validate_upstream_receipts` 保持 `g1_receipt_path` 与 development
   `receipt_sha256`；不得改 G1、G7A/G7B、G7E、P0、Schema、metrics、29 outputs、publication 或错误码。

### 17.3 必测与兼容边界

- formal positive fixture 不得创建或依赖 fake G1 receipt；断言 21 inputs 的第12/13项为 manifest/quality，八表随后。
- quality 与 target/plan/experiment receipt、任一 market table 的 hardlink/samefile alias；根外 quality path；
  missing/drift quality；same-bytes G1 whole-root replacement；旧伪 receipt 整包合法重签，均必须 fail closed。
- `BacktestArtifactUpstreamPaths` 传入 formal fresh context、formal type传入 development API、subclass/duck/dict
  必须在读取路径或发布前拒绝；development正向与receipt继续通过。
- G7F whole-bundle合法重签、三次actual G7E、Decimal/terminal exit、29-file P0事务与R2 fixed-order回归保持绿。
- G8当前构造旧 formal context 必然需要后续同步；本包不得修改G8。报告须明确G8暂停，不能通过兼容接受旧类型。

### 17.4 本轮白名单与验证

- `src/quant/backtest/a_share_reporting.py`
- `src/quant/backtest/__init__.py` 仅新增 formal 类型安全导出
- `tests/unit/test_m3_g7f_formal_backtest_artifact.py`
- `tests/integration/test_m3_g7f_formal_backtest_artifact_golden.py`
- 本任务单状态
- 唯一交付报告 `docs/agent/M3_G7F_R3_正式G1Quality来源闭包与路径类型分离交付报告.md`
- 唯一独立复验报告 `docs/agent/M3_G7F_R3_正式G1Quality来源闭包与路径类型分离独立复验报告.md`

Windows/WSL base 至少运行 G7F 10项、G7E/P0/G7B R2/F0-C-D 邻接（排除尚未同步的G8）、R2 fixed-order、
Ruff、mypy、cold import、scoped diff-check。WSL `/mnt/f` 仅 DrvFS 兼容。实现与独立初验必须使用不同的全新
外部 Cursor Agent；独立初验新增未用反例并只写指定报告。R3 初验与主验 PASS 后才解锁 G8 同步返工。

## 18. R4：pre-final G1 Release 来源与实体绑定

### 18.1 现象—根因—规则—最小复现

- 现象：合法 G7F tree 构造后，把 outer `VerifiedG1Release.release/artifact_paths` 重映射到 same-bytes copied root，
  `verify_backtest_build_output` 可重建相同内容并通过；nested `release.release=SimpleNamespace` 也未被拒绝。
- 根因：`BacktestArtifactFreshVerificationContext` 不绑定 build-time release；formal identity 只验外层 nominal type、
  portable hash与当前 bytes，pre-final 又没有 receipt path set 可证明原 G1 root。
- 应遵循规则：§17.2.5/17.3 要求 build、pre-final、final 共享同一来源闭包并拒绝 same-bytes G1 root replacement；
  exact formal input 必须递归到 nested `G1Release/G1ManifestV5/G1QualityReportV1`，不能只验外层 dataclass。
- 最小复现：独立报告补充 S1（SimpleNamespace nested）与 S2（public `G1Release` + public
  `replace(VerifiedG1Release)` 指向 copied root）均使 pre-final unexpected pass。
- 通过条件：使用**同一 fresh context**时，S1/S2 在读取29输出或回放G7E前稳定拒绝且cause/context为空；原合法
  build→pre-final→receipt→final仍通过。新建另一 context 表示新的验证请求，不在本包声明跨请求持久来源证明。

### 18.2 精确实现合同

1. `BacktestArtifactFreshVerificationContext` 新增 exact `release: VerifiedG1Release`，并在构造时递归验证 nested
   exact `G1Release`、`G1ManifestV5`、`G1QualityReportV1`、17项artifact paths，以及 root/manifest/quality/八张
   formal market table 的受控路径与普通文件实体。允许增加 `init=False/repr=False/compare=False` 的私有不可序列化
   source snapshot，但不得新增公开 mint/key/registry。
2. 每个 formal public入口在任何29-output读取、G7E回放或写入前必须：递归 exact 验 caller release；逐字段/路径
   exact等于 `fresh_context.release`；重算并比较 context 构造时的 root/manifest/quality/八表实体 snapshot；再执行
   原有 G7B/F0/G7E fresh 与21-input bytes闭包。same bytes不同inode、copied root、nested drift均拒绝。
3. context本身被 `object.__setattr__`/`dataclasses.replace` 漂移 release或私有snapshot时也必须拒绝；`__reduce__`
   继续拒绝。不得把平台inode写进 portable manifest/receipt/hash或输出。
4. development 类型/API不变；不得改G1/G7A/B/E/P0/G8、21/29数量、metrics、publication、stable error。

### 18.3 白名单与验证

白名单沿用R3：`a_share_reporting.py`、必要`backtest/__init__.py`、两个G7F测试、本任务状态；唯一R4交付报告
`M3_G7F_R4_preFinalReleaseContext实体绑定返工交付报告.md`与唯一独立复验报告。必须新增正式 S1/S2、同路径换
inode、context release/snapshot漂移、合法控制；Windows/WSL运行 G7F、排除G8邻接、R2 fixed-order、Ruff/mypy/
cold/diff。外部实现与独立初验仍须使用不同全新会话；R4 主验 PASS 前不得解锁G8。
