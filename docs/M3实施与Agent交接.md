# M3 Qlib/LightGBM 实施与 Agent 交接

状态（2026-08-02）：正式 Windows G1 已完成 INDEX→HISTORY→REFERENCE→PREPARE→PUBLISH，发布
`release_id=08eb9b31…`、manifest `d3923fa1…`；独立磁盘 `verify_g1_release` 正在后台执行，通过前仍不把
Windows G1 Gate 标记为最终关闭，且 Windows 结果不替代 Linux/ext4 Gate。隔离 development/example 路径已完成
G2B、G2C、G3A、G3B、G4A，并通过 G4B parent/fresh-worker/receipt 阶段验收；development 结果不升级为
formal verified artifact，也不关闭真实 Qlib、正式 G2–G9 或性能 Gate。后续以正式 G1 磁盘验收→正式 G2A，
以及 development G4C 为两条互不阻塞的推进线。
当前验收与返工顺序见 [`M3当前验收与返工总览.md`](M3当前验收与返工总览.md)。
本文是 **M3 实现契约的 SSOT**；技术选型理由仍以
[`../A股港股通个人量化投研交易系统调研.md`](../A股港股通个人量化投研交易系统调研.md)
为准，里程碑状态以 [`../项目实施路线图.md`](../项目实施路线图.md) 为准。
当前 D1–D8 的执行范围和禁止事项见 [`M3另一个Agent任务单.md`](archive/M3另一个Agent任务单.md)。

## 1. 本阶段要交付什么

M3 的最终闭环是：

```text
clean PIT 数据
  -> 不可变数据快照与 manifest
  -> Qlib provider 数据
  -> Alpha158 特征
  -> LightGBM 滚动训练/预测
  -> prediction_score 标准契约
  -> 无状态 Top-k 目标权重
  -> 项目统一回测器
  -> 样本外报告 + MLflow 记录
```

M3 研究运行本身不在线下载行情；G1 是独立执行、先审计后发布的前置数据 release 流程。M3 不直接
使用券商接口，也不允许使用 Qlib 自带回测结果替代项目统一回测器。
所有稳定产物必须能由一个版本化 TOML 配置和一个不可变数据快照复现。

## 2. 已冻结的架构决策

### 2.1 Qlib 的位置

Qlib 只承担以下职责：

1. 从 provider 读取日频 OHLCV/factor；
2. 计算 Alpha158；
3. 组织 `DatasetH` 的 train/valid/test 数据段；
4. 调用其 LightGBM 模型适配器或提供等价的训练矩阵。

Qlib 不承担：

- clean 数据 SSOT；
- 股票池 PIT 资格判断；
- 标签时间语义的最终定义；
- 最终目标权重契约；
- A 股/港股通市场规则、费用和成交模拟；
- MLflow 元数据 SSOT。

Qlib 官方 `dump_bin.py` 可以读取 Parquet **作为导入源**，随后仍生成 calendar、instrument 和
feature `.bin` provider；这不等于 LocalProvider 能直接挂载本项目的 clean Parquet。因此 M3
采用“clean Parquet -> 每证券 staging Parquet -> Qlib bin provider”的单向导出，不实现依赖
Qlib 内部类的自定义 Parquet Provider。

### 2.2 数据和标签

- 首个基线市场：A 股；股票池固定为
  `CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1`，不得使用今天的 300 只股票回看历史。该名称刻意标明
  Tushare 月度观察与构建版本，不能把它宣称为指数公司逐日精确成分事件。
- `data.source` 是必需配置；首个基线固定为 `tushare`。readiness、staging、manifest 和
  provider 必须使用同一 source，不得在任一环节自动选源或混源。
- 特征时点：交易日 `t` 收盘后可知的 Alpha158。
- 最早成交：`t+1` 开盘。
- `h` 日证券理论标签：
  `(close(t+h) * adj_factor(t+h)) / (open(t+1) * adj_factor(t+1)) - 1`；因子比例消除任意归一化
  基准并修正分红送转。Schema 中历史字段名 `raw_return` 表示“减基准之前的证券收益”，不是
  “未复权价格收益”。
- excess 标签：上述证券总回报减去已批准的 `510300.SH` ETF HFQ 总回报代理同一
  `open(t+1) -> close(t+h)` 区间收益；基准不套用个股复权因子，也不得与价格指数
  `000300.SH` 或旧设计的 `H00300.CSI` 序列混用。
- daily open 是理论收益代理：部分时段停牌或一字涨停时未必可成交。训练标签不读取执行状态、不宣称
  能按该价格成交；最终统一回测必须用真实停牌/涨跌停规则检验可实现收益。
- 首轮分别训练 `h=5` 与 `h=10` 两个模型，不把两个 horizon 混成同一个训练样本。
- 标签的 `available_as_of` 不得早于 `return_end_date`；train/validation 分别使用 PlannedFold 冻结的
  embargo 末日 cutoff，详见 4.4，不再错误地统一截到 segment end。
- 训练/验证与验证/测试之间使用至少 `max(horizons)=10` 个交易日 embargo，防止标签跨段。

基准行情由 `BenchmarkBar1dSchema` 定义，固定字段为
`benchmark,trade_date,open,high,low,close,source,source_snapshot_id`；它不是可交易证券，不得伪装成
`Bar1dSchema` 的普通证券行情。`ForwardReturnLabelSchema.benchmark` 允许受控基准代码；当前首个 M3
配置和正式 G1 只允许用户批准的 `510300.SH`。

标准表由 `ForwardReturnLabelSchema` 和 `PredictionScoreSchema` 定义。任何 Qlib 特有 MultiIndex
或列名必须在适配器出口转换，不能泄漏到 `quant.strategies`。

### 2.3 复权与字段

Qlib provider 每只证券至少包含：

| 字段 | 含义 |
|---|---|
| `open/high/low/close` | 同一累计因子处理后的价格，供 Alpha158 横纵向计算 |
| `vwap` | `amount / volume` 推导并使用同一价格因子调整；官方 Alpha158 的必需输入 |
| `volume` | 股；按复权语义调整与否必须与 Qlib 基线约定一致并写入 manifest |
| `factor` | 当日累计复权因子 |

本项目 clean `bar_1d` 的权威语义是：不复权 OHLC、原始成交量（股）和累计后复权
`adj_factor`，研究价格为 `raw_price * adj_factor`。Qlib 官方数据约定则要求价格和成交量
都已调整，且 `factor = adjusted_price / original_price`；官方 Yahoo 日频归一化器对价格乘
factor、对 volume 除 factor，再以首个有效收盘价归一化。因此 M3 staging 冻结为以下
逐证券确定性公式：

```text
normalization_base = first_valid_raw_close * first_valid_adj_factor
qlib_factor        = adj_factor / normalization_base
qlib_ohlc          = raw_ohlc * qlib_factor
raw_vwap           = raw_amount / raw_volume
qlib_vwap          = raw_vwap * qlib_factor
qlib_volume        = raw_volume / qlib_factor
```

这使每只证券首个有效收盘为 `1.0`，并保持 `qlib_ohlc / qlib_factor = raw_ohlc`。
`normalization_base`、上述公式版本和 clean 原始单位必须写入 manifest。不允许直接把
clean `adj_factor` 改名为 Qlib `factor` 而保留未调整 OHLC/volume。

Qlib 0.9.7 的 `Alpha158.get_feature_config()` 明确包含 `VWAP0`，滚动特征也读取 `$vwap`。
因此首版不得通过删掉 VWAP 把 158 维基线悄悄变成其他特征集。staging 行要求
`volume > 0`、`amount > 0` 且二者 finite；停牌无成交日不补零、不前向填充，也不输出伪造 VWAP。
`vwap`、OHLC 和 factor 必须满足 `vwap / factor = amount / volume`，该关系进入 G2 回读对账。

账户成交和最终回测仍读取不复权 `bar_1d`。Qlib 特征价格不得进入账户核算。导出前必须拒绝：

- 同证券同日重复；
- 不属于目标 universe **历史成分并集**的证券；provider 必须保留并集证券在整个 history window 的
  连续行情，包括首次调入前、两次成员区间之间和调出后的回看数据；
- OHLC、amount、volume 或因子非正/非 finite；
- OHLC 复权方法不一致；
- 交易日不在 SH/SZ 开市日历；
- 请求证券在区间内整段缺失；
- 数据源未经显式选择而混合。

### 2.4 可复现性

- LightGBM：CPU、固定 seed、`deterministic=true`、`force_col_wise=true`；参数见
  `configs/research/m3_qlib_example.toml`。
- 同一 snapshot、配置、依赖锁和代码版本运行两次，预测分数逐行绝对误差不得超过 `1e-12`，
  报告指标误差不得超过 `1e-12`。
- snapshot ID 是 manifest 规范化 JSON 的 SHA-256；manifest 内再记录所有输入文件的相对路径、
  大小、SHA-256、数据源、最小/最大日期、行数和 Schema 版本。
- 排序固定为 `as_of, score DESC, symbol ASC`；分数相同时按 symbol 打破平局，rank 从 1 开始。
- 禁止把 wall-clock 时间、绝对工作区路径或无序字典写入哈希输入。

### 2.5 MLflow

- 单机使用 SQLite backend：配置项 `tracking.tracking_uri`。
- SQLite 只保存 run 元数据；较大产物写入 `artifacts/research/m3/runs/<experiment_key>/` 后作为 artifact
  登记。
- 每个 run 必须记录：配置文件、配置哈希、snapshot manifest/ID、可验证代码版本、依赖版本、fold、
  horizon、模型参数、随机种子、指标和全部预测。没有有效 Git metadata 时使用规范化 source tree
  hash，禁止写固定 `unavailable`。
- 不能只依赖 MLflow 内部 artifact 路径；标准 Parquet/JSON 产物必须在项目 artifact 目录可直接读。

## 3. 稳定目录与模块边界

```text
configs/research/m3_qlib_example.toml       # M3 参数 SSOT
src/quant/domain/schemas.py                 # label/prediction/target 契约 SSOT
src/quant/research/m3/config.py             # TOML 严格加载、规范化与分层 hash
src/quant/research/m3/contracts.py          # 无重依赖值对象
src/quant/research/m3/readiness.py          # 数据与运行时就绪审计
src/quant/research/m3/snapshot.py           # clean -> staging + manifest
src/quant/research/m3/provider.py           # dump 子进程、结构检查与 probe 计划
src/quant/research/m3/labels.py             # 独立标签计算与 Qlib 标签对账
src/quant/research/m3/folds.py              # 交易日滚动切分 + embargo
src/quant/research/m3/features.py           # Alpha158 parent、strict manifest/verifier
src/quant/research/m3/alignment.py          # 监督对齐与无标签 inference loader
src/quant/research/m3/qlib_adapter.py       # 唯一允许 import qlib 的模块
src/quant/research/m3/model.py              # 唯一允许 import lightgbm 的模块
src/quant/research/m3/predictions.py        # prediction 排序、manifest 与唯一键
src/quant/research/m3/targets.py            # prediction/资格 -> 完整目标 batch
src/quant/backtest/a_share_plan.py          # 目标调度、窗口与历史成本日程
src/quant/backtest/corporate_actions.py     # entitlement 捕获/确认/结算
src/quant/backtest/a_share_execution.py     # open state、订单、T+1 与离散现金分配
src/quant/backtest/a_share_simulator.py     # A 股逐 session 账户循环
src/quant/backtest/a_share_reporting.py     # 三场景 artifact、指标与 verifier
src/quant/research/m3/run_state.py           # identity 与跨 root stage receipt
src/quant/research/m3/tracking.py            # 唯一允许 import mlflow 的模块
src/quant/research/m3/evaluate.py            # IC/ICIR、覆盖率、稳定性
src/quant/research/m3/quality_gate.py        # 固定质量命令与可审计证据
src/quant/research/m3/acceptance.py          # G0–G9 跨 Gate 最终审计
src/quant/research/run_m3.py                 # CLI 编排，不放稳定算法
src/quant/data/index_membership.py            # 月度观察快照 -> 保守 PIT 区间
src/quant/data/m3_backfill.py                 # G1 请求计划、断点续跑、质量和 clean release
src/quant/data/m3_mappers.py                  # Verified Tushare response -> G1 标准映射
src/quant/strategies/ml_topk.py              # prediction -> target_weight 纯函数策略
data/clean/m3_g1/releases/<release_id>/       # G1 不可变 clean release
artifacts/research/m3/snapshots/<id>/        # manifest 与 staging；不可追加 provider
artifacts/research/m3/providers/<id>/        # Qlib bin provider 与回读证据
artifacts/research/m3/runs/<experiment_key>/ # work 级 predictions、targets、报告、模型
```

`qlib_adapter.py`、`model.py` 和 `tracking.py` 必须延迟导入重依赖；导入 `quant.domain`、
`quant.strategies`、`quant.backtest` 时不得要求安装 Qlib/LightGBM/MLflow。

## 4. 函数级接口

下面签名可以增加仅限 keyword-only 的可选诊断参数，不得改变输入/输出主语义。

### 4.0 `config.py`

M3 的 TOML 只允许由本模块读取一次；其他模块接收 `LoadedM3Config` 或其中的只读 section，不得再次
打开 TOML、补默认值或自行维护 hash allowlist。

```python
@dataclass(frozen=True)
class ConfigIssue:
    code: str
    dotted_path: str
    message: str

class M3ConfigError(ValueError):
    issues: tuple[ConfigIssue, ...]

@dataclass(frozen=True)
class LoadedM3Config:
    document: Mapping[str, object]
    config_version: str
    full_config_sha256: str
    g1_config_sha256: str
    snapshot_config_sha256: str
    provider_config_sha256: str
    scientific_config_sha256: str
    provider_validation_config_sha256: str
    label_reconciliation_config_sha256: str
    acceptance_config_sha256: str
    canonical_tracking_uri: str
    tracking_target_key: str

    def section(self, name: str) -> Mapping[str, object]: ...

def load_m3_config(path: Path) -> LoadedM3Config: ...

ConfigSelector = Literal[
    "full", "g1", "snapshot", "provider", "scientific",
    "provider-validation", "label-reconciliation", "acceptance",
]

def canonical_config_sha256(
    *, selector: ConfigSelector, document: Mapping[str, object],
) -> str: ...

def canonical_tracking_target_key(
    *, tracking_uri: str, experiment_name: str,
) -> str: ...
```

允许的根 section 固定为 `meta,data,runtime,features,labels,g1_backfill,walk_forward,model,portfolio,
backtest,evaluation,validation,costs,tracking,acceptance`；嵌套键以版本化示例 TOML 和本节规则为准。所有当前示例键
均必需，唯一允许缺省的是最后一个费用 period 的 `effective_to`。未知根/嵌套键、缺键、错误 TOML 类型、
空字符串、非 finite 浮点和 TOML datetime/time 一次收集为按 `(dotted_path,code,message)` 稳定排序的
`M3ConfigError`；不得在创建 artifact、初始化 Qlib/MLflow 或联网之后才报配置错误。

跨字段验证至少包括：日期域有序；horizon 非空、唯一、升序且 M3 固定为 5/10；embargo 不小于最大
horizon；step 不小于 test 且 M3 固定无重叠；provider/required fields 与冻结 staging 契约一致；
`top_k/max_weight/cash_buffer` 可形成合法多头组合；coverage 比例在 `[0,1]`，IC 最小证券数不小于 2，
复现容差非负；费用 period 有序、按自然日连续且最后一期无 `effective_to`，从而覆盖未知的尾随/成交日期；三个 friction multiplier 精确为
`0.5/1.0/2.0`；三组标签容差非负且 finite，并满足
`qlib_expression_atol <= label_return_atol`、`benchmark_return_atol <= label_return_atol`。
`walk_forward.train_sessions >= data.minimum_train_sessions`，`g1_backfill.label_tail_sessions >=
max(labels.horizons_sessions)`，且 `portfolio.top_k <= data.minimum_cross_section_symbols <=
g1_backfill.expected_constituent_count`。`cash_buffer` 是最低现金保留，不是必须精确达到的现金比例；即使
`top_k * max_weight < 1-cash_buffer` 也合法，策略按容量保留更多现金。`tracking_uri` 不允许内嵌用户名、密码、token 或绝对工作区路径；任何层级的键和值出现
凭据模式都失败。加载器不读取 `configs/tushare.local.toml`，两类配置不可合并。

规范化 hash 使用 UTF-8、键排序、紧凑 JSON、ISO date、保留数组顺序并拒绝 NaN/Infinity；TOML 注释、
空白和键书写顺序不得改变 hash。分层边界冻结如下：

- `scientific_config_sha256`：只含 `runtime.qlib.version`、完整 `data`、`features,labels,walk_forward,
  model.lightgbm,evaluation,portfolio,backtest.a_share,costs`；不含 dump URL/hash/bytes、supported-python
  readiness policy、tracking、artifact 根、acceptance 阈值和注释。experiment 另绑定 provider receipt 与实际
  dependency fingerprint，不重复供应链定位信息。
- `g1_config_sha256`：含 `g1_backfill` 除
  `request_rate_per_minute/max_attempts/retry_base_seconds` 外的全部字段；它进入 G1 release
  identity/manifest，不进入 M3 snapshot/provider/experiment identity。三个排除项只控制执行可靠性，不改变
  目标数据或质量口径，因此只改变 full hash。request ID 仍只由 endpoint 与规范参数决定；G1 release
  必须因请求规划、截断门禁或对账政策变化而形成新身份。
- `snapshot_config_sha256`：只含 `data.universe/benchmark/source/start_date/end_date/market/frequency/
  minimum_train_sessions/minimum_cross_section_symbols/required_fields/snapshot_hash` 与
  `g1_backfill.feature_warmup_sessions/label_tail_sessions`；这些字段实际参与 readiness/staging/date domain。
  provider 字段或
  dump tool 变化不得伪造新 snapshot request。
- `provider_config_sha256`：只含 `data.market/frequency/provider_fields/provider_format`。Qlib version、实际
  runtime fingerprint 与 dump tool SHA 已分别进入 `compute_provider_key`，不得在本 hash 重复拼接 URL/hash/
  bytes、code、dependency 或 snapshot ID。
- `provider_validation_config_sha256`：只含 `validation.provider`；抽样改变失效 provider-validation、所有
  显式绑定其 receipt 的 label-reconciliation 与 acceptance，不重建 snapshot/provider/experiment/features/
  work identity。provider-validation PASS 是后续编排前置门禁，但不是 experiment/features 内容 receipt 输入。
- `label_reconciliation_config_sha256`：只含 `validation.labels`；标签对账算法/容差改变只失效对应
  label-reconciliation 与 acceptance，不重建 snapshot/provider/experiment 或 provider validation。
- `acceptance_config_sha256`：只含 `acceptance`；阈值改变不改变科学 experiment，但必须形成新的验收身份。
- `tracking_target_key`：只 hash 规范化 tracking URI 与 experiment name，不保存 URI 明文；其变化不改变
  snapshot/provider/experiment/work。

`full_config_sha256` 用于本地诊断，不进入科学 identity。上述九类配置身份/target key（full、G1、snapshot、
provider、scientific、provider-validation、label-reconciliation、acceptance、tracking）全部使用同一套
规范序列化。所有分层 selector 路径、hash envelope 常量和 canonicalizer 只能在
`config.py` 定义；readiness、run-state、编排、追踪和验收必须复用，禁止复制 dotted-path 集合。
`canonical_config_sha256` 接收完整且已验证的 document，并在函数内部按 selector 投影；禁止调用者预切
payload，否则 G1 排除纯运行字段等规则会再次分叉。公开函数对 direct caller 仍先执行同一闭包
validate/normalize；partial、extra、版本不匹配或非规范值必须抛 `M3ConfigError`，不能为任意 mapping 签名。
loader 内部可在一次验证后调用私有的 trusted helper，避免重复八次全量校验，但不得暴露该 helper。

#### 4.0.1 字段、类型与 selector 闭包

`full` 覆盖全部键；下表的 “derived selector” 只列 full 之外的直接归属。`G/S/P/C/PV/LR/A/T` 分别表示
G1/snapshot/provider/scientific/provider-validation/label-reconciliation/acceptance/tracking-target。

| Dotted keys | 严格类型与当前版本约束 | Derived selector |
|---|---|---|
| `meta.config_version/purpose/enabled` | string/string/bool；version 必须精确为 `1.0.0`，purpose 非空；`enabled=false` 是合法可加载配置但运行 Gate 必须失败 | version 作为 G/S/P/C/PV/LR/A hash namespace；其余无 |
| `data.universe/benchmark/source/market/frequency/provider_format/snapshot_hash` | 非空 string；当前分别固定为示例值；source 仅 `tushare` | universe/benchmark/source/market/frequency/snapshot_hash → S+C；market/frequency/provider_format → P；provider_format → C |
| `data.start_date/end_date` | `datetime.date`，start≤end；拒绝 datetime/time；两端是信号域边界并须由 G1 日历证明为 SH session，不自动对齐；修正后示例为 `2016-01-04/2026-06-26` | S+C |
| `data.minimum_train_sessions/minimum_cross_section_symbols` | int 且非 bool，分别 `>0`、`>=2` | S+C |
| `data.required_fields/provider_fields` | tuple[str]；精确等于示例的有序唯一列表，不静默排序 | required → S+C；provider → P+C |
| `runtime.qlib.version/supported_python` | string；固定 `0.9.7` 与 `>=3.8,<3.13` | version → C，并单独进入最终 provider key；supported policy 无 derived config hash |
| `runtime.qlib.dump_script_url/sha256/bytes` | HTTPS URL、裸 64 hex、正 int；精确匹配固定供应链 spec | 无 derived config hash；实际 tool SHA 单独进入 provider key |
| `features.*` | handler/policy/version strings 固定示例；feature count 正 int且=158；coverage 是 `[0,1]` float | C |
| `labels.*` | horizons 精确 `(5,10)`；offset 正 int且=1；entry/exit/version strings 与 relative bool 固定示例 | C |
| `g1_backfill` 业务核心键 | code/version/source strings 固定示例；expected count=`300`、membership warmup=`1`、feature warmup=`60`；label tail 正 int且>=最大 horizon | 全部 → G；feature warmup + label tail 另 → S |
| `g1_backfill.request_rate_per_minute/max_attempts/retry_base_seconds` | 前两者正 int 且非 bool，retry 是 finite 非负 float | 仅 full；它们是运行政策，不改变 request/release 身份 |
| `g1_backfill.endpoint_row_limits.*` | 七个精确键与冻结值：daily/adj_factor=`6000`，index_daily/index_weight/suspend_d/dividend=`5000`，stk_limit=`5800`；int 且非 bool | G |
| `g1_backfill.reconciliation.*` 与 `corporate_action_reconciliation.*` | source 固定；sample symbols/dates=`30/20`；atol/rtol/rate 是 finite 非负 float，mismatch rate≤1；factor ratio rtol 另须≤0.01 | G |
| `walk_forward.*` | 五个 session 数是正 int；selection/test policy 固定示例；另满足 embargo/step/完整 fold 不变量 | C |
| `model.lightgbm.*` | string/bool/int/float 类型精确；固定 CPU/deterministic/force-column；learning rate>0，fractions∈(0,1]，bagging freq≥0，leaves≥2，depth=-1或正数，rounds/early-stop/threads正且early-stop<rounds，min-delta≥0，全部 seed 为非负 int 且非 bool | C |
| `portfolio.*` | strategy/version/rebalance 固定；top_k 正 int；cash_buffer∈[0,1)，max_weight∈(0,1]，并满足可行性 | C |
| `backtest.a_share.*` | initial cash/tick 为正 float；6 个 policy string 与 2 个 bool 分别固定示例；friction tuple 精确 `(0.5,1.0,2.0)` | C |
| `evaluation.minimum_ic_symbols` | int 且非 bool，>=2 | C |
| `validation.provider.*` | sample symbols/dates/gaps 精确 `3/20/5`；policy 固定示例 | PV |
| `validation.labels.*` | version 固定；三个 atol 是 finite 非负 float并满足容差层级 | LR |
| `costs` header 与 periods | version/HTTPS source/scaled-components 固定；period 是非空 tuple[mapping]，日期连续不重叠；commission_rate/min、stamp_tax_sell、transfer_fee、slippage 五项均须 exact finite nonnegative float；最后 effective_to 必须缺省 | C |
| `tracking.experiment_name/tracking_uri` | name 非空；URI 仅允许规范相对 SQLite 或无 userinfo/query/fragment 的 HTTP(S) | T |
| `tracking.artifact_root/log_*` | root 是项目内相对 POSIX 路径，无 `..`；三个 flags 当前必须为 true | 无；request/artifact digest 决定 tracking key |
| `acceptance.*` | 两个 reproducibility atol、五个 coverage 阈值为 finite 非负 float，coverage≤1；required metrics 是精确有序唯一 tuple | A |

数值类型不宽松转换：bool 不能充当 int，int 不能充当 float，字符串数字也非法。所有 float 拒绝 NaN/
Infinity；`-0.0` 规范化为 `0.0`。数组原顺序参与 hash，因此对语义为集合的字段直接要求示例中的唯一固定
顺序，不能在 loader 中偷偷排序。

当前 `1.0.0` 示例含 151 个 assignment；将 `costs.a_share_periods[<index>]` 归一为
`costs.a_share_periods[]` 后有 138 种 dotted-key shape。`config.py` 的唯一 `_FIELD_SPECS` 必须与这 138 种
shape 精确相等；每个 spec 明确 required/optional、严格 TOML 类型、literal/值域与 G/S/P/C/PV/LR/A/T
归属。唯一 optional shape 是 `costs.a_share_periods[].effective_to`，且只允许末期缺省。测试从真实示例
枚举闭包，漏 spec、多 spec 或 wildcard 吞键均失败；不能另写第二份测试 allowlist。

变化传播验证分为两类：当前版本允许合法变化的字段，必须用公开 loader/canonicalizer 对两份完整
有效文档运行时比较 hash；被 `1.0.0` 冻结为唯一 literal 的字段，必须同时证明变体被公开 API
拒绝、且该 field spec 的 selector 归属正确。禁止为了构造无效文档的 hash 测试而放宽 literal，
或把跳过验证的 trusted helper 暴露给生产调用方。如需让冻结字段成为可配置量，必须先升级
`config_version` 并同步所有消费者。

#### 4.0.2 规范 hash 与 URI

除 tracking target 外，每个 derived hash（包括 full 与 G1）输入固定为：

```text
{"hash_version":"m3-config-hash-v1","selector":"<name>",
 "config_version":"1.0.0","payload":<selected read-only subtree>}
```

再按 UTF-8、键排序、紧凑 JSON、ISO date 求裸 SHA-256。selector name 必须进入输入，避免两个不同身份
恰因 payload 相同而混用。散落字段按原始 section 层级重建最小 nested mapping，不展平成 dotted-key map；
section/array 顺序语义沿用已验证 document。实现固定使用 `json.dumps(..., ensure_ascii=False,
sort_keys=True, separators=(",", ":"), allow_nan=False)` 的 UTF-8 字节；date 先转 ISO 字符串，`-0.0` 先转
`0.0`。`full` 使用同一 envelope 和完整规范化 document。tracking target 不绑定 config version，
输入只含 `hash_version,selector="tracking-target",canonical_tracking_uri,experiment_name`。
`canonical_tracking_target_key` 自身必须执行与 loader 相同的 URI/name 校验和规范化；不能假定 direct caller
已清洗，也不能接受原 URI 与自报 canonical URI 两份可冲突输入。

相对 SQLite URI 以 workspace root 为运行期解析基准，但 hash 中保留规范逻辑 URI，不写绝对路径；HTTP(S)
URI 将 scheme/host 小写、去默认端口、规范 path，拒绝 userinfo、query、fragment、凭据和 `.`/`..` 路径段。
错误不得回显原 URI。loader 将 document 中的 `tracking_uri` 替换为同一规范逻辑 URI，并通过
`canonical_tracking_uri` 明确暴露；调用方不得恢复使用原始拼写。切换 URI 只改变 T 和 full，不改变科学
identity。

#### 4.0.3 错误与不可变对象

错误 code 只允许：`CONFIG_IO_ERROR,TOML_PARSE_ERROR,UNKNOWN_KEY,MISSING_KEY,TYPE_ERROR,EMPTY_STRING,NON_FINITE,
VALUE_ERROR,CROSS_FIELD_ERROR,SECRET_VALUE,UNSAFE_PATH,UNSAFE_URI`。dotted path 对 array table 使用
`costs.a_share_periods[0].commission_rate` 形式；message 只描述期望，不回显原值、URI、token 或绝对路径。
配置文件不存在、不是普通文件、不可读或解码失败统一为不含物理路径的 `CONFIG_IO_ERROR`；TOML parser
异常不得直接拼接进 message，避免回显原始值。除文件/TOML 无法解析外，应一次收集全部可独立判断的
问题并稳定排序。

成功 document 递归转换为 `MappingProxyType`、tuple 和不可变标量；任何深度的 mapping/array 不可修改。
hash selectors 只读取该对象，不能重新 parse TOML。`LoadedM3Config` 还应提供只读 `section(name)` helper，
未知 section 失败，禁止各调用方用 `.get(default)` 恢复隐式默认。

#### 4.0.4 凭据、路径与 URI 的机械规则

安全检查先于 unknown-key 丢弃，并对 percent-decoding 后的文本再检查；unknown secret key 可同时产生
`UNKNOWN_KEY` 与 `SECRET_VALUE`。敏感键 segment 规范为小写并把 `-` 换成 `_` 后，至少拒绝
`token,api_key,apikey,secret,password,passwd,authorization,cookie,credential,private_key`。字符串值拒绝
控制字符，以及大小写不敏感的 `Bearer <value>`、`token=...`、`api[_-]?key=...`、`password=...`、
`secret=...` 或 `sk-...` 形式；不能用“任意长 hex 都是 secret”的规则误杀冻结的 dump SHA。错误只记录
dotted path 与期望类别，不记录命中的片段。

非 URL 字符串若形如 POSIX 绝对路径、Windows drive/UNC 路径或包含反斜杠路径分隔，返回
`UNSAFE_PATH`。`artifact_root` 只接受非空、相对、规范 POSIX path segment；不得含空 segment、`.`、`..`、
percent-encoded separator/dot segment。相对 SQLite URI 只接受 `sqlite:///<relative-posix-path>`，第四个
slash 即绝对路径并拒绝；HTTP(S) URI 必须有 host，scheme/host 小写、默认端口移除、空 path 规范为 `/`，
拒绝 userinfo、query、fragment、反斜杠、控制字符以及 decoded `.`/`..` segment。当前首版 URI path
一律不接受 percent encoding；HTTP path 除根 `/` 外还拒绝重复 `/` 与尾 `/`，不做可能改变服务端语义的
自动折叠。`%2f/%5c/%2e` 等绕过必须失败。host case 与 `:80/:443` 默认端口是唯一要求归一为同一
HTTP(S) target key 的别名。所有路径的真实 root containment
和 no-symlink 检查仍由 StageRunner/发布器在解析 workspace root 后执行，C0 不凭逻辑字符串声称物理安全。

### 4.1 `readiness.py`

```python
@dataclass(frozen=True)
class ReadinessIssue:
    code: str
    severity: Literal["ERROR", "WARNING"]
    message: str

def audit_m3_readiness(
    *,
    bars: pl.DataFrame,
    instruments: pl.DataFrame,
    membership: pl.DataFrame,
    calendars: pl.DataFrame,
    benchmark_bars: pl.DataFrame,
    config: Mapping[str, Any],
) -> list[ReadinessIssue]: ...
```

必须检查：字段契约、PIT 成员覆盖、基准覆盖、交易日覆盖、复权因子覆盖、最少训练长度、最小截面
证券数、horizon/embargo、Qlib 可导入性和 Python 版本。存在任何 `ERROR` 时 CLI 退出非零且不写
provider/model。

就绪口径冻结如下：

- 只检查 `data.start_date..data.end_date` 内的 SH 开市日，不得用配置区间外日历凑训练长度；
- “有效行情”是已选数据源中 OHLC、volume、adj_factor 完整且合法的唯一行；
- 先依 `data.source` 过滤 bars 和 benchmark bars，再执行重复键、finite、覆盖和截面检查；
  请求源不存在时返回 `DATA_SOURCE_MISSING`；
- 股票 bars 与 benchmark bars 是两种契约。基准精确使用 `BenchmarkBar1dSchema`，不得要求
  `symbol/volume/amount/adj_factor` 或调用股票 factor helper；M3 v1 benchmark 只允许
  `510300.SH`，重复键为 `(benchmark,trade_date,source)`；
- 每个开市日都对当日生效的 PIT 成员做稠密计数，有效证券数低于
  `minimum_cross_section_symbols` 的任意日期都产生 `CROSS_SECTION_TOO_SMALL`；不得以最大日
  截面代替逐日检查；
- “可训练 session”同时满足：截面达标、基准当日有效、日历开市；
  `minimum_train_sessions` 只对此计数；
- PIT 覆盖还必须拒绝“某一成员在其整个生效区间没有任何有效行情”；
- 缺少前置字段时先记录结构化 `ERROR`，然后跳过依赖该字段的检查；审计函数
  本身不得因输入契约错误而崩溃。

### 4.2 `snapshot.py`、`provider.py` 与 provider contracts

本节的现行实施颗粒度、verified bundle、fresh-worker 协议和五段外部闭环以
[`M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md`](agent/M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md)
为准；旧任务书合并 P0–P4 的方式不再执行。G2A 只能消费 `VerifiedG1Release`，G2B/G2C 只能消费
`VerifiedSnapshotArtifact/VerifiedProviderArtifact`，不得回退裸 path/DataFrame 加自报 hash。
本节所有消费 `*_config_sha256` 的 plan/build/verify 函数同时接收同一严格 `LoadedM3Config`，并在任何 I/O
或 worker 前调用 C0 唯一 selector 重算对应 narrow hash；只检查 hex 或相信 spec/manifest 自报值不构成验真。
完整配置不写入产物，也不因此污染窄 identity。

```python
class SnapshotSessionCalendarSchema(pa.DataFrameModel):
    date: pl.Date

def prepare_qlib_staging(
    *, release: VerifiedG1Release,
    history_start: dt.date, history_end: dt.date,
) -> pl.DataFrame: ...

def to_qlib_symbol(symbol: str) -> str: ...
def from_qlib_symbol(instrument: str) -> str: ...

def write_staging_by_symbol(
    *, frame: pl.DataFrame, output_dir: Path,
) -> tuple[Path, ...]: ...

def build_snapshot_session_calendar(
    *, release: VerifiedG1Release,
    history_start: dt.date, history_end: dt.date,
) -> pl.DataFrame: ...

@dataclass(frozen=True)
class SnapshotBuildSpec:
    snapshot_request_key: str
    config_version: str
    snapshot_config_sha256: str
    code_version: str
    history_start: dt.date
    history_end: dt.date
    staging_schema_version: str
    adjustment_formula_version: Literal["qlib_yahoo_like_v1"]

@dataclass(frozen=True)
class SnapshotRequestRecordV1:
    schema_version: Literal["m3-snapshot-request-v1"]
    snapshot_request_key: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    snapshot_config_sha256: str
    code_version: str
    history_start: dt.date
    history_end: dt.date
    signal_start: dt.date
    signal_end: dt.date

@dataclass(frozen=True)
class SnapshotArtifactEntryV1:
    path: str
    sha256: str
    size_bytes: int
    row_count: int
    schema_name: str
    symbol: str | None
    min_date: dt.date
    max_date: dt.date

@dataclass(frozen=True)
class SnapshotManifestV1:
    schema_version: Literal["m3-snapshot-manifest-v1"]
    snapshot_id: str
    config_version: str
    snapshot_config_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    source: Literal["tushare"]
    universe: Literal["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"]
    history_start: dt.date
    history_end: dt.date
    signal_start: dt.date
    signal_end: dt.date
    row_count: int
    symbol_count: int
    min_date: dt.date
    max_date: dt.date
    session_calendar_sha256: str
    session_count: int
    session_start: dt.date
    session_end: dt.date
    staging_format: Literal["parquet"]
    staging_schema_version: str
    adjustment_formula_version: Literal["qlib_yahoo_like_v1"]
    adjustment_spec_sha256: str
    files: tuple[SnapshotArtifactEntryV1, ...]

@dataclass(frozen=True)
class SnapshotBuildResult:
    root: Path
    manifest: SnapshotManifestV1
    manifest_sha256: str

@dataclass(frozen=True)
class VerifiedSnapshotArtifact:
    root: Path
    request: SnapshotRequestRecordV1
    request_sha256: str
    manifest: SnapshotManifestV1
    manifest_sha256: str
    snapshot_receipt_sha256: str
    session_calendar_path: Path
    staging_paths: tuple[Path, ...]

def build_snapshot_artifact(
    *, release: VerifiedG1Release, config: LoadedM3Config,
    spec: SnapshotBuildSpec,
    output_root: Path,
) -> SnapshotBuildResult: ...

def build_snapshot_request_record(
    *, release: VerifiedG1Release, config: LoadedM3Config,
    spec: SnapshotBuildSpec,
    result: SnapshotBuildResult,
) -> SnapshotRequestRecordV1: ...

def read_snapshot_manifest(path: Path) -> SnapshotManifestV1: ...
def read_snapshot_request_record(path: Path) -> SnapshotRequestRecordV1: ...

def verify_snapshot_artifact(
    *, snapshot_root: Path, snapshot_request_path: Path,
    snapshot_receipt_path: Path, release: VerifiedG1Release,
    config: LoadedM3Config, spec: SnapshotBuildSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedSnapshotArtifact: ...

@dataclass(frozen=True)
class QlibDumpToolSpec:
    url: str
    sha256: str
    size_bytes: int
    qlib_version: Literal["0.9.7"]
    command: Literal["dump_all"]

def build_qlib_dump_tool_spec(config: LoadedM3Config) -> QlibDumpToolSpec: ...

def ensure_qlib_dump_tool(
    *, spec: QlibDumpToolSpec, target_path: Path,
) -> Path: ...

@dataclass(frozen=True)
class ProviderRuntimeFingerprint:
    python_version: str
    packages: tuple[tuple[str, str], ...]
    sha256: str

@dataclass(frozen=True)
class ProviderBuildSpec:
    snapshot_id: str
    snapshot_manifest_sha256: str
    provider_key: str
    provider_config_sha256: str
    dump_tool: QlibDumpToolSpec
    qlib_version: Literal["0.9.7"]
    code_version: str
    runtime_fingerprint: ProviderRuntimeFingerprint
    fields: tuple[str, ...]
    frequency: Literal["day"]
    dump_contract_version: Literal["m3-qlib-dump-all-v1"]

@dataclass(frozen=True)
class ProviderManifestV1:
    schema_version: Literal["m3-provider-manifest-v1"]
    provider_key: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    provider_config_sha256: str
    qlib_version: str
    dump_tool_sha256: str
    dump_tool_bytes: int
    dump_contract_version: str
    provider_runtime_fingerprint_sha256: str
    code_version: str
    frequency: Literal["day"]
    fields: tuple[str, ...]
    storage_dtype: Literal["<f4"]
    calendar_sha256: str
    calendar_count: int
    calendar_start: dt.date
    calendar_end: dt.date
    instrument_count: int
    instrument_ranges_sha256: str
    output_tree_sha256: str
    logical_argv: tuple[str, ...]
    files: tuple[ArtifactDigest, ...]

@dataclass(frozen=True)
class ProviderBuildResult:
    root: Path
    qlib_dir: Path
    manifest: ProviderManifestV1
    manifest_sha256: str

@dataclass(frozen=True)
class VerifiedProviderArtifact:
    root: Path
    qlib_dir: Path
    manifest: ProviderManifestV1
    manifest_sha256: str
    provider_receipt_sha256: str

def read_provider_manifest(path: Path) -> ProviderManifestV1: ...

def materialize_qlib_provider(
    *, snapshot: VerifiedSnapshotArtifact, qlib_dump_script: Path,
    python_executable: Path, config: LoadedM3Config,
    spec: ProviderBuildSpec,
    output_root: Path, timeout_seconds: float,
) -> ProviderBuildResult: ...

@dataclass(frozen=True)
class ProviderValidationSpec:
    provider_validation_key: str
    provider_validation_config_sha256: str
    code_version: str
    qlib_version: Literal["0.9.7"]
    sampling_policy_version: Literal["provider_market_stratified_hash_first_last_v1"]
    worker_protocol_version: Literal["m3-qlib-worker-v1"]

@dataclass(frozen=True)
class ProviderProbePlan:
    schema_version: Literal["m3-provider-probe-v1"]
    provider_validation_key: str
    provider_key: str
    snapshot_id: str
    sampling_policy_version: Literal["provider_market_stratified_hash_first_last_v1"]
    candidate_keys_sha256: str
    selected_rows: tuple[tuple[str, dt.date], ...]
    selected_gap_rows: tuple[tuple[str, dt.date], ...]
    emitted_keys_sha256: str
    gap_keys_sha256: str

@dataclass(frozen=True)
class ProviderValidationSummaryV1:
    schema_version: Literal["m3-provider-validation-v1"]
    provider_validation_key: str
    provider_key: str
    provider_receipt_sha256: str
    provider_manifest_sha256: str
    snapshot_id: str
    provider_validation_config_sha256: str
    provider_runtime_fingerprint_sha256: str
    qlib_version: str
    sampling_policy_version: str
    worker_protocol_version: str
    probe_plan_sha256: str
    candidate_keys_sha256: str
    emitted_keys_sha256: str
    gap_keys_sha256: str
    emitted_key_count: int
    gap_key_count: int
    emitted_comparison_count: int
    gap_comparison_count: int
    details_sha256: str
    details_row_count: int
    api_calendar_sha256: str
    api_instrument_ranges_sha256: str
    missing_emitted_cell_count: int
    extra_cell_count: int
    duplicate_cell_count: int
    non_finite_emitted_cell_count: int
    emitted_mismatch_cell_count: int
    gap_finite_cell_count: int
    calendar_mismatch_count: int
    instrument_mismatch_count: int
    provider_uri_sha256: str
    parent_import_audit_sha256: str
    read_audit_sha256: str
    passed: bool

@dataclass(frozen=True)
class ProviderValidationResult:
    details: pl.DataFrame
    summary: ProviderValidationSummaryV1

@dataclass(frozen=True)
class VerifiedProviderValidationArtifact:
    root: Path
    details: pl.DataFrame
    summary: ProviderValidationSummaryV1
    summary_sha256: str
    validation_receipt_sha256: str

def read_provider_validation_summary(path: Path) -> ProviderValidationSummaryV1: ...

def inspect_provider_structure(
    *, qlib_dir: Path, snapshot: VerifiedSnapshotArtifact,
    spec: ProviderBuildSpec,
) -> ProviderManifestV1: ...

def plan_provider_probe(
    *, snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec,
) -> ProviderProbePlan: ...

def validate_provider_public_api(
    *, snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    probe_plan: ProviderProbePlan, config: LoadedM3Config,
    spec: ProviderValidationSpec,
    python_executable: Path, output_root: Path,
    timeout_seconds: float,
) -> ProviderValidationResult: ...

def verify_provider_artifact(
    *, provider_root: Path, provider_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact,
    config: LoadedM3Config, artifact_roots: Mapping[str, Path],
) -> VerifiedProviderArtifact: ...

def verify_provider_validation_artifact(
    *, validation_root: Path, validation_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedProviderValidationArtifact: ...
```

validation verifier 必须接收已经冻结的 `ProviderValidationSpec`，用它独立重算 formal/development key 和
完整 deterministic probe；不得从 details 自报 keys 反构造“期望计划”。无 `spec` 的旧签名不能证明
`provider_validation_key`，已经废止。

输出 staging 列固定为 `symbol,date,open,high,low,close,vwap,volume,factor`，每证券一个 Parquet，日期
升序。必须先按 `source` 过滤 bars，按 `universe` 过滤 membership 并取得历史 symbol 并集，再用该
并集过滤 bars；**不得**按 membership effective interval 删除行情。重复键必须拒绝。交易日域统一使用 SH session
calendar，不得把 SH/SZ 开市日做并集。finite 检查在选源后执行；OHLC/amount/volume/factor 任一
null、NaN 或正负 infinity 都必须拒绝，
且 emitted row 的 amount/volume 均须为正。`to_qlib_symbol`/`from_qlib_symbol` 是项目与 Qlib 证券代码
互转的唯一 SSOT，必须互为逆函数并支持 Qlib 返回的大小写形式。
`SnapshotSessionCalendarSchema` 的唯一定义位于 `quant.domain.schemas`，严格只有非空、唯一、严格升序的
单列 `date: pl.Date`；不保存 `is_connect_open/is_half_day`，避免与 SH session 无关的字段改变 provider。
snapshot 必须发布 `session_calendar.parquet`：它由通过 `TradeCalendarSchema` 的权威日历中过滤
`market="SH"`、`is_open=true` 和显式 `[history_start,history_end]` 得到，日期唯一且严格递增；其日期域来自
G1 release/config 的 warmup 至 label tail 请求，不从 staging 的实际日期并集反推。发布 snapshot 前，全部
staging 日期并集必须与该权威 session 列表完全一致；若某个权威开市日所有证券都缺行，snapshot 直接失败，
不得让 dump 工具静默删掉该日。

manifest 顶层字段精确以 `SnapshotManifestV1` 为准，其中业务字段包含
`source,universe,g1_release_id,g1_release_manifest_sha256,snapshot_config_sha256,config_version,row_count,
symbol_count,min_date,max_date,history_start,history_end,signal_start,signal_end,session_calendar_sha256,session_count,
schema_version,staging_format,adjustment_formula_version,adjustment_spec_sha256`；`staging_format` 固定为 `parquet`，不得把下游 `provider_format`
写进 snapshot，
每个数据文件条目至少包含相对路径、大小、SHA-256、symbol、行数和最小/最大日期。
manifest 不再读取或 hash 整份 TOML；否则只改 tracking URI 也会伪造新 snapshot。调用者只能传入 C0
已验证的 narrow `snapshot_config_sha256`，函数校验 64 位小写 hex。`config_path` 旧签名废止。

G1 manifest 必须公开 `signal_start/signal_end/history_start/history_end`。snapshot spec 的 history 首尾只能
与其中 `history_start/history_end` 精确相等；不得在保持 `snapshot_config_sha256` 和 request key 不变时由
caller 另传窗口。snapshot manifest 和 `SnapshotRequestRecordV1` 的 `signal_start/signal_end` 也必须从该
verified G1 manifest 投影，不接受 caller 另传。request record 是 request key 到内容 `snapshot_id` 的唯一严格映射，其
request/hash/G1/config/code/date 字段全部重算；它不进入 snapshot manifest 的内容 ID。snapshot temp 的
Parquet 写参数固定为 zstd level 3、statistics 开启、row group 65536、Polars native writer。

`snapshot.py` 到此为止，不 import Qlib、不启动 dump。`QlibDumpToolSpec` 唯一定义在 `contracts.py`；
`fetch_qlib_tool.build_qlib_dump_tool_spec` 从 C0 已验证的扁平字段
`runtime.qlib.dump_script_url/dump_script_sha256/dump_script_bytes/version` 显式映射并固定
`command="dump_all"`。`ensure_qlib_dump_tool` 不解析 TOML，只接收该 spec；现有
`fetch_qlib_tool.py` 中第二个 TOML reader 必须删除。
`provider.py` 负责标准库子进程与结构检查；只有
`qlib_adapter.py` 的 fresh worker 入口可以 import Qlib。`materialize_qlib_provider` 只接受 StageRunner 分配的空临时
output dir，以参数数组和 `shell=False` 调用**当前 WSL base 的同一 Python**：

```text
<python> <pinned dump_bin.py> dump_all
  --data_path <staging> --qlib_dir <stage-temp>/provider --freq day
  --file_suffix .parquet --date_field_name date --symbol_field_name symbol
  --include_fields open,high,low,close,vwap,volume,factor --max_workers 1
```

最终物理布局唯一为 `providers/<provider_key>/provider/{calendars,instruments,features}` 与同级
`provider_manifest.json`；validation 位于
`providers/<provider_key>/provider-validation/key=<provider_validation_key>/`。`--qlib_dir` 永远指向
stage temp 的 `provider/` 子目录。manifest 的 `files` 只列该子目录内普通文件，不列 manifest、receipt 或
validation，避免自引用。

禁止 `dump_fix/dump_update/limit_nums/backup_dir`、非空 output、shell、隐式默认 fields 或调用者提供任意
额外 argv。运行前重新校验脚本 URL 对应的固定 bytes/SHA、snapshot manifest 和全部 staging digest；
运行后无论 exit code 是否为 0 都执行结构验真。官方脚本会把值写成 little-endian float32、按全局 calendar
对证券起止区间 reindex，并会自行 drop duplicate date，因此上游仍须先拒绝重复，不能依赖脚本“修复”。

materializer 在任何副作用前重算 runtime fingerprint hash、要求 tool spec 与运行时 Qlib version 一致，并
调用 E3 唯一 `compute_provider_key` 重算 `spec.provider_key`；调用者自报 key/version/hash 不一致即失败。
provider runtime fingerprint 精确记录当前 Python、NumPy、pandas、PyArrow、Qlib、Fire、tqdm 和 Loguru
版本；这些包任一变化必须改变 provider key。只改变 LightGBM 不改变 provider；完整 dependency
fingerprint 仍进入 experiment。provider manifest 使用稳定 schema version，记录 snapshot/provider/config/
tool/code/runtime identities、逻辑 argv、calendar/instrument 摘要及所有生成普通文件的相对路径/大小/hash，
不记录绝对路径、wall-clock、PID 或非确定性 stdout。manifest 的稳定逻辑 argv 固定为
`<PYTHON> <DUMP_TOOL> dump_all --data_path <SNAPSHOT_STAGING> --qlib_dir <PROVIDER_TEMP>/provider ...`；
真实绝对 argv 只传 subprocess，不落盘。

`inspect_provider_structure` 不 import Qlib，严格验证：`calendars/day.txt` 等于 snapshot 发布的权威
`session_calendar.parquet` 且升序
唯一；`instruments/all.txt` 恰为 staging symbol 集及各自 min/max；每个 symbol 只有七个
`<field>.day.bin`，无额外 symbol/field；bin 首 float32 是正确 calendar offset，字节数等于该证券全局
calendar 起止跨度的 `4*(1+n)`，实际 staging 日期有限值、缺口位置 NaN。所有 symlink 和未声明文件失败。

正式 G1 长时 I/O 期间允许使用 development example 轨做工程反馈，但必须保持独立信任域：开发 Provider
materializer 只接受 `VerifiedDevelopmentExampleSnapshotArtifact` 并返回与正式路径同形的未发布
`ProviderBuildResult`；只有开发最终 verifier 返回
`VerifiedDevelopmentExampleProviderArtifact(release_kind="development_example",
formal_gate_eligible=False, example_id=...)`；identity 使用带固定 domain tag 和 `example_id` 的
`compute_development_provider_key`，receipt stage 固定为 `development-provider`，输出根名必须同时显式包含
`development` 与 `example`。正式 `materialize_qlib_provider/verify_provider_artifact` 只接受精确
`VerifiedSnapshotArtifact`，不得用 union、包装或重命名把开发对象提升为 `VerifiedProviderArtifact`。开发轨
复用同一个 `ProviderManifestV1`、七字段 bin 格式和静态 inspector，仅证明开发契约、跨平台兼容和编排恢复；
不证明正式 G2B/G2C、真实数据覆盖/性能或任何 Gate。开发 fixture 固定为 21 个连续 SH session；
`000001.SZ` 因一个全日停牌输出 20 行，另两证券各输出 21 行，同时保留公司行动/复权和退市生命周期边界。
因此开发轨可原样运行下述 G2C `3×20×7` sampling policy，不放宽正式规则。开发 G2C 另用
`compute_development_provider_validation_key` 的固定 domain tag/`example_id`、
`development-provider-validation` receipt stage 和开发专用 nominal verified 类型闭合；正式入口仍精确拒绝
开发类型。该结果只证明 development example 的 fresh-process 公共 API、确定性抽样和跨平台工程契约，
不提升为正式 `VerifiedProviderValidationArtifact`。

probe 不是随机数调用：策略固定为 `provider_market_stratified_hash_first_last_v1`，先按
规范 JSON 数组 `["provider-symbol-v1",snapshot_id,provider_key,symbol]` 的 SHA-256 各选 1 个 SH/SZ，再选
剩余最低 hash 证券；每证券必须至少 20 个 staging 行，日期包含首尾并以
`["provider-date-v1",provider_key,symbol,date]` 的规范数组 hash 选 18 个内部日期。另每证券最多选 5 个
区间内 staging 缺口，gap 排名固定使用规范数组
`["provider-gap-date-v1",provider_key,symbol,date]`。禁止直接字符串拼接。
最终 emitted 样本恰为 3 证券×20 日期，共 60 keys/420 field comparisons；gap 是另外的 0–15 keys/
0–105 comparisons。两类计数在 summary 分开记录。通过 fresh Python/Qlib API 回读；值必须等于 staging 值转
little-endian float32 后的结果并比较 UInt32 bit pattern。gap 的 API row 缺失或显式 NaN 都合法并分别记录，
任何 finite gap 值失败。calendar/instrument 也通过 Qlib API 全量核对。
不足 3 证券、任一市场缺失、某样本不足 20 日、Qlib 不可导入、版本/identity 不符或任一差异都失败，
不得退化为少量 sample。PID 只允许父进程测试 spy 实时观察，不写持久产物；持久 summary 记录 worker
protocol version、fresh-process enforced、provider URI hash、runtime hash 与 parent import/read audit。
details 和 summary 分别发布 `provider_validation.parquet/json`；严格 reader 拒绝未知/缺失字段、duplicate
JSON key、NaN 和宽松数字转换。details 对 gap 的 NaN 规范化为 nullable null，并保留 `api_row_present/status`；
summary 必须绑定完整 probe/details/API 摘要并重算 missing/extra/duplicate/non-finite/mismatch/gap-filled/
calendar/instrument 八类计数，不能只有 caller 自报 `passed`。

### 4.3 `labels.py`

G3A/G3B 分包同样以
[`M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md`](agent/M3_G2_G3快照Provider标签分包骨架与外部闭环任务单.md)
为现行执行入口。标签 artifact 额外绑定直接输入 `bars_sha256` 与 experiment manifest；G3B 只接收 verified
G1/snapshot/provider/provider-validation/label bundle，并在 fresh worker 前关闭所有混配。G3B 发布后必须由
`verify_label_reconciliation_artifact` 重建 `VerifiedLabelReconciliationArtifact`；G9 不接受裸 summary 或
caller 自报 reconciliation receipt hash。

```python
@dataclass(frozen=True)
class LabelBuildResult:
    labels: pl.DataFrame
    diagnostics: pl.DataFrame

@dataclass(frozen=True)
class ExperimentIdentityManifestV1:
    schema_version: Literal["m3-experiment-identity-v1"]
    experiment_key: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    provider_key: str
    provider_manifest_sha256: str
    provider_receipt_sha256: str
    scientific_config_sha256: str
    dependency_fingerprint_sha256: str
    code_version: str

@dataclass(frozen=True)
class ExperimentIdentitySpec:
    scientific_config_sha256: str
    dependency_fingerprint_sha256: str
    code_version: str

@dataclass(frozen=True)
class VerifiedExperimentIdentity:
    root: Path
    manifest: ExperimentIdentityManifestV1
    manifest_sha256: str
    experiment_receipt_sha256: str

def read_experiment_identity_manifest(path: Path) -> ExperimentIdentityManifestV1: ...

def verify_experiment_identity(
    *, experiment_root: Path, experiment_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact, provider: VerifiedProviderArtifact,
    config: LoadedM3Config, spec: ExperimentIdentitySpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedExperimentIdentity: ...

@dataclass(frozen=True)
class LabelBuildSpec:
    experiment_key: str
    experiment_manifest_sha256: str
    horizon_sessions: Literal[5, 10]
    benchmark: Literal["510300.SH"]
    label_version: str
    label_build_code_version: str

@dataclass(frozen=True)
class LabelArtifactManifest:
    schema_version: Literal["m3-label-artifact-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    horizon_sessions: int
    benchmark: str
    label_version: str
    label_build_code_version: str
    eligible_keys_sha256: str
    bars_sha256: str
    session_calendar_sha256: str
    benchmark_bars_sha256: str
    labels_sha256: str
    labels_row_count: int
    label_key_sha256: str
    diagnostics_sha256: str
    diagnostics_row_count: int
    diagnostic_key_sha256: str
    candidate_count: int
    success_count: int
    diagnostic_count: int

@dataclass(frozen=True)
class VerifiedLabelArtifact:
    root: Path
    labels: pl.DataFrame
    diagnostics: pl.DataFrame
    manifest: LabelArtifactManifest
    manifest_sha256: str
    label_receipt_sha256: str

def build_label_artifact(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, experiment_spec: ExperimentIdentitySpec,
    spec: LabelBuildSpec, output_root: Path,
) -> LabelArtifactManifest: ...

def read_label_artifact_manifest(path: Path) -> LabelArtifactManifest: ...

def verify_label_artifact(
    *, label_root: Path, label_receipt_path: Path,
    release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, experiment_spec: ExperimentIdentitySpec,
    spec: LabelBuildSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedLabelArtifact: ...

def compute_forward_relative_labels(
    *,
    bars: pl.DataFrame,
    benchmark_bars: pl.DataFrame,
    eligible_keys: pl.DataFrame,
    calendars: pl.DataFrame,
    horizons: Sequence[int],
    benchmark: str,
    label_version: str,
) -> LabelBuildResult: ...

@dataclass(frozen=True)
class LabelReconciliationSummaryV1:
    schema_version: Literal["m3-label-reconciliation-v1"]
    reconciliation_key: str
    experiment_key: str
    horizon_sessions: int
    provider_validation_receipt_sha256: str
    label_manifest_sha256: str
    label_reconciliation_config_sha256: str
    dependency_fingerprint_sha256: str
    code_version: str
    worker_protocol_version: str
    qlib_version: str
    qlib_expression: str
    details_sha256: str
    row_count: int
    row_key_sha256: str
    missing_key_count: int
    extra_key_count: int
    duplicate_key_count: int
    non_finite_count: int
    expression_direct_max_abs_error: float
    expression_direct_p99_abs_error: float
    benchmark_max_abs_error: float
    benchmark_p99_abs_error: float
    raw_label_max_abs_error: float
    raw_label_p99_abs_error: float
    relative_label_max_abs_error: float
    relative_label_p99_abs_error: float
    qlib_expression_atol: float
    benchmark_return_atol: float
    label_return_atol: float
    passed: bool

@dataclass(frozen=True)
class LabelReconciliationResult:
    details: pl.DataFrame
    summary: LabelReconciliationSummaryV1

@dataclass(frozen=True)
class VerifiedLabelReconciliationArtifact:
    root: Path
    details: pl.DataFrame
    summary: LabelReconciliationSummaryV1
    summary_sha256: str
    reconciliation_receipt_sha256: str

@dataclass(frozen=True)
class LabelReconciliationSpec:
    reconciliation_key: str
    experiment_key: str
    horizon_sessions: Literal[5, 10]
    provider_validation_receipt_sha256: str
    label_manifest_sha256: str
    label_reconciliation_config_sha256: str
    dependency_fingerprint_sha256: str
    code_version: str
    worker_protocol_version: Literal["m3-qlib-worker-v1"]
    qlib_version: Literal["0.9.7"]
    qlib_expression_atol: float
    benchmark_return_atol: float
    label_return_atol: float

@dataclass(frozen=True)
class LabelReconciliationReceiptPaths:
    snapshot_receipt_path: Path
    provider_receipt_path: Path
    provider_validation_receipt_path: Path
    experiment_receipt_path: Path
    label_receipt_path: Path

def read_label_reconciliation_summary(path: Path) -> LabelReconciliationSummaryV1: ...

def verify_label_reconciliation_artifact(
    *, reconciliation_root: Path, reconciliation_receipt_path: Path,
    release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity,
    provider: VerifiedProviderArtifact,
    provider_validation: VerifiedProviderValidationArtifact,
    labels: VerifiedLabelArtifact,
    config: LoadedM3Config, spec: LabelReconciliationSpec,
    receipt_paths: LabelReconciliationReceiptPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedLabelReconciliationArtifact: ...

def reconcile_labels_with_qlib(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity,
    provider: VerifiedProviderArtifact,
    provider_validation: VerifiedProviderValidationArtifact,
    labels: VerifiedLabelArtifact, config: LoadedM3Config,
    spec: LabelReconciliationSpec,
    receipt_paths: LabelReconciliationReceiptPaths,
    artifact_roots: Mapping[str, Path],
    python_executable: Path, output_root: Path,
    timeout_seconds: float,
) -> LabelReconciliationResult: ...
```

G3B 不从目录扫描或按 hash 猜上游 receipt。formal/development reconcile 与 verifier 都显式接收五条
`LabelReconciliationReceiptPaths` 和完整 `artifact_roots`，并在启动 worker 前通过共享
`verify_stage_receipt_with_bytes` 核对 receipt bytes、stage/scope/scope_key、nominal SHA 与 root registry。
reconciliation receipt 的输入闭包精确为：experiment receipt+manifest；G1 manifest+benchmark；snapshot
receipt+manifest+session calendar；provider receipt+manifest+严格完整 provider tree；provider-validation
receipt+summary+details；label receipt+manifest+labels+diagnostics。输出严格只有
`reconciliation.parquet,reconciliation.json`。

development 路径必须使用独立 development nominal/key/API/stage，key 绑定 development domain tag 与
`example_id`，输出根名同时含 development/example，且 `formal_gate_eligible=False`；formal exact-type
入口拒绝 development nominal。worker 的 request/echo 完整绑定 config、dependency、code version，并在
import Qlib 前重算 row-key 与逻辑 provider URI hash。summary 的 `row_count` 是实际 details 行数；与
missing/extra/duplicate 三个计数及 verified label manifest 的 success count 共同证明期望/匹配行数闭包，
不再另设含义重叠的 expected/matched 字段。`non_finite_count` 固定为六个数值输入槽位的非 finite/缺失
cell 数；`-0.0` 的逻辑摘要规范化为 `0.0`。

返回值必须通过 `ForwardReturnLabelSchema`。不得用自然日位移；所有偏移基于对应市场开市日序号。
`calendars` 必须先通过 `TradeCalendarSchema`；过滤 SH 后日期仍须唯一、严格递增，重复 session 不能被 sort/
dict 静默合并或当作两个交易日。对任何成功样本，`return_end_date` 不得早于 `return_start_date`；`h=1`
表示同一下一 session 的 open-to-close，允许两日期相等，只有 `h>1` 时 end 才必须严格晚于 start。M3 v1
生产配置仍只允许 h=5/10。
尾部没有完整 horizon 的样本直接不输出。证券 entry/exit 两端都必须有正且 finite 的 adj_factor；
停牌缺价不得补值。需要以含除权事件的手算 fixture 对账，再与 Qlib 调整后价格表达式逐行对账。

`eligible_keys` 是样本候选 SSOT；不得遍历历史成分并集后把非成员日期也计为缺失。diagnostics 固定列为
`as_of,horizon_sessions,reason,sample_count`，reason 至少包括：`TAIL_INCOMPLETE`、
`BENCHMARK_ENTRY_MISSING`、`BENCHMARK_EXIT_MISSING`、`ASSET_ENTRY_BAR_MISSING`、
`ASSET_EXIT_BAR_MISSING`、`ASSET_ENTRY_FACTOR_INVALID`、`ASSET_EXIT_FACTOR_INVALID`。同一候选只能进入
一个最先命中的 reason 或成功 labels，计数必须守恒；尾部截断是预期 INFO，其他原因进入 G1/G3
质量报告。

每个 horizon 的 labels/diagnostics 必须与 `label_manifest.json` 在同一 stage receipt 原子发布。
`build_label_artifact` 绑定 G1/snapshot/experiment、eligible/bars/calendar/benchmark 输入 digest 与输出
digest，并验证 `candidate_count = success_count + diagnostic_count`、`labels_row_count=success_count`、
diagnostics row-count/sample-count 区分和唯一 label/diagnostic key hash；`verify_label_artifact` 从文件重算，
拒绝自报 hash、未知字段、duplicate JSON key、NaN 和宽松数字转换。该 manifest 的生产者属于 G3A，
不由 G8 编排器临时补造。

reason 优先级按上段列举顺序固定：tail → benchmark entry → benchmark exit → asset entry bar → asset
exit bar → entry factor → exit factor。`benchmark_bars` 必须通过实际代码 SSOT 的
`BenchmarkBar1dSchema`，且只含显式 `benchmark` 参数对应切片；现行配置验证只接受 `510300.SH`。
`ForwardReturnLabelSchema` 对三列收益要求 finite，benchmark 使用独立 benchmark pattern，绝不放宽可交易
证券 `SYMBOL_PATTERN`。当前 Schema/label builder 已有初次实现和测试；readiness 虽已移除个股必需列，
但消费边界必须执行 exact `BenchmarkBar1dSchema`，required-column subset 不得代替 strict Schema。extra
column、dtype 或 Schema 约束失败统一形成 `BENCHMARK_INVALID` 且不泄露底层异常。Schema 验真必须发生在
任何 `source/benchmark/date` filter、comparison、duplicate 或 coverage 表达式之前；因 Schema 开启
coercion，下游只允许消费 `validate` 返回的规范 DataFrame，不得继续操作原 frame。extra 表若要继续收集
独立覆盖 issue，先投影 required columns，再以同一 Schema 验真该投影；现有绿测不能作为完整 G1/G3 证据。
当前 G1-P1 已按此通过主验。生产 Schema 的唯一键 check 会把重复 benchmark key 归入
`BENCHMARK_INVALID`；专用 `BENCHMARK_DUPLICATE_KEYS` 的诊断恢复记录为 P2，随 B4 统一质量错误分类处理，
不得为恢复专用码把 duplicate Polars 操作移回 Schema 之前。

### 4.4 `folds.py`

G4–G6 的现行执行颗粒度、verified artifact、失败语义和外部闭环以
[`M3_G4_G6研究链分包骨架与外部闭环任务单.md`](agent/M3_G4_G6研究链分包骨架与外部闭环任务单.md) 为准；
旧 H0–H5 合并任务只保留设计历史。fold 不再向下游暴露裸 `FoldPlan` 或 caller 自报 hash。

```python
@dataclass(frozen=True)
class PlannedFold:
    name: str
    train_dates: tuple[dt.date, ...]
    train_validation_embargo_dates: tuple[dt.date, ...]
    validation_dates: tuple[dt.date, ...]
    validation_test_embargo_dates: tuple[dt.date, ...]
    test_dates: tuple[dt.date, ...]
    train_label_available_by: dt.date
    validation_label_available_by: dt.date
    planned_fold_sha256: str

@dataclass(frozen=True)
class FoldPlanBuildSpec:
    experiment_key: str
    experiment_manifest_sha256: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    train_sessions: int
    validation_sessions: int
    test_sessions: int
    step_sessions: int
    embargo_sessions: int
    max_horizon_sessions: int

@dataclass(frozen=True)
class FoldPlanManifestV1:
    schema_version: Literal["m3-fold-plan-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    session_calendar_sha256: str
    signal_dates_sha256: str
    scientific_config_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    max_horizon_sessions: int
    folds: tuple[PlannedFold, ...]

@dataclass(frozen=True)
class FoldPlanUpstreamPaths:
    snapshot_request_path: Path
    snapshot_receipt_path: Path
    provider_dump_tool_path: Path
    provider_receipt_path: Path
    experiment_receipt_path: Path

@dataclass(frozen=True)
class VerifiedFoldPlanArtifact:
    root: Path
    manifest: FoldPlanManifestV1
    manifest_sha256: str
    folds_receipt_sha256: str

def build_temporal_fold_plan(
    *, snapshot: VerifiedSnapshotArtifact,
    experiment: VerifiedExperimentIdentity, config: LoadedM3Config,
    spec: FoldPlanBuildSpec, output_root: Path,
) -> FoldPlanManifestV1: ...

def verify_fold_plan_artifact(
    *, root: Path, receipt_path: Path, release: VerifiedG1Release,
    snapshot: VerifiedSnapshotArtifact, snapshot_spec: SnapshotBuildSpec,
    provider: VerifiedProviderArtifact, provider_spec: ProviderBuildSpec,
    experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, config: LoadedM3Config,
    spec: FoldPlanBuildSpec, upstream_paths: FoldPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path],
) -> VerifiedFoldPlanArtifact: ...

def select_supervised_labels(
    *, label: VerifiedLabelArtifact, folds: VerifiedFoldPlanArtifact,
    release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    snapshot_spec: SnapshotBuildSpec, provider: VerifiedProviderArtifact,
    provider_spec: ProviderBuildSpec, experiment: VerifiedExperimentIdentity,
    experiment_spec: ExperimentIdentitySpec, config: LoadedM3Config,
    label_spec: LabelBuildSpec, fold_spec: FoldPlanBuildSpec,
    label_receipt_path: Path, folds_receipt_path: Path,
    upstream_paths: FoldPlanUpstreamPaths,
    artifact_roots: Mapping[str, Path], fold_name: str,
    segment: Literal["train", "validation"],
) -> pl.DataFrame: ...
```

development example 复用完全相同的 manifest、schema、hash 与 receipt 形态，但使用精确平行 API 和
`VerifiedDevelopmentExampleFoldPlanArtifact(release_kind="development_example", formal_gate_eligible=False,
example_id=...)`。formal API 在写入前拒绝 development nominal；development 产物只允许位于显式
development/example 路径，不能进入正式 G1/G4 发布根、journal 或候选映射。当前最小 fixture 含 38 个
history sessions：前 28 个 signal sessions 加 10 个 label-tail sessions；development walk-forward 为
`2/2/2/2/10`，恰好两折。该链通过只表示开发契约通过，不关闭正式 G4 Gate。

M3 使用固定长度 rolling window，不使用 expanding train。`open_dates` 必须唯一、严格递增且全部是冻结
SH session；函数先取 `[signal_start,signal_end]`，provider 的 60-session warmup 和 10-session label tail
永不进入 train/validation/test。`embargo_sessions >= max_horizon_sessions`，且为形成无重叠样本外汇总，M3 要求
`step_sessions >= test_sessions`。每折布局固定为
`train -> embargo_1 -> validation -> embargo_2 -> test`，尾部不足完整 test 不生成。

标签可知截止点不是 segment end：train 标签允许使用到 `embargo_1` 最后一个 session 已知的数据，
validation 标签允许使用到 `embargo_2` 最后一个 session 已知的数据。embargo 的作用正是等待前段标签
成熟；若仍用 train/validation end 截止，会无理由丢掉各段末尾约 h 个信号。test 只用于模型冻结后的
推理与事后评估，其标签可知截止由 `test.end + horizon tail` 单独验真，不进入训练接口。

`folds.json` 是 strict `FoldPlanManifestV1`，必须发布完整日期列表、两个 label cutoff、完整 warmup→tail
`session_calendar_sha256`、信号域 `signal_dates_sha256`、experiment 已绑定的 `scientific_config_sha256` 和
每折日期 hash；只存
首尾日期不足以证明 session 数、embargo 或日历未漂移。fold name 由规范日期计划稳定生成。跨折 train
可以重叠，test 日期不得重叠；任何 test 指标不得用于参数、iteration 或 feature schema 选择。

FoldPlan 必须非空。fold receipt 固定为 `EXPERIMENT` scope，formal/development stage 分别为
`folds`/`development-folds`；直接输入精确为 snapshot request、snapshot manifest/receipt/calendar、
experiment manifest/receipt，输出只允许 `folds.json`。标签选择器每次消费都用完整上游 nominal、配置、
spec、receipt 和 artifact roots 重新验真 label 与 FoldPlan，拒绝漏项、增项、decoy 或仅信已构造 dataclass。
`FoldPlanUpstreamPaths` 是上游 request/receipt/tool 的唯一物理路径来源；不得从 snapshot 的最具体 alias
反推公共 artifacts base。Fold verifier 必须 fresh 验真 snapshot、provider、experiment 各自的完整 receipt
闭包，并按 digest 解析出的精确物理路径处理重叠 root alias；禁止 basename 搜索或同 bytes decoy 替换。
spec 的 signal window 必须等于 snapshot request/manifest 从 G1 继承的窗口，walk-forward 数值必须等于
`LoadedM3Config` scientific selector；C0 不存在独立 `walk_forward_config_sha256`，不得新增伪 selector。

### 4.5 `features.py`、`alignment.py` 与 `qlib_adapter.py`

row key、允许 NaN 的 Float64 feature matrix、finite label series 和 schema digest 精确采用
[`M3_G4_G6研究链分包骨架与外部闭环任务单.md`](agent/M3_G4_G6研究链分包骨架与外部闭环任务单.md) §2.1 的
`m3-f64-matrix-digest-v1`；禁止 pickle、本机默认 endian、Parquet bytes 或 NaN JSON 作为逻辑摘要。

```python
@dataclass(frozen=True)
class FeatureSchemaManifestV1:
    feature_version: str
    qlib_version: str
    input_names: tuple[str, ...]
    expressions: tuple[str, ...]
    input_schema_sha256: str
    selected_names: tuple[str, ...]
    selected_dtypes: tuple[str, ...]
    dropped_all_nan_train: tuple[str, ...]
    selected_schema_sha256: str

@dataclass(frozen=True)
class FeatureSegmentManifestV1:
    name: Literal["train", "validation", "test"]
    path: str
    bytes_sha256: str
    content_sha256: str
    eligible_keys_sha256: str
    feature_row_keys_sha256: str
    feature_matrix_sha256: str
    scorable_keys_sha256: str
    n_eligible: int
    n_feature_rows: int
    n_scorable: int

@dataclass(frozen=True)
class FeatureManifestV1:
    schema_version: Literal["m3-feature-artifact-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    provider_key: str
    provider_manifest_sha256: str
    provider_receipt_sha256: str
    fold: str
    planned_fold_sha256: str
    scientific_config_sha256: str
    eligible_keys_sha256: str
    worker_protocol_version: str
    schema: FeatureSchemaManifestV1
    segments: tuple[FeatureSegmentManifestV1, ...]
    coverage_path: str
    coverage_sha256: str
    coverage_row_count: int

@dataclass(frozen=True)
class FeatureBuildSpec:
    experiment_key: str
    experiment_manifest_sha256: str
    fold: str
    planned_fold_sha256: str
    provider_key: str
    provider_manifest_sha256: str
    provider_receipt_sha256: str
    feature_version: str
    expected_qlib_version: Literal["0.9.7"]
    worker_protocol_version: Literal["m3-qlib-worker-v1"]

@dataclass(frozen=True)
class VerifiedFeatureArtifact:
    root: Path
    manifest: FeatureManifestV1
    manifest_sha256: str
    feature_receipt_sha256: str

@dataclass(frozen=True)
class AlignmentBuildSpec:
    experiment_key: str
    work_key: str
    fold: str
    planned_fold_sha256: str
    horizon_sessions: Literal[5, 10]
    feature_manifest_sha256: str
    label_manifest_sha256: str

@dataclass(frozen=True)
class AlignmentSegmentManifestV1:
    name: Literal["train", "validation"]
    path: str
    bytes_sha256: str
    row_keys_sha256: str
    matrix_sha256: str
    labels_sha256: str
    n_feature_scorable: int
    n_label_identity: int
    n_label_joined: int
    n_cutoff_dropped: int
    n_final: int

@dataclass(frozen=True)
class AlignmentManifestV1:
    schema_version: Literal["m3-alignment-artifact-v1"]
    experiment_key: str
    work_key: str
    fold: str
    planned_fold_sha256: str
    horizon_sessions: int
    feature_manifest_sha256: str
    label_manifest_sha256: str
    selected_feature_schema_sha256: str
    segments: tuple[AlignmentSegmentManifestV1, ...]
    diagnostics_path: str
    diagnostics_sha256: str
    diagnostics_row_count: int

@dataclass(frozen=True)
class VerifiedAlignmentArtifact:
    root: Path
    manifest: AlignmentManifestV1
    manifest_sha256: str
    alignment_receipt_sha256: str

@dataclass(frozen=True)
class SupervisedSegment:
    name: Literal["train", "validation"]
    features: pd.DataFrame
    labels: pd.Series
    metadata: pl.DataFrame

@dataclass(frozen=True)
class InferenceSegment:
    name: Literal["test"]
    features: pd.DataFrame
    metadata: pl.DataFrame

def build_feature_artifact(
    *, release: VerifiedG1Release, snapshot: VerifiedSnapshotArtifact,
    provider: VerifiedProviderArtifact,
    experiment: VerifiedExperimentIdentity, folds: VerifiedFoldPlanArtifact,
    config: LoadedM3Config, spec: FeatureBuildSpec, python_executable: Path,
    output_root: Path, timeout_seconds: float,
) -> FeatureManifestV1: ...

def verify_feature_artifact(...) -> VerifiedFeatureArtifact: ...

def load_supervised_segment(
    *, alignment: VerifiedAlignmentArtifact,
    segment: Literal["train", "validation"],
) -> SupervisedSegment: ...

def build_alignment_artifact(
    *, feature: VerifiedFeatureArtifact, label: VerifiedLabelArtifact,
    folds: VerifiedFoldPlanArtifact, experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, spec: AlignmentBuildSpec, output_root: Path,
) -> AlignmentManifestV1: ...

def build_inference_segment(
    *, feature: VerifiedFeatureArtifact, folds: VerifiedFoldPlanArtifact,
    fold_name: str,
) -> InferenceSegment: ...
```

H1 启动前必须由编排器确认 provider-validation PASS；该 receipt 只作前置门禁，不传给 H1 builder/handler、不列入
feature 内容 receipt。H1 只读取已验真的 snapshot `session_calendar.parquet`、provider receipt/tree 与 fold，
不能接受调用者临时传入另一份 calendar。`FeatureBuildSpec` 在启动 worker 前重算并核对 provider/fold/config
identities，worker 回包必须 echo 相同 identity。feature 配置只由 scientific selector 验真；C0 不存在独立
`feature_config_sha256`。inference 只能按 `fold_name` 从 verified folds bundle 取 test 日期，不接受裸 fold。
这里的“已验真”是本次调用沿显式 upstream paths/spec fresh 重验 G4A 及其上游，不接受仅凭可构造 dataclass
跳过磁盘验真。稳定 worker request/response 只保存 provider URI 身份摘要；绝对 URI 仅经 fresh subprocess
临时环境传递，不进入 manifest、receipt、stdout 或其他稳定产物。

`features.py` 是安全 parent API；`qlib_adapter.py` 是唯一 Qlib worker。handler 构造与 DatasetH prepare 必须在
同一个 fresh Python 子进程中连续执行，Qlib 对象不能跨进程返回；父进程只通过规范 JSON/Parquet 接收普通
数据并从原始文件重算 manifest。不得让 Qlib recorder 成为主实验记录器。Alpha158 features **按 fold 生成一次并在 h=5/h=10
间共享**；标签对齐才是 work/horizon 级。禁止为两个 horizon 重算和复制同一份大特征矩阵。

首版 processor 与标签策略冻结如下：

1. 生产 feature handler 固定为官方 Qlib v0.9.7 `Alpha158` 默认 158 个 expression，显式传
   `infer_processors=[]`、`learn_processors=[]`、`label=([], [])`；不允许 loader 计算 `LABEL0`，更不能
   把它丢弃后假装没有前瞻依赖。Qlib v0.9.7 官方源码确认 Alpha158 默认 learn processor 含
   `DropnaLabel/CSZScoreNorm`，因此这三个显式空值是防泄漏契约，不是可选优化：
   <https://github.com/microsoft/qlib/blob/v0.9.7/qlib/contrib/data/handler.py>。
2. handler `start_time` 必须使用 provider manifest 的 history start，而不是 train start；否则首个 train
   session 没有 60-session rolling lookback。`end_time=fold.test.end`，instruments 使用 provider manifest
   发布的历史并集 instrument set，禁止 Alpha158 默认 `csi500` 或今天的 csi300。Dataset segments 使用
   PlannedFold 的三个精确边界。
3. `DatasetH.prepare(..., col_set="feature", data_key=DataHandlerLP.DK_I)` 只导出 feature。Qlib 官方文档
   明确 `prepare` 的 segment/col_set/data_key 职责：<https://qlib.readthedocs.io/en/stable/component/data.html>。
   返回列必须与运行时 `get_feature_config()` 的 158 个唯一 name/expression 一一对应；接受全为 feature
   group 的两级列或唯一 flat names，其他列结构、重复 leaf name、数量不为 158 均失败。manifest 记录
   names、expressions、实际 Qlib 版本及 hash，不能只写 `Alpha158` 字符串。
4. feature index 必须按命名 level 从 Qlib `(datetime,instrument)` 显式转换为项目
   `(as_of,symbol)`；证券代码转换只调用 snapshot 的同一对映射函数，不复制字符串逻辑。
   时间戳必须无时区且为午夜；不能用 `.date()` 静默截断日内或时区值。转换后重复键、segment 外日期、
   非 SH session 都失败。
5. verified G1 release 的 `eligible_keys` 是唯一正向 PIT 资格域，键必须唯一且只含 fold 三段日期。先按 segment 与资格键过滤
   Qlib 历史行，再以 **train eligible rows** 拟合 feature schema：inf 转 NaN，只删除 train 全 NaN 列，
   validation/test 复用同一有序列和 float64 dtype。选定列后整行全 NaN 是 unscorable，三段均剔除并按日
   输出 `n_eligible/n_feature_rows/n_scorable/reason`；不做均值填充、不删普通含 NaN 行、不按 test 改列。
   “剔除”是指从 G4C/inference 的 scorable 消费域剔除；G4B segment parquet 仍保留该 feature row，保证
   `feature_row_keys_sha256` 与 `scorable_keys_sha256` 均可由稳定产物独立重建，不依赖 worker summary。
6. `build_alignment_artifact` 只允许 train/validation。它消费对应 `VerifiedLabelArtifact` 并使用 PlannedFold
   对应 `available_by`，一对一连接 scorable feature keys；X/y 使用同一
   唯一 `(as_of,symbol)` pandas MultiIndex、稳定排序且行数/顺序完全一致。缺标签进入 alignment diagnostics，
   不得填充。
7. test 使用 `build_inference_segment`，**绝不 join 未来标签**。所有 PIT eligible 且 scorable test keys
   都必须进入预测；标签只在模型已冻结、predictions 已发布后由 evaluate 事后连接。否则会产生幸存者/
   可标签样本选择偏差，并让 G7 缺少本应交易的信号。

这条路径不包含需要 `fit` 的 feature processor，因此不存在“在 validation/test 上 fit”的入口。
未来若增加任何有状态 processor，必须新增可见的 processor manifest，证明其 fit 日期严格等于
train segment；不能仅依赖 DatasetH 的 segment，因为 segment 只控制 prepare 取数，不自动限制
handler processor 的拟合区间。

provider history domain 与 model sample domain 必须分离：前者为历史成分并集的连续行情，以保证新
调入证券首个生效日也有完整 60-session Alpha158 回看；后者只能是 PIT membership 当日有效的
`eligible_keys`。禁止通过删 provider 历史来表达样本资格，也禁止保留历史后省略资格 join。

G3 的 Qlib 对账只是语义审计：在日期 `t` 计算
`Ref($close, -h) / Ref($open, -1) - 1` 的证券调整后收益，并减去独立 `510300.SH` ETF HFQ 总回报代理
区间收益，与独立标签的
`raw_return/benchmark_return/relative_return` 三列逐行比较。对账表达式不得反向成为训练标签 SSOT。

该审计必须在 fresh Python 子进程中完成并关闭 Qlib disk/expression cache；父进程和核心 import 路径不得
加载 Qlib。每个 horizon 独立运行，先按 `benchmark/label_version/horizon` 严格取得唯一标签切片。Qlib
表达式结果只保留已发布 label keys；缺一行、重复、多一身份或非 finite 都失败。不得只抽样 reconciliation。

启动 worker 前先验真 provider、label、snapshot calendar、G1 benchmark 文件及全部 receipt/hash；任一
“A 的 DataFrame + B 的 digest”组合都在 import Qlib 前失败。worker 请求和回包必须 echo identities。
主 join key 固定为 `(as_of,symbol,benchmark,horizon_sessions,label_version)`；return start/end 由权威 session
独立推导后逐值比较，不能放进 join key 掩盖日期错位。provider expression/direct 先以 `(as_of,symbol)`
计算，再严格一对一连接主 key。

由于固定 `dump_bin.py` 把 provider fields 写成 float32，G3 不再使用不可实现的单一 `1e-10` 门槛，而是
分开核对三层：

1. 对每个 label key，另外通过 Qlib 直接读取 return start 的 `$open` 和 return end 的 `$close`，手算
   `provider_raw_return`；与 Qlib `Ref` expression 的误差使用 `validation.labels.qlib_expression_atol`。
2. benchmark audit 不调用 `compute_forward_relative_labels`，而以 SH session 和原始 `510300.SH`
   open/close 独立向量化查表；与 label `benchmark_return` 使用 `benchmark_return_atol`。
3. `provider_raw_return` 与权威 Float64 label `raw_return`、以及
   `provider_raw_return-audit_benchmark_return` 与 label `relative_return` 使用 `label_return_atol`，明确容纳
   provider float32 量化但不掩盖日期错位。

details 至少包含唯一键、return start/end、Qlib expression/direct raw、label raw、audit/label benchmark、
audit/label relative、四种 abs error 和稳定 status；summary 分别记录
`expression_direct/benchmark/raw_label/relative_label` 四个 max/p99 序列，不能把后两者合成一个 max；记录 experiment/provider-validation/label
manifest/reconciliation identities、行键 hash、期望/匹配行数、每种 max/p99 error、配置容差和全量 PASS。
p99 固定使用 nearest-rank：升序 n 个误差取 `ceil(0.99*n)-1`（n>0），不得使用依赖版本可能改变插值默认值
的通用 quantile。
JSON 禁止 NaN/Infinity。reconciliation key 绑定 experiment、horizon、provider validation receipt、label
manifest、label-reconciliation config、code/dependency；配置容差改变不重建 provider/experiment，但必须形成新
reconciliation 路径和 receipt。生产 Alpha158 handler 仍固定 `label=([],[])`，训练永不读取该审计输出。

### 4.6 `model.py`

```python
@dataclass(frozen=True)
class LightgbmTrainingSpec:
    model_version: str
    booster_params: tuple[tuple[str, str | int | float | bool], ...]
    num_boost_round: int
    early_stopping_rounds: int
    early_stopping_min_delta: float

@dataclass(frozen=True)
class ModelManifestV1:
    schema_version: Literal["m3-lightgbm-model-v1"]
    experiment_key: str
    work_key: str
    snapshot_id: str
    provider_receipt_sha256: str
    fold: str
    horizon_sessions: int
    model: Literal["lightgbm"]
    model_version: str
    alignment_manifest_sha256: str
    feature_manifest_sha256: str
    label_manifest_sha256: str
    input_feature_schema_sha256: str
    selected_feature_names: tuple[str, ...]
    selected_feature_schema_sha256: str
    params_sha256: str
    train_row_keys_sha256: str
    validation_row_keys_sha256: str
    train_matrix_sha256: str
    validation_matrix_sha256: str
    train_labels_sha256: str
    validation_labels_sha256: str
    lightgbm_version: str
    best_iteration: int
    best_validation_l2: float
    model_sha256: str
    validation_curve_sha256: str

@dataclass(frozen=True)
class VerifiedModelArtifact:
    root: Path
    manifest: ModelManifestV1
    manifest_sha256: str
    model_receipt_sha256: str

def build_model_artifact(
    *, alignment: VerifiedAlignmentArtifact,
    feature: VerifiedFeatureArtifact, label: VerifiedLabelArtifact,
    experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, spec: LightgbmTrainingSpec,
    output_root: Path,
) -> ModelManifestV1: ...

def verify_model_artifact(...) -> VerifiedModelArtifact: ...

def predict_fitted_model(
    *, model: VerifiedModelArtifact, inference: InferenceSegment,
) -> tuple[float, ...]: ...
```

`build_lightgbm_training_spec(config)` 是 training spec 的唯一构造入口。booster parameter key 必须唯一并按
key 排序，值只允许上述规范标量；拒绝 bool/int 混淆、NaN/Infinity、list/dict 和参数别名重复。
`model_version` 从 scientific selector 进入 spec，builder 不接受第二份 free-form 字符串。verifier 同样接收
`LoadedM3Config` 并重验 experiment scientific identity。

预测返回 `PredictionScoreSchema`。不得在测试集重新 fit、early stop 或选择 iteration。

M3 直接调用 LightGBM native `train`，不使用 Qlib `LGBModel`。训练协议冻结为：

1. train/validation 列名、顺序、float64 dtype 和唯一 MultiIndex 完全一致；X 允许普通 NaN 但不允许 inf，
   y 必须 finite，X/y/metadata 的 keys 与顺序逐行一致。train/validation 都非空；test 对象不进入 fit 签名。
2. objective=`regression`、metric=`l2`；只把 validation Dataset 放入 `valid_sets`，使用官方
   `early_stopping(stopping_rounds, first_metric_only=True, min_delta=...)` 和 `record_evaluation`。官方 API
   说明 validation metric 决定 `best_iteration`：<https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.early_stopping.html>。
   不用 test 选 iteration，不做超参数搜索，也不在选出 best iteration 后把 train+validation 合并重训。
   Rank IC 是样本外研究指标，不冒充本版 booster 的 early-stopping metric。
3. `num_boost_round/early_stopping_*` 是 training control，不混进 booster params。booster params 必须显式
   含 objective/metric、`device_type="cpu"`、`deterministic=true`、`force_col_wise=true`、`seed/data_random_seed/
   feature_fraction_seed/bagging_seed` 和 `num_threads`；缺项或 GPU/CUDA 失败。不得由适配器偷偷补值。
4. LightGBM `Dataset` 不设 categorical features、不设 sample weight，保持稳定行序。记录每轮 validation
   l2；`best_iteration >= 1` 且 best score finite，否则失败。模型只保存到 best iteration。
5. `stage_dir` 必须是 StageRunner 分配的空临时目录。函数只写 `model.txt`、`model.metadata.json`、
   `validation_curve.parquet`，不自行覆盖 final work 目录；跨文件原子发布由唯一 StageRunner 完成。metadata
   记录 experiment/work、snapshot/provider、feature/label input hashes、行键/matrix/label hashes、有序 feature
   schema、规范参数、实际 LightGBM 版本、seed、best iteration/score 和 model hash。

`predict_fitted_model` 必须校验输入 feature 名称、顺序和 hash 与 `VerifiedModelArtifact` 完全一致；score 非 finite
立即失败，并只用已保存模型的 `best_iteration`。rank 统一由 `quant.research.m3.predictions` 的唯一
`normalize_prediction_scores` 生成，策略层改为 import 它，禁止模型/策略各写一套。排序分组和
PredictionScore Schema 唯一键都必须包含 `model`，不能只用 `model_version`。

predictions parquet 同目录发布 manifest，至少含 experiment/work、model metadata/model file hash、feature
bundle/test segment/eligibility/signal-date hash、snapshot/fold/horizon/model identity、`n_eligible/n_scorable/
n_predicted` 和 prediction hash。`n_predicted` 必须等于 test `n_scorable`；空预测或遗漏任一 scorable key
失败，不能等 evaluate 或 targets 才发现。

feature projection 的唯一执行点是 `build_feature_artifact`：先验真 158 维 input schema，再应用
train-only 全 NaN 列投影，输出 selected schema。model/predict 只接受该 bundle 的 selected columns，
不得由编排器临时 `.drop()`。`verify_model_artifact` 用于 train 与 predictions 分属不同进程的恢复路径，必须
复算 model/metadata/curve hash，并核对 work、snapshot/fold/horizon、feature projection 和实际 LightGBM
版本。`model.metadata.json` 不记录自身 hash，避免身份循环；其 bytes hash 只进入 verified bundle 与 receipt。

### 4.7 `evaluate.py`

```python
@dataclass(frozen=True)
class PredictionBuildSpec:
    experiment_key: str
    work_key: str
    fold: str
    horizon_sessions: Literal[5, 10]
    model: Literal["lightgbm"]
    model_version: str

@dataclass(frozen=True)
class PredictionManifestV1:
    schema_version: Literal["m3-prediction-artifact-v1"]
    experiment_key: str
    work_key: str
    model_manifest_sha256: str
    model_sha256: str
    feature_manifest_sha256: str
    selected_feature_schema_sha256: str
    eligibility_sha256: str
    signal_dates_sha256: str
    snapshot_id: str
    fold: str
    horizon_sessions: int
    model: str
    model_version: str
    n_eligible: int
    n_scorable: int
    n_predicted: int
    prediction_keys_sha256: str
    predictions_sha256: str

@dataclass(frozen=True)
class VerifiedPredictionArtifact:
    root: Path
    predictions: pl.DataFrame
    manifest: PredictionManifestV1
    manifest_sha256: str
    prediction_receipt_sha256: str

@dataclass(frozen=True)
class EvaluationSpec:
    experiment_key: str
    work_key: str
    fold: str
    horizon_sessions: Literal[5, 10]
    minimum_ic_symbols: int

IcStatus = Literal[
    "NO_ELIGIBLE", "NO_LABELS", "NO_PREDICTIONS", "INSUFFICIENT_SYMBOLS",
    "BOTH_ZERO_VARIANCE", "SCORE_ZERO_VARIANCE", "LABEL_ZERO_VARIANCE",
    "COMPUTABLE",
]

@dataclass(frozen=True)
class EvaluationMetricsV1:
    schema_version: Literal["m3-evaluation-metrics-v1"]
    experiment_key: str
    work_key: str
    fold: str
    horizon_sessions: int
    model: str
    model_version: str
    n_dates: int
    n_computable_dates: int
    n_eligible: int
    n_scorable: int
    n_predicted: int
    n_labeled: int
    n_evaluated: int
    feature_coverage: float | None
    prediction_coverage: float | None
    label_coverage: float | None
    evaluation_coverage: float | None
    pearson_ic_mean: float | None
    rank_ic_mean: float | None
    pearson_icir: float | None
    rank_icir: float | None
    status_counts: tuple[tuple[IcStatus, int], ...]
    daily_sha256: str

@dataclass(frozen=True)
class EvaluationManifestV1:
    schema_version: Literal["m3-evaluation-artifact-v1"]
    experiment_key: str
    work_key: str
    prediction_manifest_sha256: str
    label_manifest_sha256: str
    feature_manifest_sha256: str
    fold_plan_manifest_sha256: str
    eligible_keys_sha256: str
    evaluation_dates_sha256: str
    scientific_config_sha256: str
    fold: str
    horizon_sessions: int
    model: str
    model_version: str
    daily_sha256: str
    metrics_sha256: str

@dataclass(frozen=True)
class VerifiedEvaluationArtifact:
    root: Path
    daily: pl.DataFrame
    metrics: EvaluationMetricsV1
    manifest: EvaluationManifestV1
    manifest_sha256: str
    evaluation_receipt_sha256: str

@dataclass(frozen=True)
class ResearchSummaryMetricsV1:
    schema_version: Literal["m3-research-summary-metrics-v1"]
    experiment_key: str
    horizon_sessions: int
    model: str
    model_version: str
    folds: tuple[str, ...]
    n_dates: int
    n_computable_dates: int
    n_eligible: int
    n_scorable: int
    n_predicted: int
    n_labeled: int
    n_evaluated: int
    feature_coverage: float | None
    prediction_coverage: float | None
    label_coverage: float | None
    evaluation_coverage: float | None
    pearson_ic_mean: float | None
    rank_ic_mean: float | None
    pearson_icir: float | None
    rank_icir: float | None
    status_counts: tuple[tuple[IcStatus, int], ...]
    daily_sha256: str

@dataclass(frozen=True)
class ResearchSummaryManifestV1:
    schema_version: Literal["m3-research-summary-v1"]
    experiment_key: str
    horizon_sessions: int
    model: str
    model_version: str
    scientific_config_sha256: str
    folds: tuple[str, ...]
    evaluation_manifest_sha256s: tuple[str, ...]
    evaluation_receipt_sha256s: tuple[str, ...]
    test_dates_sha256: str
    daily_sha256: str
    fold_metrics_sha256: str
    metrics_sha256: str

@dataclass(frozen=True)
class VerifiedResearchSummaryArtifact:
    root: Path
    daily: pl.DataFrame
    fold_metrics: pl.DataFrame
    metrics: ResearchSummaryMetricsV1
    manifest: ResearchSummaryManifestV1
    manifest_sha256: str
    summary_receipt_sha256: str

def build_prediction_artifact(
    *, model: VerifiedModelArtifact, feature: VerifiedFeatureArtifact,
    folds: VerifiedFoldPlanArtifact, experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, spec: PredictionBuildSpec,
    output_root: Path,
) -> PredictionManifestV1: ...

def verify_prediction_artifact(...) -> VerifiedPredictionArtifact: ...

def build_evaluation_artifact(
    *, release: VerifiedG1Release, feature: VerifiedFeatureArtifact,
    prediction: VerifiedPredictionArtifact, label: VerifiedLabelArtifact,
    folds: VerifiedFoldPlanArtifact, experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, spec: EvaluationSpec,
    output_root: Path,
) -> EvaluationManifestV1: ...

def verify_evaluation_artifact(...) -> VerifiedEvaluationArtifact: ...

def summarize_prediction_metrics(...) -> EvaluationMetricsV1: ...

def build_research_summary_artifact(
    *, evaluations: Sequence[VerifiedEvaluationArtifact],
    experiment: VerifiedExperimentIdentity, config: LoadedM3Config,
    horizon_sessions: int, output_root: Path,
) -> ResearchSummaryManifestV1: ...
```

`evaluation_dates` 是当前 PlannedFold 的完整 test_dates，是日期域 SSOT。四层 keys 均按
`(as_of,symbol)` 唯一并满足 `scorable ⊆ eligible`、`predicted == scorable`、`labeled ⊆ eligible`；任何
区间外行、身份混片、集合关系破坏或 prediction 漏行先失败。labels 只按当前 horizon/benchmark/version
过滤；区间外 labels 不影响结果，且不能用 labels 决定哪些 test rows 先生成 prediction。
`VerifiedPredictionArtifact` 的 work/model/model file/feature schema/prediction hash 必须与 parquet 逐项一致；
这些高维研究 lineage 不塞进全局 PredictionScore Schema，但没有已验真 manifest 的 parquet 也不得评估。

每次调用只接受一个唯一的
`(model,model_version,dataset_snapshot_id,fold,horizon_sessions)` 预测切片；若包含多个切片必须
拒绝，不得自动混合。预测唯一键是该切片加 `(as_of,symbol)`，标签唯一键是
`(as_of,symbol,horizon_sessions)`；任一重复键必须在 join 前拒绝。连接键必须包含
`horizon_sessions`。模型名 `model` 也属于 prediction slice 与唯一键，不能让两个不同模型仅因
`model_version` 相同而被合并。

每日输出完整 coverage ladder：`n_eligible,n_scorable,n_predicted,n_labeled,n_evaluated`，并分别汇总：

- `feature_coverage = sum(n_scorable) / sum(n_eligible)`；
- `prediction_coverage = sum(n_predicted) / sum(n_scorable)`，验真后应为 1；
- `label_coverage = sum(n_labeled) / sum(n_eligible)`；
- `evaluation_coverage = sum(n_evaluated) / sum(n_labeled)`。

旧的 matched/expected-label 单一 `prediction_coverage` 会把特征缺失、预测遗漏和标签缺失混为一个数字，
在 G4–G6 实现时废止；F5 二次返工只先修日期域，不代表最终 G6 coverage 契约完成。

`daily_ic.parquet` 列精确为 `as_of,n_eligible,n_scorable,n_predicted,n_labeled,n_evaluated,feature_coverage,
prediction_coverage,label_coverage,evaluation_coverage,pearson_ic,rank_ic,ic_status`。Pearson/Spearman 都只在
evaluated rows 上计算；`ic_status` 按固定优先级选择首个适用项：`NO_ELIGIBLE`、`NO_LABELS`、
`NO_PREDICTIONS`、`INSUFFICIENT_SYMBOLS`、`BOTH_ZERO_VARIANCE`、`SCORE_ZERO_VARIANCE`、
`LABEL_ZERO_VARIANCE`、`COMPUTABLE`，绝不填 0。Spearman 使用 average
tie ranks。日均 IC 是可计算日等权均值；ICIR 是
日 IC mean / sample std (`ddof=1`)，不年化，不做 pooled cross-section。metrics 必须是严格
`EvaluationMetricsV1`，`status_counts` 按八状态完整固定排序且和为日期总数；manifest 绑定全部输入/output hash。
计数写 JSON integer；未定义的 IC/ICIR 写 `null`，规范 JSON 序列化必须 `allow_nan=false`，禁止把 NaN/
Infinity 写入 metrics 或 MLflow。
`minimum_ic_symbols` 必须与 `LoadedM3Config` scientific selector 相等；C0 不存在独立
`evaluation_config_sha256`。prediction 的 signal/eligibility hash 只能从 verified folds/feature 推导，不允许 spec
自报。所有 Parquet 使用 zstd level 3、statistics、row group 65536、Polars native writer 的冻结参数。

`build_research_summary_artifact` 只接受同 experiment/model/model version/horizon 且 test dates 不重叠的
verified evaluation；拼接
daily 后按同一公式重算 aggregate，不平均各 fold ICIR，不选择“最好 fold”。若 test 日期重叠立即失败。
该函数只聚合研究 IC；G7 的独立现金账户收益不得在这里顺序复合。

### 4.8 `ml_topk.py`

```python
class MlTopkStrategy(Strategy):
    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame: ...
```

输入只允许 `PredictionScoreSchema` 和当日资格表；输出 `TargetWeightSchema`。排序规则固定；策略
无状态、不读取账户。首版使用等权 Top-k，权重不超过 `1-cash_buffer` 和单证券 `max_weight`。
TopkDrop 不属于 M3 完成条件；未来实现时必须由调用者显式传入上期选择集合，不得藏在全局变量、
对象可变状态或磁盘中。若现有 `Strategy` 接口无法表达，应先提交接口变更方案。

无状态 Top-k 也必须在按 `as_of` 过滤后确认预测只有一个
`(model,model_version,dataset_snapshot_id,fold,horizon_sessions)` 切片；多切片输入必须拒绝。
资格表每个 symbol 只能有一个布尔值，冲突记录不得使用任意 `unique` 结果。

`TargetWeightSchema` 是 M2/M3/交易层共用契约，不增加研究框架字段。M3 target stage 必须发布 strict
`TargetManifestV1` 并经 `VerifiedTargetArtifact` 消费，固定记录模型、G1 release、snapshot、fold、horizon、prediction/eligibility/
signal dates/target domain/target 文件 hash、三层覆盖计数和策略身份。manifest 与 target parquet
及逐日覆盖表共同作为 targets stage receipt 的输出；任何字段变化必须改变下游 backtest run identity。禁止把这些
血缘压进 `strategy_version` 字符串，也禁止仅依赖上游目录名推断。

每个 test signal date 的 target domain 是当日全部 PIT eligible symbols；`n_scorable` 是其中确实存在
Alpha158 feature row 的证券，`n_predicted` 必须等于 `n_scorable`。无预测、无 eligible、预测遗漏 scorable
证券或 scorable/eligible 低于配置阈值都使 targets stage 失败，不能发布空 batch。Top-k 只在 scorable
预测中选择，但最终 target parquet 必须扩展到完整 target domain，未选中和不可评分的 eligible symbol
显式为 0；已调出证券由模拟器与实际持仓取并集后补 0。空文件绝不表示清仓或保持仓位。

```python
def build_target_artifact(
    *, release: VerifiedG1Release, feature: VerifiedFeatureArtifact,
    prediction: VerifiedPredictionArtifact, folds: VerifiedFoldPlanArtifact,
    experiment: VerifiedExperimentIdentity, config: LoadedM3Config,
    spec: TargetBuildSpec, output_root: Path,
) -> TargetManifestV1: ...

def verify_target_artifact(
    *, root: Path, receipt_path: Path, release: VerifiedG1Release,
    feature: VerifiedFeatureArtifact, prediction: VerifiedPredictionArtifact,
    folds: VerifiedFoldPlanArtifact, experiment: VerifiedExperimentIdentity,
    config: LoadedM3Config, artifact_roots: Mapping[str, Path],
) -> VerifiedTargetArtifact: ...
```

该 builder 属于 `quant.research.m3.targets` 的纯适配层；策略仍只处理预测排序，适配层负责覆盖率门禁和完整
domain 扩展。不得要求策略读取持仓或把 research lineage 加进全局 TargetWeight Schema。

### 4.9 `tracking.py` 和 `run_m3.py`

```python
def register_m3_work(
    *, request: TrackingRequestV1, tracking_uri: str, experiment_name: str,
    artifact_roots: Mapping[str, Path],
) -> TrackingMarkerV1: ...

def compute_tracking_key(*, work_key: str, request_sha256: str) -> str: ...

@dataclass(frozen=True)
class ArtifactDigest:
    root_alias: str
    relative_path: str
    size_bytes: int
    sha256: str

@dataclass(frozen=True, kw_only=True)
class StageReceipt:
    receipt_version: Literal["m3-stage-receipt-v1"] = "m3-stage-receipt-v1"
    stage: str
    scope: Literal[
        "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"
    ]
    scope_key: str
    inputs: tuple[ArtifactDigest, ...]
    outputs: tuple[ArtifactDigest, ...]

def compute_experiment_key(
    *, snapshot_id: str, provider_receipt_sha256: str,
    scientific_config_hash: str, code_version: str,
    dependency_fingerprint_sha256: str,
) -> str: ...

def compute_snapshot_request_key(
    *, g1_release_id: str, g1_release_manifest_sha256: str,
    snapshot_config_sha256: str, code_version: str,
) -> str: ...

def compute_provider_key(
    *, snapshot_id: str, provider_config_hash: str,
    dump_tool_sha256: str, qlib_version: str,
    provider_runtime_fingerprint_sha256: str, code_version: str,
) -> str: ...

def compute_provider_validation_key(
    *, provider_key: str, provider_receipt_sha256: str,
    provider_validation_config_sha256: str,
    provider_runtime_fingerprint_sha256: str, code_version: str,
) -> str: ...

def compute_label_reconciliation_key(
    *, experiment_key: str, horizon: int,
    provider_validation_receipt_sha256: str,
    label_manifest_sha256: str, label_reconciliation_config_sha256: str,
    dependency_fingerprint_sha256: str, code_version: str,
) -> str: ...

def compute_work_key(
    *, experiment_key: str, fold: str, horizon: int,
) -> str: ...

def verify_stage_receipt(
    *, receipt_path: Path, artifact_roots: Mapping[str, Path],
) -> StageReceipt | None: ...

def publish_stage_receipt(
    *, receipt_path: Path, stage: str,
    scope: Literal[
        "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"
    ],
    scope_key: str, artifact_roots: Mapping[str, Path],
    inputs: Sequence[tuple[str, Path]],
    outputs: Sequence[tuple[str, Path]],
) -> StageReceipt: ...

def main(argv: Sequence[str] | None = None) -> int: ...
```

所有 identity/key、配置 hash、manifest/receipt digest 的编码统一为**裸 64 位小写十六进制 SHA-256**；
不得返回或持久化 `sha256:<hex>`。这些值会直接组成 Windows 挂载盘目录，冒号非法。若报告需要可读算法名，
另写稳定字段 `hash_algorithm="sha256"`，不进入路径或 hash 值。identity join 仍是规范 JSON 数组 UTF-8
后 SHA-256，只迁移输出编码，不允许同时兼容两种格式。
所有组合 key 必须调用其唯一具名函数；禁止把字段直接串接后 hash。规范数组编码必须覆盖
`("ab","c")` 与 `("a","bc")` 不碰撞的反例。

CLI 支持 `readiness`、`snapshot`、`train`、`evaluate`、`backtest`、`run-all`、
`verify-reproducibility`、`acceptance-audit` 八个子命令；
每步可重跑，已存在相同 snapshot 时必须校验后复用，不得覆盖不同内容。

命令依赖闭包与停止点冻结如下；共同参数均含 `--config`：

| Command | Required identity args | Stop stage |
|---|---|---|
| `readiness` | `--g1-release-id` | readiness；不生成 snapshot |
| `snapshot` | `--g1-release-id` | snapshot；输出 snapshot ID，不生成 provider |
| `train` | `--snapshot-id --fold --horizon` | 自动验真/生成 provider/shared/features，止于 train |
| `evaluate` | `--snapshot-id --fold --horizon` | 止于 evaluation |
| `backtest` | `--snapshot-id --fold --horizon` | 止于 backtest，不登记 MLflow |
| `run-all` | `--g1-release-id` 或 `--snapshot-id` 二选一 | 所有 work 止于 tracking |
| `verify-reproducibility` | `--snapshot-id --fold --horizon` | 两个冷启动 attempt 与 comparison receipt |
| `acceptance-audit` | `--snapshot-id` | 重算 provider/experiment identity，执行固定质量命令与 G0–G9 审计；只在全通过时发布 acceptance receipt |

提供 snapshot ID 时只验真/复用已有 snapshot，不回退 G1 构建；提供 G1 release 时按分段计划生成或复用。
stdout 只输出一份规范 JSON，所有 warning/log 写 stderr。退出码：0 成功或验真复用；2 参数/配置/契约；
3 readiness/G1/snapshot 数据门禁；4 Qlib/LightGBM/MLflow 等依赖不可用；5 本地 stage/receipt；6 tracking；
7 冷启动比较；8 质量或最终验收。同一命令有多类失败时 summary 全列，进程取最小非零 code；code 2
在执行前返回且不写产物。

`params` 和 `tags` 的安全检查必须递归遍历 Mapping/Sequence，检查所有嵌套键和字符串值；
`token,password,secret,api_key,apikey`、Bearer/token 内容和绝对本机路径在任意嵌套层级都必须
被拒绝。依赖版本、模型参数等结构化值可记录，但不得把未筛选的整份项目配置传入
tracking 层。artifact 路径必须在打开 MLflow run 前全部校验存在，避免留下部分记录。

`run_m3` 是薄编排器，不包含因子、标签、训练或回测算法。运行身份分成三层；Qlib provider 是 snapshot
的确定性派生产物，使用独立 `provider_key`，不向不可变 snapshot 目录追加文件：

```text
snapshot_dir  = artifacts/research/m3/snapshots/<snapshot_id>/
provider_key   = compute_provider_key(...)
provider_dir   = artifacts/research/m3/providers/<provider_key>/
experiment_key = compute_experiment_key(...)
experiment_dir = artifacts/research/m3/runs/<experiment_key>/
work_key       = compute_work_key(...)
work_dir       = <experiment_dir>/work/fold=<fold>/horizon=<horizon>/
```

`scientific_config_hash` 只覆盖 4.0 冻结的精确 selector：`runtime.qlib.version`、完整 `data`、`features`、
`labels`、`walk_forward`、`model.lightgbm`、`evaluation`、`portfolio`、`backtest.a_share`、`costs`；排除 tracking URI、
dump tool URL/hash/bytes、supported-python policy、artifact 物理根路径、validation/验收阈值和注释。配置解析器拒绝这些子树内的未知键、缺失必需键和错误类型。snapshot manifest
只记录 4.0 的 narrow `snapshot_config_sha256`；`provider_config_hash` 只覆盖 market/frequency/provider
fields/format。Qlib version、实际 runtime fingerprint 与 dump tool hash 作为独立 provider-key 字段加入，
不重复放入 provider config hash。改变 tracking URI 不改变任何科学 identity；改变费用只改变 experiment/
work；改变 provider 字段、Qlib version、runtime 或 dump tool 改变 provider/experiment，但不伪造新的 snapshot。
`code_version` 优先使用可验证的 Git
commit + dirty tree hash；仓库元数据不可用时，退化为本次运行涉及的 `src/quant` 与版本化配置文件的
“相对路径 + 文件 SHA-256”规范化集合 hash，禁止写固定的 `unavailable` 造成缓存碰撞。

readiness 同时发布 provider 子集和完整 dependency fingerprint。provider subset 至少包含 Python、NumPy、
pandas、PyArrow、Qlib、Fire、tqdm、Loguru 的实际版本，进入 provider key；其中任一变化必须重建
provider。完整 `dependency_fingerprint_sha256` 另包含平台、`pyproject.toml` hash、Polars、SciPy、
scikit-learn、LightGBM 等所有参与研究/回测的版本或明确 `NOT_INSTALLED`，进入 experiment/work。只改
LightGBM 可复用 provider、不能复用 experiment；改 NumPy/pandas/Qlib 两层都必须变化。MLflow 另记录
可读依赖清单，但 identity 只使用稳定 hash。

snapshot 是内容寻址产物，因此编排使用显式 continuation，不能在上游身份尚未发布时伪造下游计划。
第一段负责产生 `snapshot_id`：以
`snapshot_request_key=compute_snapshot_request_key(...)`
在 `snapshot-builds/<snapshot_request_key>/` 执行 readiness/staging；manifest 验真后才计算 `snapshot_id`，
再把完整 staging 目录原子发布到 `snapshots/<snapshot_id>/`，并写不可变
`snapshot-requests/<snapshot_request_key>.json` 映射。第二段读取已验真的 snapshot manifest，计算
`provider_key` 并执行 provider；再以 provider receipt、`provider_validation_config_sha256`、runtime/code 形成独立
provider-validation key 并发布 probe 证据。第三段要求 provider-validation PASS 后继续，但只由已验真的
snapshot/provider receipts 与科学身份计算并发布 experiment identity；随后发布 labels、G3 reconciliation 与
folds shared evidence，其中 reconciliation 独立绑定 provider-validation receipt。第四段读取 folds receipt，构造每-fold shared
features 与 fold×horizon work；第五段只在所需 evaluation receipts 完整后构造 research summary。
请求映射已存在时，必须验真目标 snapshot 后复用；
映射或目标损坏时 fail-closed，不重指向另一个 snapshot。

snapshot 发布是 StageRunner 唯一受控的内容寻址特例：先目录级 no-clobber 发布完整 snapshot，再
no-clobber 发布 strict request record，最后发布 `stage="snapshot"/scope="SNAPSHOT"` receipt。receipt inputs
精确为 G1 manifest 与实际读取的 bar/membership/calendar，outputs 精确为 request record、snapshot manifest、
session calendar 与全部 staging 文件。中间崩溃只允许在完整内容逐字节相同时认领；任何冲突不得覆盖。

- 每一步只读取声明依赖的已发布产物，写入本 stage 的临时目录，校验后以原子 rename 发布；最后写
  `<stage>.complete.json`，其中列出输入/输出相对路径及 SHA-256。完成标记不得先于产物出现。
- 重跑遇到完成标记时必须重新校验所有 hash；全部一致才复用，缺失或不一致立即失败，不静默覆盖。
- 未完成标记对应的临时文件可清理后重算。若崩溃发生在产物 rename 后、receipt 发布前，重算结果与
  orphan 产物逐字节一致时可补发 receipt；任何内容冲突都必须失败，不得覆盖。已发布且 hash 不符的文件
  不可就地修补，必须通过改变
  snapshot/config/code 形成新的 snapshot/experiment/work key。
- snapshot 作用域固定为 `readiness -> snapshot`，随后在独立 provider_dir 执行
  `provider -> provider_validation`；experiment 共享作用域为每个 horizon 独立的 `labels[h]` 与 `folds`；
  folds receipt 发布后，每个 fold 只有一个 experiment-scoped `features[fold]`，由该 fold 的 h=5/h=10
  work 共享；work 作用域固定为
  `alignment -> train -> predictions -> evaluation -> targets -> backtest_plan -> backtest -> tracking`。全部 work evaluation
  完成后可构造 `research_summary[h]`，只聚合不重叠 test daily IC。子命令可以止于某
  stage，但不能跳过依赖、跨作用域偷读未声明文件或伪造完成标记。
- `features.<fold>` 的 provider-validation receipt 只作 DAG dependency gate，不进入 feature handler 内容输入；
  它使用 `EXPERIMENT/experiment_key`，由 node id/fold 区分，同 fold 两 horizon 必须引用同一 receipt。fold 的
  signal window 只从 snapshot request/manifest 继承，prediction/evaluation/summary 只接受 G4–G6 冻结的 strict
  manifests/metrics 和精确 receipt 闭包，不接受 caller 自报 selector hash 或宽松 Mapping。
- `run-all` 先验证共享作用域，再按 `(fold name ASC,horizon ASC)` 枚举 work unit。某 work 失败后跳过其
  下游，但继续其他独立 work；`folds` 失败阻止全部 work，某个 `labels[h]` 失败只阻止该 horizon 的 work。
  命令返回非零并输出结构化失败清单，重跑只恢复未完成 work。
- MLflow 是每个 work 的最后登记步骤。本地产物及 hash 全部验证后才打开 run；成功 run ID 写入本地
  marker。tracking 文件位于 `work/tracking/target=<tracking_target_key>/`，其中
  `tracking_target_key` 只能由 C0 `canonical_tracking_target_key` 计算；request 只记录 target key，不记录
  原始 URI 或凭据。这样切换 MLflow server 不改变科学 experiment/work identity，但也不会误复用旧 server
  的 marker。`request.json` 必须包含 work key、过滤后的 params/tags/metrics 与所有 artifact digest；
  `tracking_key` 只能由 `compute_tracking_key(work_key=...,request_sha256=...)` 的规范 JSON 数组编码计算；
  以该 key 查询 MLflow：0 个匹配才新建；1 个 `FINISHED`
  且 request/artifact hash 完全匹配才恢复 marker；`RUNNING`、`FAILED`、`KILLED`、内容不符或多于 1 个
  都 fail-closed，禁止用同一 tracking key 创建第二条记录。创建 run 时必须通过 `start_run(tags=...)` 或
  等价 create API 在首个服务端写操作中附带 `quant_tracking_key`，不能先创建再 set_tag。个人单机版还需
  对 `(tracking_target_key,tracking_key)` 使用 WSL `flock` 互斥，避免两个本地进程同时观察到 0 个匹配；
  跨主机并发不在 M3 保证范围并须在报告披露。只重试 tracking，不重新训练。

`verify_stage_receipt` 只能返回两种成功状态：receipt 不存在返回 `None`；receipt 存在且每个输入输出
hash 均一致时返回对象。receipt 存在但 JSON 非法、路径越界、文件缺失、大小或 hash 不一致时必须
抛出错误，不得把损坏状态解释为“尚未运行”。每个 digest 以 `root_alias + relative_path` 定位；alias
必须存在于调用方显式传入的 `artifact_roots`，路径必须是该 root 内相对 POSIX 路径。每个 root 必须存在、
为目录且自身非 symlink；root 到文件的任一组件出现 symlink 均拒绝，即使最终仍在 root 内。另拒绝未知 alias、
`..`、绝对路径、重复 `(alias,path)` 及 inputs/outputs 交叉重复。这样 work receipt 可以审计 snapshot/provider/
experiment 输入，又不复制大文件或把上级路径写成本机绝对路径。receipt 自身永远不列入自身 outputs。

Receipt 的严格语言与发布语义进一步冻结如下：读取端必须拒绝任意层级 duplicate JSON key、未知或缺失字段、
NaN/Infinity、bool 冒充整数、字符串数字和非规范 JSON 字节；合法 receipt 的原始字节必须恰等于以
`sort_keys=true,separators=(",",":"),ensure_ascii=true,allow_nan=false` 重编码的结果。`ArtifactDigest` 与
`StageReceipt` 直接构造也必须执行同一套值对象校验，不能只在文件 parser 中校验；`inputs/outputs` 必须
是 exact tuple 且元素必须是 `ArtifactDigest`。值对象只验证版本、scope、identity、类型、排序和逻辑重复；
root、文件存在性、物理身份与内容 hash 由 publish/verify 的上下文校验负责。输入、输出分别按
`(root_alias,relative_path)` 严格升序且唯一；同一物理 root 不得用两个 alias 重复注册，root 自身及从已有
文件系统锚点到 root、从 root 到 artifact/receipt 的任一已有组件均不得是 symlink。相对路径必须是未
规范化前后完全一致的 POSIX 表示，拒绝 `.`、`..`、空段、反斜杠、盘符/UNC、控制字符和 `:`。
不同 root 允许按真实目录布局嵌套，但 verifier 必须以普通文件的稳定物理身份补充去重，拒绝同一现有文件
借由“父 root 相对路径/子 root 相对路径”或 hard-link 同时/重复进入 digest 集合。`receipt_path` 必须位于
至少一个显式 artifact root 内，其父目录必须已经存在且通过同一 no-symlink 目录校验；publish 不负责创建
任意未声明父目录。receipt 自引用在 inputs 与 outputs 任一侧都拒绝，并按物理文件身份判断，不能只比较
路径字符串。完整 `artifact_roots` 必须在读取任一 digest 前全部验真，不能只检查实际被引用的 root。

规范读取算法固定为 `read_bytes -> strict UTF-8 decode -> duplicate-aware JSON parse（parse_constant 拒绝）
-> strict object construction -> canonical encode -> 原始 bytes 精确比较`；BOM、CRLF、尾随换行和仅字段顺序
不同均非法。物理文件身份使用 `lstat` 后的 `(st_dev,st_ino)` 或 `os.path.samestat` 等价语义；不能用
`resolve()` 或内容 hash 冒充 hard-link 身份，无法可靠取得时 fail-closed。verify 必须先验证 root registry、
receipt containment、parent 与 leaf 的 lstat；只有 leaf 真正 ENOENT 才返回 `None`，dangling symlink 不是缺失。

消费者同时需要 parsed receipt 与 receipt hash 时，必须使用共享
`verify_stage_receipt_with_bytes`，不得在下游复制第二套 verifier。该入口对 receipt 使用同一
打开文件描述符完成读取、parse 和 hash，并复用本节完整 root registry 和 digest 物理身份契约。
嵌套 roots 从路径反推 alias 时选择包含该路径的最具体子 root；同一物理 root 的重复 alias
仍在任何 digest 读取前失败。

发布端不得以 `os.replace` 覆盖并发进程刚发布的 immutable receipt。固定流程为：同目录临时普通文件写入
并 `fsync`，再次验真声明 artifact，以 Linux/WSL 的原子 no-clobber 创建（例如同文件系统 `os.link`），
并发目标已存在时只允许“规范字节相同且现有 receipt 全量验真通过”复用，否则冲突失败；最后清理临时文件
并尽力 `fsync` 父目录。禁止回退到覆盖式 replace。单个 receipt 原子发布不等于多 artifact 跨文件事务，
artifact 在验真后被外部修改的 TOCTOU 仍由再次验真 fail-closed 暴露，交付报告不得夸大保证。
`os.link` 只有 `FileExistsError` 可进入并发复用分支；其他错误必须脱敏失败且不得 fallback。临时文件清理
失败不能覆盖主异常。父目录 fsync 只可忽略 `EINVAL/ENOTSUP/EOPNOTSUPP` 这类明确“不支持”错误；其他错误
以稳定消息失败。若 receipt 已原子创建后目录 fsync 才失败，文件保持原状，重试必须重新验真后复用。

编排骨架使用显式静态 DAG，不允许根据目录中“看起来存在”的文件动态猜依赖：

```python
@dataclass(frozen=True)
class OutputSpec:
    relative_path: str
    kind: Literal["FILE", "TREE"]
    closure_manifest: str | None

@dataclass(frozen=True)
class StageSpec:
    name: str
    scope: Literal[
        "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"
    ]
    dependencies: tuple[str, ...]
    outputs: tuple[OutputSpec, ...]

@dataclass(frozen=True)
class StaticDirectoryPublication:
    final_directory: str

@dataclass(frozen=True)
class SnapshotContentPublication:
    content_directory_parent: Literal["snapshots"]
    request_record_path: str
    manifest_relative_path: Literal["manifest.json"]
    content_id_field: Literal["snapshot_id"]

PublicationSpec = StaticDirectoryPublication | SnapshotContentPublication

@dataclass(frozen=True)
class ExternalInput:
    artifact: ArtifactDigest

@dataclass(frozen=True)
class StageOutputInput:
    producer_node_id: str
    root_alias: str
    relative_path: str

InputSpec = ExternalInput | StageOutputInput

@dataclass(frozen=True)
class StageNode:
    node_id: str
    spec_name: str
    scope: Literal[
        "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"
    ]
    scope_key: str
    fold: str | None
    horizon: int | None
    dependencies: tuple[str, ...]
    inputs: tuple[InputSpec, ...]
    publication: PublicationSpec
    output_specs: tuple[OutputSpec, ...]
    receipt_path: str

@dataclass(frozen=True)
class RunPlan:
    continuation: Literal["SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "SUMMARY"]
    nodes: tuple[StageNode, ...]

@dataclass(frozen=True)
class StageFailure:
    node_id: str
    scope: Literal[
        "SNAPSHOT", "PROVIDER", "EXPERIMENT", "WORK", "REPRO", "ACCEPTANCE"
    ]
    scope_key: str
    work_key: str | None
    fold: str | None
    horizon: int | None
    stage: str
    error_code: str
    message: str

@dataclass(frozen=True)
class RunSummary:
    snapshot_id: str | None
    provider_key: str | None
    experiment_key: str | None
    completed_node_ids: tuple[str, ...]
    reused_node_ids: tuple[str, ...]
    failures: tuple[StageFailure, ...]

def build_snapshot_plan(
    *, release: VerifiedG1Release, config: LoadedM3Config,
) -> RunPlan: ...

def build_provider_plan(
    *, snapshot: VerifiedSnapshotArtifact, config: LoadedM3Config,
) -> RunPlan: ...

def build_experiment_plan(
    *, snapshot: VerifiedSnapshotArtifact, provider: VerifiedProviderArtifact,
    provider_validation: VerifiedProviderValidationArtifact,
    config: LoadedM3Config,
) -> RunPlan: ...

def build_work_plan(
    *, experiment: VerifiedExperimentIdentity,
    folds: VerifiedFoldPlanArtifact,
    labels: Sequence[VerifiedLabelArtifact],
    config: LoadedM3Config,
) -> RunPlan: ...

def build_summary_plan(
    *, experiment: VerifiedExperimentIdentity,
    evaluations: Sequence[VerifiedEvaluationArtifact],
    config: LoadedM3Config,
) -> RunPlan: ...

def execute_m3_plan(
    *, plan: RunPlan, config: LoadedM3Config,
    handlers: Mapping[str, StageHandler],
    artifact_roots: Mapping[str, Path], resume: bool,
) -> RunSummary: ...
```

`StageSpec` 是唯一的 stage 类型 registry；`StageNode` 是完全解析后的执行实例。`node_id` 在整个 plan 内
唯一，依赖引用 node_id，fold/horizon 不得偷偷编码进 experiment key。计划构造时校验 DAG 无环、stage-owned
输出目录无嵌套/冲突、所有输入都有显式 producer 或受信外部 digest。continuation 边界外输入必须使用
`ExternalInput`；同一 plan 内尚未产生的输入使用 `StageOutputInput`，runner 执行时从 producer 的已验真
receipt 解析实际 digest，禁止 builder 或调用者预填未知 hash。handler 只接收解析后的 inputs 与空临时目录，
禁止自行扫描 artifact tree。`node_id` 只允许小写 ASCII 字母、数字、点、下划线和连字符；每个 producer
引用必须同时出现在 dependencies 中，且路径被 producer output spec 覆盖。receipt 固定在 output directory
外的同 scope `receipts/` 目录。目录型 output 在 plan 中解析到唯一受控目录；发布 receipt 时必须递归列出其中
每个普通文件，拒绝符号链接和未声明目录外产物，不能只对目录名做 hash。fold 定义只来自已验真的
`VerifiedFoldPlanArtifact`；experiment plan 只发布 labels/folds 共享证据，不枚举 work。只有 folds artifact
验真后才能构造 work plan。若解析结果与已发布文件不一致，必须因 receipt/input hash 冲突失败。计划构造函数是纯函数，
CLI 在构造任何 plan 前恰调用一次 `load_m3_config`；runner 与 handler 只接收同一个
`LoadedM3Config`/只读 section，不再打开配置路径。
不得调用 stage handler 或扫描目录，因此不存在把未发布对象当作规划前置的循环。

StageRunner 验证 receipt 时不仅复算 receipt 自报文件的 hash，还必须把 receipt 的 stage/scope/scope_key、
解析后的 inputs、逐文件 outputs 与对应 `StageNode` 的期望闭包逐项比较；合法 hash 但漏 required output、
换 scope key 或增加未声明输入同样失败。每个多文件 stage 独占最终目录；runner 持有
`(scope,scope_key,node_id)` 的 WSL `flock`，锁内复验后用 Linux/WSL
`renameat2(RENAME_NOREPLACE)` 或语义等价 primitive 原子发布整个目录，再 fsync parent、最后发布 receipt。
运行时不支持目录级 no-clobber 时 fail-closed；禁止回退到 `os.rename`、逐文件 merge 或覆盖式发布。

受信只读 root alias 至少包含 `CONFIG`（版本化 M3 配置）、`G1_RELEASE`（已验真 clean release）和
`EXTERNAL_QLIB`（固定 `dump_bin.py`）；运行期另注入 `SNAPSHOT/PROVIDER/EXPERIMENT/WORK/REPRO/
ACCEPTANCE`。provider handler 不隐式联网，D8/显式供应链命令先下载，provider StageNode 再把脚本作为
digest 输入。稳定产物与最小 required-input 闭包如下；receipt 必须精确列出本行全部输入和输出：

| Scope/stage | Required inputs | Required outputs |
|---|---|---|
| snapshot/readiness | `CONFIG`；`G1_RELEASE:{manifest,bars,benchmark,membership,calendar,instruments}` | `readiness.json` |
| snapshot/snapshot | readiness receipt；`CONFIG` narrow hash；上述 G1 文件 | `manifest.json`, `session_calendar.parquet`, `staging/*.parquet` |
| provider/provider | `EXTERNAL_QLIB:dump_bin.py`；snapshot receipt、manifest、calendar、全部 staging | `provider/**`, `provider_manifest.json` |
| provider/provider_validation | provider receipt/manifest/全部 provider tree；snapshot manifest/calendar/全部 staging | `provider-validation/key=<provider_validation_key>/{provider_validation.parquet,provider_validation.json}` |
| experiment/experiment_identity | snapshot/provider receipts 与 manifests；scientific/dependency identities；provider-validation PASS 仅作编排前置、不列内容 input | `experiment_manifest.json` |
| experiment/labels[h] | experiment manifest；`G1_RELEASE:{manifest,bars,benchmark,eligible_keys}`；snapshot calendar | `labels/horizon=<h>/{labels.parquet,diagnostics.parquet,label_manifest.json}` |
| experiment/label_reconciliation[h] | experiment receipt/manifest；`G1_RELEASE:{manifest,benchmark}`；snapshot receipt/manifest/session calendar；provider receipt/manifest/严格完整 tree；provider-validation receipt/summary/details；label receipt/manifest/labels/diagnostics | `labels/horizon=<h>/reconciliation/key=<reconciliation_key>/{reconciliation.parquet,reconciliation.json}` |
| experiment/folds | verified experiment；verified snapshot calendar；walk-forward config identity | strict `folds.json` |
| experiment/features[fold] | verified provider/folds/G1 eligible keys；feature config identity；provider-validation PASS 仅作编排前置、不列内容 input | `features/fold=<fold>/{train,validation,test}.parquet`, `feature_manifest.json`, `coverage.parquet` |
| work/alignment | verified feature；对应 horizon verified label；verified fold | `alignment/{train,validation}.parquet`, `alignment_manifest.json`, `diagnostics.parquet` |
| work/train | verified alignment/feature/label/experiment；model config/dependency identities | `train/{model.txt,model.metadata.json,validation_curve.parquet}` |
| work/predictions | verified model；verified test feature/fold/eligibility | `predictions/{predictions.parquet,prediction_manifest.json}` |
| work/evaluation | verified prediction/label/feature/fold；G1 eligible keys | `evaluation/{daily_ic.parquet,metrics.json,evaluation_manifest.json}` |
| work/targets | verified prediction/feature/fold；G1 eligibility/domain；scientific config identity | `targets/{target_weights.parquet,target_daily.parquet,target_manifest.json}` |
| work/backtest_plan | verified target/fold/G1 calendar；window/cost/backtest identities | `backtest_plan/{scheduled_targets,schedule_diagnostics}.parquet`, `cost_schedule.json`, `manifest.json` |
| work/backtest | verified target/backtest plan；`G1_RELEASE` market facts/benchmark/manifest | `backtest/scenario={0p5x,1p0x,2p0x}/{nav,trades,positions,rejections,postings,diagnostics,entitlements}.parquet`、每场景 `metrics.json`/`manifest.json`、根 `backtest_metrics.json`/`backtest_manifest.json` |
| work/tracking | 本 work 全部需登记的已验真 artifacts；tracking target identity | `tracking/target=<tracking_target_key>/{request.json,marker.json}` |
| experiment/research_summary[h] | 该 horizon 全部 verified evaluations，test dates 不重叠 | `summary/horizon=<h>/{daily_ic,fold_metrics}.parquet`, `metrics.json`, `manifest.json` |
| repro/comparison | 已验真 provider/features/labels/alignment；work/config/code/dependency identities；禁止读取正常 work model | `repro/<comparison_key>/attempt={1,2}/{model.txt,model.metadata.json,predictions.parquet,prediction_manifest.json,daily_ic.parquet,metrics.json,read_audit.json}`、根 `reproducibility.json` |
| acceptance/quality | source/test trees、版本化配置、code/dependency identities | `acceptance/quality/<quality_key>/{quality_report.json,pytest.log,ruff.log,mypy.log,import_isolation.json}` |
| acceptance/final | 预期 DAG 的全部 receipts/manifests、tracking markers、repro comparisons、quality receipt 与 acceptance config identity | `acceptance/final/<acceptance_key>/acceptance_report.json` |

`labels[h]` 可以在 folds 间共享但不同 horizon 不得混文件；Alpha158 feature bundle 依赖 fold 但不依赖
horizon，因此每 fold 只生成一次；supervised alignment 才依赖 horizon/work。任何共享产物的失败只阻止
真实依赖 work。stage runner
只能接收 `StageSpec` 中声明的输入路径；测试使用 fake runner 记录 open/read 路径，发现未声明读取即失败。

同一缓存的成功复用不能证明 G5/G9 冷启动可复现。CLI 另提供 `verify-reproducibility`：由父编排器启动
两个顺序执行的全新 WSL Miniforge base Python 子进程，在独立
`repro/<comparison_key>/attempt=1|2/` 下复用已验真的 snapshot/provider/features，但强制重新训练、预测
和评估。两个子进程使用 attempt 专属临时/cache 目录和显式确定性环境，不能共享 Python 对象、Qlib/
LightGBM 进程内缓存，也不读取正常 work 的 model/predictions；比较行键、score 和 metrics 后发布 comparison receipt。
两个 attempt 任一失败、读到对方产物或容差超限都不通过。

所有新 JSON manifest、report 和 receipt 必须有稳定 `schema_version`（stage receipt 固定
`m3-stage-receipt-v1`），使用规范 JSON 且禁止 NaN/Infinity、时间戳、本机绝对路径和凭据。版本未知时
fail-closed，不能按“字段差不多”继续读取。

### 4.9.1 `quality_gate.py` 和 `acceptance.py`

G9 不是“再跑一次测试”的别名，而是验证 G0–G8 的全部证据确实形成同一条身份闭包。验收模块只编排
生产模块自己的 artifact validator 和 `verify_stage_receipt`，不得复制标签、IC、账户或费用公式。

```python
@dataclass(frozen=True)
class QualityCheckResultV1:
    name: Literal["pytest", "ruff", "mypy", "import_isolation"]
    logical_argv: tuple[str, ...]
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str

@dataclass(frozen=True)
class QualityReportV1:
    schema_version: Literal["m3-quality-report-v1"]
    quality_key: str
    command_policy_version: Literal["m3-quality-commands-v1"]
    code_version: str
    dependency_fingerprint_sha256: str
    checks: tuple[QualityCheckResultV1, ...]
    passed: Literal[True]

@dataclass(frozen=True)
class VerifiedQualityArtifact:
    report: QualityReportV1
    report_digest: ArtifactDigest
    receipt: StageReceipt
    receipt_sha256: str

GateName = Literal["G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9"]

@dataclass(frozen=True)
class EvidenceLocatorV1:
    gate: GateName
    node_id: str
    expected_stage: str
    expected_scope: Scope
    expected_scope_key: str
    root_alias: str
    receipt_relative_path: str

@dataclass(frozen=True)
class AcceptanceIssueV1:
    gate: GateName
    code: str
    subject: str
    evidence: tuple[ArtifactDigest, ...]

@dataclass(frozen=True)
class GateResultV1:
    gate: GateName
    status: Literal["PASS", "FAIL"]
    issues: tuple[AcceptanceIssueV1, ...]
    evidence: tuple[ArtifactDigest, ...]

@dataclass(frozen=True)
class VerifiedRuntimeIdentity:
    code_version: str
    provider_runtime_fingerprint_sha256: str
    dependency_fingerprint_sha256: str
    full_config_sha256: str
    readiness_receipt_sha256: str

@dataclass(frozen=True)
class VerifiedAcceptanceSubject:
    snapshot: VerifiedSnapshotArtifact
    provider: VerifiedProviderArtifact
    provider_validation: VerifiedProviderValidationArtifact
    experiment: VerifiedExperimentIdentity
    folds: VerifiedFoldPlanArtifact
    runtime: VerifiedRuntimeIdentity

@dataclass(frozen=True)
class AcceptanceEvidencePlanV1:
    schema_version: Literal["m3-acceptance-evidence-plan-v1"]
    snapshot_id: str
    provider_key: str
    experiment_key: str
    expected_work_keys: tuple[str, ...]
    expected_comparison_keys: tuple[str, ...]
    evidence: tuple[EvidenceLocatorV1, ...]

@dataclass(frozen=True)
class RemoteTrackingObservationV1:
    work_key: str
    tracking_target_key: str
    tracking_key: str
    run_id: str
    status: Literal["FINISHED"]
    request_sha256: str
    artifact_digest_sha256: str

@dataclass(frozen=True)
class AcceptanceDecisionV1:
    schema_version: Literal["m3-acceptance-report-v1"]
    acceptance_key: str
    experiment_key: str
    acceptance_config_sha256: str
    code_version: str
    dependency_fingerprint_sha256: str
    tracking_target_key: str
    tracking_observations_sha256: str
    gate_results: tuple[GateResultV1, ...]
    overall_status: Literal["PASS", "FAIL"]

def build_acceptance_evidence_plan(
    *, subject: VerifiedAcceptanceSubject, config: LoadedM3Config,
) -> AcceptanceEvidencePlanV1: ...

def audit_m3_acceptance(
    *, subject: VerifiedAcceptanceSubject, plan: AcceptanceEvidencePlanV1,
    quality: VerifiedQualityArtifact, config: LoadedM3Config,
    artifact_roots: Mapping[str, Path], tracking_verifier: TrackingVerifier,
) -> AcceptanceDecisionV1: ...
```

G9A quality handler 只以 `shell=False` 顺序运行当前 WSL Python 的固定 argv：`python -m pytest -q`、
`python -m ruff check src tests`、`python -m mypy src`，并以新子进程执行核心 import/重依赖隔离审计。
不得执行配置提供的命令、调用网络或记录 Python
绝对路径；日志将 workspace/Python 前缀规范化为 `<WORKSPACE>`/`<PYTHON>` 后写入临时 acceptance 目录。
执行前后重算 code、dependency 与版本化配置 identity，任一漂移都失败。四项全为 0、实际 dependency
fingerprint 与 experiment 完全一致时才发布 quality receipt；失败只返回脱敏诊断，
不得发布成功 receipt。

`resolve_acceptance_subject` 从已验真的 snapshot、当前配置、code/dependency fingerprint 重算 provider key 和
experiment key，调用者提供的 snapshot ID 只用于定位，不能信任目录名或 manifest 自报 identity。
`build_acceptance_evidence_plan` 再使用 G8 的 plan builder/StageSpec registry 枚举明确 receipt locator；
生产函数内部调用唯一 `get_m3_stage_registry()`，不得由 CLI/调用者注入另一份 Mapping。
禁止扫描目录猜 work。每个期望 fold×horizon 必须恰有一个 work、tracking marker
和独立进程 comparison receipt，每个 horizon 必须恰有一个 research summary。额外的非权威文件不自动
成为证据，缺失、重复、跨 experiment 混用或损坏 receipt 均失败。

`audit_m3_acceptance` 收集全部可判定问题而不是首错退出，并验证：G0 readiness/实际依赖；G1 release 与
snapshot；G2 provider 全量结构、60 emitted keys/420 comparisons 与另计 gap；G3 每 horizon label reconciliation；G4 folds；G5 每 work 冷启动 comparison；
G6 每 work evaluation、每 horizon summary 和 coverage 阈值；G7 完整 targets、三档 backtest manifest 与
required metrics；G8 receipt 闭包与 tracking marker；G9 当前 code/dependency 对应的四项质量检查。所有
manifest 的 snapshot/provider/experiment/work/fold/horizon/model/feature/label/target hashes 必须沿链一致。

coverage、可计算日期比例和复现容差只从 `config.acceptance` 读取并逐 work 检查，不能用 pooled 结果
掩盖坏 fold。required metric 使用限定来源名：`evaluation.test_rank_ic`、`evaluation.test_rank_icir`、
`backtest.1p0x.test_net_excess_return`、`backtest.1p0x.test_turnover`、
`backtest.1p0x.test_max_drawdown`。前两者只投影当前 work 的 `EvaluationMetricsV1.rank_ic_mean/rank_icir`，
后三者只投影当前 work `BacktestMetricsV1` 中 `scenario=1p0x` 的同名字段；禁止动态去前缀、用 summary
替代、跨 work pooled 或从 0.5×/2× 回退。负收益或负 IC 本身不是工程失败。threshold 改变形成新 acceptance key，
不改变 experiment。`acceptance_key` 规范 hash experiment key、acceptance config hash、tracking target key、
quality receipt hash、remote tracking observations hash 和所有有序 required receipt hash。只有十个 Gate 全 PASS 才原子发布 `acceptance_report.json` 与
ACCEPTANCE receipt；FAIL 报告只输出到 stdout，不写可被误认为晋级证据的 complete receipt。验收通过
不自动修改路线图，仍需主 Agent 终验后更新。

G8 tracking validator 在 G9 时必须连接当前 tracking target，确认每个 work 恰有一个相同
`quant_tracking_key` 的 `FINISHED` run，request/artifact hash 与本地 marker 完全一致；仅有 marker 文件
不能证明 G8 当前仍闭合。远端 query 的规范最小观察值进入 acceptance report 与 identity；网络/认证错误
是 G8 FAIL，不得 SKIP。artifact/manifest/receipt 只对 evidence plan 引用的限定文件做 secret/path scan，
不扫描工作区、`archive/legacy_pre_greenfield/`、`data/legacy/` 或计划外目录。

### 4.10 `index_membership.py` 和 `m3_backfill.py`

```python
class TushareConnector:
    def fetch_index_weight_raw(
        self, *, index_code: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame: ...
    def fetch_daily_raw(
        self, *, symbol: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame: ...
    def fetch_adj_factor_raw(
        self, *, symbol: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame: ...
    def fetch_index_daily_raw(
        self, *, index_code: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame: ...
    def fetch_suspend_raw(
        self, *, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame: ...
    def fetch_stk_limit_raw(
        self, *, symbol: str, start: dt.date, end: dt.date, fields: str
    ) -> pl.DataFrame: ...
    def fetch_dividend_raw(
        self, *, symbol: str, fields: str
    ) -> pl.DataFrame: ...

@dataclass(frozen=True)
class TushareRequestSpec:
    schema_version: Literal["m3-g1-tushare-request-v1"]
    request_id: str
    endpoint: Literal[
        "index_weight", "daily", "adj_factor", "index_daily", "suspend_d",
        "stk_limit", "dividend",
    ]
    parameters: tuple[tuple[str, str], ...]

    @classmethod
    def create(
        cls, *, endpoint: str, parameters: Mapping[str, str]
    ) -> "TushareRequestSpec": ...

@dataclass(frozen=True)
class EndpointPolicy:
    row_limit: int
    empty_response: Literal["ALLOW", "REJECT"]

@dataclass(frozen=True)
class TushareRequestBatch:
    schema_version: Literal["m3-g1-tushare-request-batch-v1"]
    phase: Literal["INDEX_WEIGHT", "HISTORY"]
    requests: tuple[TushareRequestSpec, ...]
    batch_sha256: str

@dataclass(frozen=True)
class G1RequestPlan:
    schema_version: Literal["m3-g1-request-plan-v1"]
    index_weight_batch: TushareRequestBatch
    history_batch: TushareRequestBatch
    plan_sha256: str

@dataclass(frozen=True)
class TushareRequestIntentV1:
    schema_version: Literal["m3-g1-tushare-intent-v1"]
    request_id: str
    endpoint: str
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str

@dataclass(frozen=True)
class TushareRawCandidateV1:
    schema_version: Literal["m3-g1-tushare-candidate-v1"]
    request_id: str
    endpoint: str
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

@dataclass(frozen=True)
class TushareRequestReceipt:
    schema_version: Literal["m3-g1-tushare-receipt-v1"]
    request_id: str
    endpoint: str
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    stable_response_sha256: str
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

@dataclass(frozen=True)
class VerifiedRawResponse:
    spec: TushareRequestSpec
    receipt: TushareRequestReceipt
    receipt_sha256: str
    frame: pl.DataFrame

class M3G1MappingError(ValueError):
    code: str

def map_g1_daily_response(*, response: VerifiedRawResponse) -> pl.DataFrame: ...
def map_g1_adjustment_factor_response(
    *, response: VerifiedRawResponse
) -> pl.DataFrame: ...
def map_g1_benchmark_response(
    *,
    fund_daily: VerifiedRawResponse,
    fund_adj_segments: Sequence[VerifiedRawResponse],
    fund_div: VerifiedRawResponse,
    factor_ratio_rtol: float,
) -> pl.DataFrame: ...
def map_g1_suspension_response(*, response: VerifiedRawResponse) -> pl.DataFrame: ...

@dataclass(frozen=True)
class ReferenceRequestSpec:
    schema_version: Literal["m3-g1-baostock-request-v1"]
    request_id: str
    endpoint: Literal["query_history_k_data_plus"]
    symbol: str
    parameters: tuple[tuple[str, str], ...]

@dataclass(frozen=True)
class ReferenceRequestPlanV1:
    schema_version: Literal["m3-g1-baostock-request-plan-v1"]
    sample_plan_sha256: str
    requests: tuple[ReferenceRequestSpec, ...]
    request_plan_sha256: str

@dataclass(frozen=True)
class ReferenceRequestIntentV1:
    schema_version: Literal["m3-g1-baostock-intent-v1"]
    request_id: str
    endpoint: Literal["query_history_k_data_plus"]
    symbol: str
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str

@dataclass(frozen=True)
class ReferenceRawCandidateV1:
    schema_version: Literal["m3-g1-baostock-candidate-v1"]
    request_id: str
    endpoint: Literal["query_history_k_data_plus"]
    symbol: str
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

@dataclass(frozen=True)
class ReferenceRequestReceipt:
    schema_version: Literal["m3-g1-baostock-receipt-v1"]
    request_id: str
    endpoint: Literal["query_history_k_data_plus"]
    symbol: str
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    stable_response_sha256: str
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

@dataclass(frozen=True)
class VerifiedReferenceResponse:
    spec: ReferenceRequestSpec
    receipt: ReferenceRequestReceipt
    receipt_sha256: str
    frame: pl.DataFrame

@dataclass(frozen=True)
class AdjustmentApplicationResult:
    bars: pl.DataFrame
    factor_match_evidence: pl.DataFrame

@dataclass(frozen=True)
class HistoryWindow:
    start: dt.date
    end: dt.date

@dataclass(frozen=True)
class G1QualityIssue:
    code: str
    severity: Literal["ERROR", "WARNING"]
    message: str
    count: int
    evidence: tuple[str, ...]

@dataclass(frozen=True)
class ObservedMembershipResult:
    observations: pl.DataFrame
    membership: pl.DataFrame
    eligible_keys: pl.DataFrame
    observations_sha256: str
    membership_sha256: str
    eligible_keys_sha256: str

@dataclass(frozen=True)
class CorporateActionSelectionResult:
    ledger: pl.DataFrame
    selection_evidence: pl.DataFrame
    ledger_sha256: str
    selection_evidence_sha256: str

@dataclass(frozen=True)
class CorporateActionReconciliationResult:
    evidence: pl.DataFrame
    evidence_sha256: str

@dataclass(frozen=True)
class G1BuildSpec:
    config_version: str
    g1_config_sha256: str
    mapper_version: str
    schema_version: str
    membership_method_version: str
    price_limit_method_version: str
    corporate_action_selection_version: str
    corporate_action_reconciliation_version: str
    build_code_version: str
    dependency_fingerprint_sha256: str

@dataclass(frozen=True)
class G1BuildInputs:
    build_spec: G1BuildSpec
    request_plan: G1RequestPlan
    responses: tuple[VerifiedRawResponse, ...]
    calendars: pl.DataFrame
    instruments: pl.DataFrame
    universe: Literal["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"]
    signal_start: dt.date
    signal_end: dt.date
    history: HistoryWindow
    expected_constituent_count: int
    factor_ratio_rtol: float

@dataclass(frozen=True)
class G1ReceiptProjectionV1:
    source: Literal["tushare", "baostock"]
    request_id: str
    endpoint: str
    parameters_sha256: str
    stable_response_sha256: str
    row_count: int
    columns: tuple[str, ...]

@dataclass(frozen=True)
class G1Candidate:
    build_spec: G1BuildSpec
    request_plan: G1RequestPlan
    signal_start: dt.date
    signal_end: dt.date
    history_start: dt.date
    history_end: dt.date
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    calendars: pl.DataFrame
    instruments: pl.DataFrame
    observations: pl.DataFrame
    membership: pl.DataFrame
    eligible_keys: pl.DataFrame
    bars: pl.DataFrame
    adjustment_factors: pl.DataFrame
    factor_match_evidence: pl.DataFrame
    benchmark_bars: pl.DataFrame
    suspensions: pl.DataFrame
    price_limits: pl.DataFrame
    corporate_actions: pl.DataFrame
    corporate_action_selection_evidence: pl.DataFrame
    corporate_action_reconciliation: pl.DataFrame
    table_content_digests: tuple[tuple[str, str], ...]
    price_limit_required_keys_sha256: str
    primary_candidate_key: str

@dataclass(frozen=True)
class CrossSourceSamplePlan:
    schema_version: Literal["m3-g1-cross-source-sample-v1"]
    primary_candidate_key: str
    sample_symbols: Literal[30]
    dates_per_symbol: Literal[20]
    keys: tuple[tuple[str, dt.date], ...]
    sample_plan_sha256: str

@dataclass(frozen=True)
class CrossSourceReconciliationBundle:
    sample_plan: CrossSourceSamplePlan
    reference_receipts: tuple[G1ReceiptProjectionV1, ...]
    detail: pl.DataFrame
    detail_sha256: str
    summary: CrossSourceSummaryV1
    summary_sha256: str
    issues: tuple[G1QualityIssue, ...]
    passed: bool

@dataclass(frozen=True)
class G1PrimaryAuditResult:
    primary_candidate_key: str
    plan_sha256: str
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    table_content_digests: tuple[tuple[str, str], ...]
    issues: tuple[G1QualityIssue, ...]
    passed: bool

@dataclass(frozen=True)
class G1ArtifactEntryV1:
    path: str
    sha256: str
    content_sha256: str
    size_bytes: int
    row_count: int
    schema_name: str
    table_schema_version: str
    key_columns: tuple[str, ...]
    min_key: tuple[str, ...] | None
    max_key: tuple[str, ...] | None

@dataclass(frozen=True)
class G1QualityIssueV1:
    code: str
    severity: Literal["ERROR", "WARNING"]
    message: str
    count: int
    evidence: tuple[str, ...]

@dataclass(frozen=True)
class G1QualityReportV1:
    schema_version: Literal["m3-g1-quality-v1"]
    release_id: str
    primary_candidate_key: str
    plan_sha256: str
    error_count: int
    warning_count: int
    passed: bool
    issues: tuple[G1QualityIssueV1, ...]

@dataclass(frozen=True)
class CrossSourceFieldStatsV1:
    field: Literal["open", "high", "low", "close", "volume"]
    comparison_count: int
    mismatch_count: int
    max_abs_diff: float
    max_relative_diff: float

@dataclass(frozen=True)
class CrossSourceSummaryV1:
    schema_version: Literal["m3-g1-cross-source-v1"]
    primary_candidate_key: str
    sample_plan_sha256: str
    sample_symbol_count: int
    dates_per_symbol: int
    key_count: int
    field_count: int
    comparison_count: int
    primary_receipt_digests: tuple[str, ...]
    reference_receipt_digests: tuple[str, ...]
    price_atol: float
    price_rtol: float
    volume_rtol: float
    max_mismatch_rate: float
    missing_primary_rows: int
    missing_reference_rows: int
    mismatch_cells: int
    mismatch_rate: float
    field_stats: tuple[CrossSourceFieldStatsV1, ...]
    detail_sha256: str
    passed: bool

@dataclass(frozen=True)
class G1ManifestV1:
    schema_version: Literal["m3-g1-manifest-v1"]
    release_id: str
    primary_candidate_key: str
    config_version: str
    g1_config_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    history_start: dt.date
    history_end: dt.date
    request_plan_sha256: str
    build_code_version: str
    dependency_fingerprint_sha256: str
    mapper_version: str
    clean_schema_version: str
    membership_method_version: str
    price_limit_method_version: str
    corporate_action_selection_version: str
    corporate_action_reconciliation_version: str
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    price_limit_required_keys_sha256: str
    sample_plan_sha256: str
    cross_source_summary_sha256: str
    quality_sha256: str
    files: tuple[G1ArtifactEntryV1, ...]

@dataclass(frozen=True)
class G1Release:
    release_id: str
    root: Path
    manifest_path: Path
    quality_path: Path

@dataclass(frozen=True)
class G1CrossSourcePolicy:
    reference_source: Literal["baostock"]
    sample_symbols: Literal[30]
    dates_per_symbol: Literal[20]
    price_atol: float
    price_rtol: float
    volume_rtol: float
    max_mismatch_rate: float

@dataclass(frozen=True)
class G1ReleaseInputs:
    build_inputs: G1BuildInputs
    cross_source_policy: G1CrossSourcePolicy
    reference_responses: tuple[VerifiedReferenceResponse, ...]

@dataclass(frozen=True)
class G1PreparedRelease:
    candidate: G1Candidate
    primary_audit: G1PrimaryAuditResult
    reconciliation: CrossSourceReconciliationBundle
    release_id: str
    quality: G1QualityReportV1

@dataclass(frozen=True)
class VerifiedG1Release:
    release: G1Release
    manifest: G1ManifestV1
    manifest_sha256: str
    quality: G1QualityReportV1
    quality_sha256: str
    artifact_paths: tuple[tuple[str, Path], ...]

def plan_index_weight_requests(
    *, index_code: str, start: dt.date, end: dt.date, warmup_months: int,
) -> TushareRequestBatch: ...

def resolve_history_window(
    *, open_dates: Sequence[dt.date], signal_start: dt.date, signal_end: dt.date,
    feature_warmup_sessions: int, label_tail_sessions: int,
) -> HistoryWindow: ...

def plan_history_requests(
    *, index_weight_batch: TushareRequestBatch, symbols: Sequence[str],
    benchmark: str, history: HistoryWindow,
) -> G1RequestPlan: ...

def execute_tushare_batch(
    *, batch: TushareRequestBatch, connector: TushareConnector,
    raw_store: RawStore, journal_root: Path,
    endpoint_policies: Mapping[str, EndpointPolicy],
    request_rate_per_minute: int, max_attempts: int, retry_base_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    classify_error: Callable[[BaseException], str],
) -> tuple[TushareRequestReceipt, ...]: ...

def verify_tushare_receipt(
    *, spec: TushareRequestSpec, receipt_path: Path, raw_root: Path,
    journal_root: Path, policy: EndpointPolicy,
) -> VerifiedRawResponse: ...

def normalize_index_weight_observations(
    *, batch: TushareRequestBatch,
    responses: Sequence[VerifiedRawResponse], universe: str,
) -> pl.DataFrame: ...

def apply_adjustment_factors_strict(
    *, bars: pl.DataFrame, adjustment_factors: pl.DataFrame,
    daily_responses: Sequence[VerifiedRawResponse],
    factor_responses: Sequence[VerifiedRawResponse],
) -> AdjustmentApplicationResult: ...

def build_observed_membership(
    *, observations: pl.DataFrame, calendars: pl.DataFrame,
    instruments: pl.DataFrame, universe: str,
    signal_start: dt.date, signal_end: dt.date,
    expected_constituent_count: int,
) -> ObservedMembershipResult: ...

def verify_observed_membership_result(
    *, batch: TushareRequestBatch,
    responses: Sequence[VerifiedRawResponse],
    result: ObservedMembershipResult,
    calendars: pl.DataFrame,
    instruments: pl.DataFrame,
    universe: str,
    signal_start: dt.date,
    signal_end: dt.date,
    expected_constituent_count: int,
) -> None: ...

def clean_table_content_sha256(
    *, table_name: str, frame: pl.DataFrame,
) -> str: ...

def map_g1_price_limit_response(
    *, response: VerifiedRawResponse,
) -> pl.DataFrame: ...

def require_g1_price_limit_coverage(
    *, price_limits: pl.DataFrame, eligible_keys: pl.DataFrame,
    suspensions: pl.DataFrame, calendars: pl.DataFrame,
    instruments: pl.DataFrame,
    history: HistoryWindow,
) -> pl.DataFrame: ...

def select_g1_corporate_actions(
    *, response: VerifiedRawResponse, history: HistoryWindow,
) -> CorporateActionSelectionResult: ...

def reconcile_g1_corporate_actions(
    *, corporate_actions: pl.DataFrame, bars: pl.DataFrame,
    adjustment_factors: pl.DataFrame,
    daily_responses: Sequence[VerifiedRawResponse],
    suspensions: pl.DataFrame, calendars: pl.DataFrame,
    history: HistoryWindow, factor_ratio_rtol: float,
) -> CorporateActionReconciliationResult: ...

def build_g1_candidate(
    *, inputs: G1BuildInputs,
) -> G1Candidate: ...

def verify_g1_candidate(
    *, inputs: G1BuildInputs, candidate: G1Candidate,
) -> None: ...

def plan_cross_source_reconciliation(
    *, candidate: G1Candidate, policy: G1CrossSourcePolicy,
) -> CrossSourceSamplePlan: ...

def plan_baostock_reference_requests(
    *, sample_plan: CrossSourceSamplePlan,
) -> ReferenceRequestPlanV1: ...

def execute_baostock_reference_plan(
    *, sample_plan: CrossSourceSamplePlan, plan: ReferenceRequestPlanV1,
    connector: BaostockConnector,
    raw_store: RawStore, journal_root: Path,
) -> tuple[ReferenceRequestReceipt, ...]: ...

def verify_reference_receipt(
    *, spec: ReferenceRequestSpec, receipt_path: Path,
    raw_root: Path, journal_root: Path,
) -> VerifiedReferenceResponse: ...

def reconcile_cross_source(
    *, candidate: G1Candidate, sample_plan: CrossSourceSamplePlan,
    reference_responses: Sequence[VerifiedReferenceResponse],
    policy: G1CrossSourcePolicy,
) -> CrossSourceReconciliationBundle: ...

def audit_g1_candidate(
    *, candidate: G1Candidate,
) -> G1PrimaryAuditResult: ...

def prepare_g1_release(
    *, inputs: G1ReleaseInputs,
) -> G1PreparedRelease: ...

def publish_g1_release(
    *, output_root: Path, inputs: G1ReleaseInputs,
) -> G1Release: ...

def verify_g1_release(*, release: G1Release) -> VerifiedG1Release: ...

def read_g1_manifest(path: Path) -> G1ManifestV1: ...
def read_g1_quality(path: Path) -> G1QualityReportV1: ...
def read_cross_source_summary(path: Path) -> CrossSourceSummaryV1: ...
```

标准化观察与基准行情必须使用领域 Schema，而不是散落在 mapper 中的临时列约定：

```python
class IndexConstituentObservationSchema(pa.DataFrameModel):
    universe: str  # CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1
    observation_date: pl.Date
    symbol: str  # 六位 .SH/.SZ A 股代码
    weight: float  # 正且 finite
    source: str  # tushare
    source_snapshot_id: str  # 小写 64 位 hex

class BenchmarkBar1dSchema(pa.DataFrameModel):
    benchmark: str
    trade_date: pl.Date
    open: float
    high: float
    low: float
    close: float
    source: str
    source_snapshot_id: str
```

G1 核心 mapper 首版固定放在 `quant.data.m3_mappers`，只接受 B2A 的 `VerifiedRawResponse`，不接受裸
DataFrame、调用方自报 symbol/source/snapshot 或配置路径。四个函数输出列顺序与语义固定为：

| 函数 | endpoint | 精确输出列 |
|---|---|---|
| `map_g1_daily_response` | `daily` | `symbol,trade_date,open,high,low,close,volume,amount,source` |
| `map_g1_adjustment_factor_response` | `adj_factor` | `symbol,effective_date,adj_factor,source` |
| `map_g1_benchmark_response` | `fund_daily` + 分段 `fund_adj` + `fund_div` | `benchmark,trade_date,open,high,low,close,source,source_snapshot_id` |
| `map_g1_suspension_response` | `suspend_d` | `symbol,trade_date,suspension_scope,suspension_detail,source,source_snapshot_id` |

`daily` 输出是尚未拼接 factor 的 G1 内部表，不得伪造 `adj_factor=1.0`；B4 的
`apply_adjustment_factors_strict` 才生成通过 `Bar1dSchema` 的最终表和 factor-match evidence。
`adj_factor` 输出必须逐供应商交易日保留，即使相邻值相同也不得压缩。前两张表没有逐行
`source_snapshot_id` 字段，其血缘由 `G1Candidate.input_receipts`、factor-match evidence 与 manifest 的精确
receipt 闭包绑定；不得为
“看起来统一”而修改现有 `Bar1dSchema/AdjustmentFactorSchema`。基准和停牌 Schema 已有该字段，值必须来自
`response.receipt.raw_snapshot_id`。四张表的 `source` 固定为 `tushare`，调用方不可覆盖。

mapper 必须在读取行值前重建并重验 exact `VerifiedRawResponse`：使用生产构造边界重新证明 spec 的规范
request identity、receipt 与 spec 的 endpoint/parameters/fields/columns/row count 闭包、规范 receipt bytes
hash，以及 frame 的 columns/row count/content digest。`frozen=True` 和对象曾经构造成功不能代替消费时
identity 闭包；重验失败统一脱敏为 `G1_MAPPER_RESPONSE_INVALID`。闭包通过后再核对 endpoint、请求参数与
响应范围。逐证券 endpoint 的每个 `ts_code` 必须等于 spec 的 `ts_code`；基准首版只允许
`510300.SH`；A 股代码只允许六位数字加 `.SH/.SZ`。日期严格解析 `YYYYMMDD`，数值 strict cast，拒绝
null/NaN/Infinity、非法 OHLC、负 volume/amount、非正 factor、响应越过请求日期范围和不可规范化代码。
Tushare `vol` 从手换算为股（`*100`），`amount` 从千元换算为元（`*1000`）。

`daily/adj_factor/index_daily` 的业务键重复必须拒绝，不得 `unique(keep="last")`。`suspend_d` 是唯一允许在
raw 留档后按 `(symbol,trade_date)` 合并多行的核心 mapper：`suspend_type` 必须为 `S`；全部
`suspend_timing=null` 映射一个 `FULL_DAY/null`；全部非空映射 `PARTIAL`，相同 detail 去重后按 Unicode
码点排序，以精确分隔符 `" | "` 连接；FULL/PARTIAL 同日冲突失败。空 `suspend_d` 返回带固定 dtype 的
零行表，其余三个 endpoint 的空 verified response 在 mapper 边界再次 fail-closed。

`M3G1MappingError` 的 `str()` 只允许稳定 code：
`G1_MAPPER_RESPONSE_INVALID`、`G1_MAPPER_ENDPOINT_MISMATCH`、`G1_MAPPER_EMPTY`、
`G1_MAPPER_COLUMNS_INVALID`、`G1_MAPPER_REQUEST_SCOPE_MISMATCH`、`G1_MAPPER_VALUE_INVALID`、
`G1_MAPPER_DUPLICATE_KEY`、`G1_MAPPER_SUSPENSION_CONFLICT`、`G1_MAPPER_SCHEMA_INVALID`。公开边界不得
泄露原始行、receipt/client repr、token 或绝对路径；底层 Polars/Pandera 异常使用 `from None` 转换。
输出按各自业务键稳定升序，并由对应领域 Schema 或本节内部列契约验证。

涨跌停与公司行动虽然也消费 `VerifiedRawResponse`，但它们依赖“合法无限制日”规则证据、公告版本选择与
factor-ratio 对账，不属于核心机械映射。首版由 G1-P3/B2C 专用任务书实现、B4 重验发布；不得在 B2B 为赶进度先写
`null -> unlimited`、`keep="last"` 或简化 dividend mapper。

观察唯一键为 `(universe,observation_date,symbol,source)`；同一来源同一观察日必须恰好形成一个完整
CSI300 状态，不得把同月多次观察合并成一个月末状态。研究基准固定为可交易 ETF `510300.SH`，只通过
`BenchmarkBar1dSchema` 校验；不得为通过 A 股代码正则而伪装成 SH/SZ symbol。

请求与发布语义：

- `request_id` 是 endpoint 与排序后参数规范化 JSON 的 SHA-256；参数必须显式包含稳定 `fields`，
  不得包含 token、客户端对象、重试次数、调用时间或绝对路径。`TushareRequestSpec.create`
  是唯一构造边界；executor 在任何 IO 前必须重算 request ID。
- 七个 endpoint 的 `fields` 使用代码中一份常量表，首版精确为：

  | endpoint | fields（顺序也是契约） |
  |---|---|
  | `index_weight` | `index_code,con_code,trade_date,weight` |
  | `daily` | `ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount` |
  | `adj_factor` | `ts_code,trade_date,adj_factor` |
  | `index_daily` | `ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount` |
  | `suspend_d` | `ts_code,trade_date,suspend_timing,suspend_type` |
  | `stk_limit` | `trade_date,ts_code,pre_close,up_limit,down_limit` |
  | `dividend` | `ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,imp_ann_date,base_date,base_share` |

  planner 不接受任意 fields 覆盖；字段不足或额外字段都必须形成不同 request ID，mapper
  严格拒绝缺字段。
- `index_weight` 从 `signal_start` 所在月向前推 `membership_warmup_months`，直到
  `signal_end` 所在月，每个请求都使用该自然月的完整首尾，不 clamp 到 signal 日；history 第二阶段只能在全部
  权重 receipt 通过、历史成分并集确定后生成。`daily/adj_factor` 按单证券完整 history window 请求，
  `index_daily` 单独请求基准，`suspend_d` 按月请求全市场后过滤成分并集；`stk_limit` 按证券请求完整
  history window，`dividend` 按证券请求全历史后只保留 history window 内已实施事件。
- `resolve_history_window` 要求 signal start/end 本身都是已验真 SH 开市日，不自动对齐。
  history start 是 signal start 之前精确 `feature_warmup_sessions` 个 SH session，history end 是 signal end
  之后精确 `label_tail_sessions` 个 SH session；日历不足即失败。所有证券 planner 入口使用领域契约，
  A 股只接受六位数字加 `.SH/.SZ`，不复用只检查“全数字”的宽松 connector helper。
- executor 首版严格串行并使用单调时钟限频。只重试 connector 显式转换的 typed
  `NETWORK/RATE_LIMIT/TRANSIENT_SERVER` 错误；权限、字段、契约或未分类的 SDK 字符串异常均
  fail-closed。首次网络尝试立即执行；后续尝试的最早时刻是“上次尝试开始 + 限频间隔”与
  “上次失败 + `retry_base_seconds * 2**(attempt-1)`”两个 deadline 的较晚者。缓存命中和
  journal 恢复不计网络尝试、不限频；重试不得改 request ID。
- 每次 API 原始响应原样写 `RawStore`，不得在 raw 前 `unique(keep="last")`。receipt 只有 raw data、
  metadata、行数、字段和 hash 全部验证后才原子发布。receipt 已存在且有效则不联网；存在但损坏
  立即失败。响应行数等于 endpoint 上限时视为可能截断，不发布成功 receipt。
- endpoint 的空响应与截断规则分别配置，禁止用一个全局 `row_limit_guard` 推断所有接口。首版项目
  fail-closed 单请求行数安全阈值为
  `daily=6000`、`adj_factor=6000`、`index_daily=5000`、`index_weight=5000`、`suspend_d=5000`、
  `stk_limit=5800`、`dividend=5000`。这些不得被表述为供应商的统一最大页长；返回行数等于
  安全阈值即失败。`index_weight/daily/adj_factor/index_daily/stk_limit=REJECT`，
  `suspend_d/dividend=ALLOW`。`dividend` 空表只表示该证券无可用分红记录，不能作为跳过 factor
  跳变对账的理由。
- receipt 是 request journal 的已提交态。每个 request 使用确定目录
  `journal/<request_id>/{intent.json,candidate.json,receipt.json}`；`intent` 在连网前原子发布，
  `candidate` 在 raw data+metadata 都完整验真后绑定它们。首版固定布局只允许一个
  `candidate.json`：它不存在且没有 raw 证据时才允许联网；存在且与 intent/raw 完全一致时恢复 receipt；
  candidate 冲突，或 request journal 目录出现第二个 candidate-like/未知普通文件时均失败。单有不完整
  data 而无可验真 metadata 不得冒充恢复成功；需要人工处理该孤儿后才可重试。所有相对路径必须
  规范化并仍位于受控 root 内。
- receipt 的 `raw_file_sha256/raw_metadata_sha256/raw_snapshot_id/path` 用于物理证据验真；
  `stable_response_sha256` 只规范 hash request ID、endpoint、parameters hash、response content hash、
  row count 与 columns，不含抓取时间、物理路径或 metadata hash。DataFrame 内容 digest 用固定列顺序、
  业务键排序和类型标签的规范 JSON 行计算；日期用 ISO、finite float 用唯一十进制编码、
  `-0.0` 归一为 `0.0`、null 保留，不得以 Parquet 文件字节代替逻辑内容 digest。raw 仍保留供应商原顺序和重复行。
- `execute_tushare_batch` 不写 clean。最终 `G1RequestPlan` 的 request ID 集与 verified receipt 集必须
  精确相等，少一个、多一个、重复或跨 plan receipt 均不得构建 candidate。只有全局质量门禁无 ERROR 后，才允许
  `publish_g1_release` 在临时目录组装，完成文件 hash/manifest 后原子 rename 为 immutable release。
  失败或进程中断不得把半套数据写入现有 `data/clean/bar_1d`。
- `publish_g1_release` 不读取配置文件，也不反向 import `quant.research`；它只接收已验证的
  `config_version/g1_config_sha256` 并绑定到 release ID/manifest。G1 stage handler 在调用任何可能写入的
  data-layer 函数前，必须用 C0 唯一 selector 从同一 `LoadedM3Config` 复算该 hash；G9 再从冻结配置独立
  复算。release identity 还绑定全部输入 receipt 和规范化 clean 内容，不绑定 config 物理路径、抓取时间
  或本机路径。

上述七个 `*_raw` 方法是 G1 executor 唯一允许调用的 connector API；现有聚合型
`fetch_bar_1d/fetch_adjust_factors` 会分块并在返回前 `unique(keep="last")`，禁止在 G1 复用，否则
供应商重复键会在 raw 留档前被吞掉。raw 方法不得去重、排序、映射或附加非供应商列。
现有 `TushareBarMapper/TushareAdjustmentFactorMapper` 依赖 `_request_symbol/_market` 且 factor mapper
会删除连续相同行，因此不得复用于 G1。G1 B2B 按上文新建 bar/factor/benchmark/suspension 核心 mapper；
price-limit/dividend 归 G1-P3/B2C，B4 只重验发布，仍必须从 `VerifiedRawResponse` 注入 receipt 血缘。factor 保留每个供应商
交易日行。

月度观察转 PIT 的保守规则：

1. normalize 必须同时接收完整 `INDEX_WEIGHT` batch 与 verified responses，并在读 frame 值前重建两者；
   response request ID 多重集合必须与 batch 精确相等。每个请求覆盖一个完整自然月，月份连续且代码固定
   `000300.SH`。只传若干 response 无法证明整批没有漏月，因此不再是合法接口。
2. `trade_date` 重命名为 `observation_date`；请求月份首日不是观察日或生效日。source 固定为 `tushare`，
   不能由调用方注入。
3. 首个 CSI300 版本每个 observation 必须**恰好 300** 个唯一证券、正且 finite 权重；按 symbol 稳定排序后
   用 `math.fsum` 计算权重和并要求在 `[99,101]`，禁止依赖输入行序/线程分块的普通浮点 reduce，也不得
   round 后比较。请求范围每个自然月至少一个 observation。250–350 只作为未来其他指数的通用
   诊断范围，不能放宽当前硬门禁。若同月多 observation，全部按日期顺序保留。
4. 成员方法版本精确为 `tushare_monthly_observed_next_session_close_v1`；旧
   `tushare_monthly_observed_next_open_v1` 必须拒绝。某 observation 的成分从其**下一 SH 开市日的收盘后信号**
   起可用；不得在 observation 当日或当月月初向前回填。下一 observation 生效时，前一状态在前一 SH
   开市日结束。
5. B3 membership 只表达 signal window：与 instrument 生命周期和 `[signal_start,signal_end]` 相交；
   `list_date` 向后映射为首个 `>=` 的 SH session，`delist_date` 向前映射为最后一个 `<=` 的 SH session；相邻
   状态中持续存在的证券区间合并，调出后再调入形成两段。`effective_to` 一律非 null，最后状态精确截到
   `signal_end`。生命周期裁剪后每个 signal session 仍必须恰好 300 个资格键，否则 fail-closed。
6. signal start 的第一个开市日必须已有 warmup observation 推导出的状态，否则 G1 失败。令
   `calendar_anchor=max(max(observation_date), signal_end)`，calendar 必须同时包含并证明 anchor 之后第一个
   SH 开市日 `calendar_proof_end`，并在依赖自然日域逐日证明 SH/SZ 日期集和 `is_open` 一致；不得求并集、
   用自然次日猜 session，或因尾部缺少严格下一 session 而截断。
7. observations/membership/eligible keys 的逻辑摘要统一使用 `m3-clean-table-content-v1`：规范 JSON、显式
   scalar 类型、完整规范行排序、重复保留、`-0.0→0.0`，与 Parquet bytes 和输入行序无关。v1 只接受
   null/bool/int/finite float/date/string，datetime 明确拒绝。公开 verifier 必须从原始 batch、verified
   responses、calendar、instruments 和参数重新 normalize/build，再逐表逐 digest 比较；不能只检查 result
   内部 hex，否则整体平移一个 session 后重算 digest 的自洽伪造仍会通过。值对象构造若调用带 coercion 的
   Schema，必须把 validator 返回的三张规范 frame 写回后再基于实际公开 frame 验 digest；不得用规范结果算
   摘要却继续暴露预验证 DataFrame。

B3 配置前置已按
[`M3_G1_P2_0主Agent最终验收报告.md`](agent/M3_G1_P2_0主Agent最终验收报告.md)
通过主验。B3 的现行可执行任务书为
[`M3_G1_P2_B3PIT成员状态外部闭环任务单.md`](agent/M3_G1_P2_B3PIT成员状态外部闭环任务单.md)；本节保存跨模块
业务不变量，精确错误码、文件范围、测试矩阵和外部实现—复验循环以该任务书为准。

G1 质量门禁至少包括：全部 standard Schema、选中 source 唯一、成分月完整、会员日行情/全日停牌
二选一、部分时段停牌仍要求行情、每条行情有可 as-of 的正 finite factor、OHLC/amount/volume 正且
finite、基准覆盖整个 history window、feature warmup 与 label tail 完整、重复键/截断/未知证券为
ERROR。Tushare `daily` 的停牌日无行是正常来源语义，但没有 bar 且没有全日停牌证据不能静默接受。

G1 使用两阶段身份：`primary_candidate_key` 由 `g1_config_sha256`、完整 Tushare plan/
stable response digests、calendar/instrument/标准化 clean 内容 digest、mapper/schema/membership/build
code version、dependency fingerprint 以及显式 `signal_start/signal_end/history_start/history_end` 按具名字段
规范 JSON 计算；不含 BaoStock 证据。四日期同时是 `G1Candidate` 字段，不能只藏在 opaque plan hash 中。
用该 key 按固定
hash-rank 算法先选 30 只证券，再为每只选 20 个已发布 primary bar 交易日；样本不足即失败。
证券 rank 键是规范 JSON 数组 `["m3-g1-cross-source-symbol-v1",primary_candidate_key,symbol]`
的 SHA-256，日期 rank 键是
`["m3-g1-cross-source-date-v1",primary_candidate_key,symbol,trade_date_iso]`；均按 `(hash,原值)`
升序取前 N，最终 sample keys 再按 `(symbol,trade_date)` 排序。
冻结 sample plan 后才能请求 BaoStock 不复权数据，每个参考请求也必须先 raw 留档、再形成可验真
receipt。每个入选 symbol 恰有一个 BaoStock request，区间是该 symbol 样本日的 min–max，参数固定为
`fields=date,code,open,high,low,close,volume,amount,adjustflag,tradestatus`、`frequency=d`、
`adjustflag=3`。首版参考源 executor 严格串行且不自动重试；网络失败保留 intent 并由人工重跑，
有效 receipt 则零网络复用。参考 raw 可保留区间内额外日期，对账严格只比较冻结的 600 个
`(symbol,trade_date)` 键，每键比较 OHLC 和 volume 五个值；
缺少一行按五个 mismatch 计数。价格通过条件为
`abs(primary-reference) <= price_atol + price_rtol * abs(reference)`，成交量为
`abs(primary-reference) <= volume_rtol * max(abs(reference), 1)`；`mismatch_rate`是 mismatch cell 数除以 3000，
不大于配置阈值才 PASS。最终 `release_id` 在 primary identity 上再绑定 sample plan、BaoStock stable
receipt digests 和 reconciliation detail/summary digest，因此无身份循环，也不含抓取时间或物理路径。

BaoStock executor 只接受自证的 `ReferenceRequestPlanV1`，而不是可被 caller 任意裁剪的 request sequence。
该 plan 必须把 `sample_plan_sha256` 与按 request ID 排序的 30 个完整 request spec 绑定到
`request_plan_sha256`；写任何 intent 或联网前，重算 600 个 sample key 到 30 个请求的精确闭包。P4 的
`primary_candidate_key`、sample plan、reference request plan 和 `release_id` 使用的确切 canonical JSON
envelope 以 P4 任务拆分文档为准，不得用 `repr`、位置含糊的对象或字段子集替代。

`primary_candidate_key` 是主源 candidate 的唯一内容身份；不再维护含义重叠的 `candidate_sha256`。
`publish_g1_release` 只接受 `G1ReleaseInputs`，必须从 `G1BuildInputs` 和 verified reference responses 重建
candidate、request/receipt 闭包、跨源结果和所有门禁，不接受调用方自报的 candidate、audit、`quality`
列表或 PASS 布尔值。精确的 P4A/P4B/P4C 信任边界、接口、身份 DAG、文件状态机和外部闭环以
[`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](agent/M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md)
为准。发布目录首版固定为：

```text
data/clean/m3_g1/releases/<release_id>/
  manifest.json
  quality.json
  universe_membership.parquet
  eligible_keys.parquet
  bar_1d.parquet
  adjustment_factor.parquet
  adjustment_factor_match.parquet
  benchmark_bar_1d.parquet
  suspension_1d.parquet
  trade_calendar.parquet
  instrument.parquet
  index_constituent_observation.parquet
  price_limit_1d.parquet
  corporate_action_ledger.parquet
  corporate_action_selection_evidence.parquet
  corporate_action_reconciliation.parquet
  cross_source_reconciliation.parquet
  cross_source_reconciliation.json
```

不允许自行分区或增加普通文件。manifest 的 file table 精确列出除 manifest 自身外的所有普通文件，
不自引用；外层 snapshot/stage receipt 负责绑定 manifest bytes。manifest、quality 和 cross-source
summary 分别使用严格 `m3-g1-manifest-v1`、`m3-g1-quality-v1`、`m3-g1-cross-source-v1`
reader，拒绝未知/缺字段、duplicate JSON key、字符串数字、NaN/Infinity、绝对/逃逸路径和未知
issue code。`G1QualityIssue.evidence` 只保存固定排序的业务键或受控相对路径，禁止本机路径、客户端
repr 或凭据。后续 snapshot manifest 必须记录 `g1_release_id` 与 G1 manifest hash，不能只写
`source=tushare`。

首版 issue code 精确集为：

```text
REQUEST_PLAN_MISMATCH, RECEIPT_INVALID, SCHEMA_INVALID, DUPLICATE_KEY,
UNKNOWN_INSTRUMENT, MEMBERSHIP_MISSING_MONTH, MEMBERSHIP_COUNT_MISMATCH,
MEMBERSHIP_WEIGHT_INVALID, MEMBERSHIP_INTERVAL_OVERLAP, CALENDAR_MISMATCH,
HISTORY_WINDOW_INCOMPLETE, BAR_OR_SUSPENSION_MISSING,
BAR_FULL_SUSPENSION_CONFLICT, PARTIAL_SUSPENSION_BAR_MISSING,
FACTOR_MISSING, FACTOR_INVALID, PRICE_LIMIT_MISSING, PRICE_LIMIT_INVALID,
BENCHMARK_MISSING, CORPORATE_ACTION_INVALID,
CORPORATE_ACTION_FACTOR_MISMATCH, CROSS_SOURCE_INCOMPLETE,
CROSS_SOURCE_MISMATCH
```

issues 按 `(severity,code,message,evidence)` 排序；`error_count/warning_count` 必须与 issues 重算相等，
`passed` 当且仅当 `error_count == 0`。manifest `input_receipts` 按 `(source,endpoint,request_id)`
排序，files 按 path 排序；`sha256` 是物理文件 bytes，`content_sha256` 是规范表内容，二者均验真。
`min_key/max_key` 使用与 `key_columns` 同长的规范字符串 tuple；0 行文件两者均为 null，非空文件两者
均必需；`quality.json/cross_source_reconciliation.json` 固定 `row_count=1`、空 `key_columns`、
null min/max，`content_sha256` 是对严格解析后对象的规范 JSON hash。cross-source `field_stats` 顺序精确为 `open,high,low,close,volume`，`key_count=600`、
`field_count=5`、`comparison_count=3000`，每个 field comparison count=600；统计、detail digest、receipt
digests 和 `passed` 均由 reader 重算而不信任自报。

`apply_adjustment_factors_strict` 必须先按 `symbol,trade_date,source` 唯一键验证两侧数据，再做精确匹配；
每个 emitted bar 必须保留“确实匹配到供应商 factor 行”的证据，匹配缺失、重复、非正或 non-finite 均为
ERROR。禁止使用 `coalesce(..., 1.0)`、默认值或前值填充掩盖缺因子。现有聚合 pipeline/store 的逐日发布
语义不得用于 G1；`publish_g1_release` 只能创建全新的临时 release，原子 rename 后立即调用
`verify_g1_release` 重算 manifest、文件 hash、Schema、行数和键范围。已存在 release 只允许验真复用，
不得增量补写或覆盖。

G1 release 的 Parquet 写参数固定为 zstd level 3、statistics 开启、row group 65536、Polars native writer；
目录发布只允许 WSL/Linux `renameat2(RENAME_NOREPLACE)` 或经测试证明语义等价的 no-clobber primitive。
运行时不支持时 fail-closed，禁止回退到 `os.rename`、`os.replace`、先检查后 rename 或逐文件 merge。

SH 日历是信号与 membership 的唯一 session SSOT；同一日期若 SH/SZ `is_open` 不一致必须产生结构化
诊断并失败，不得求并集或静默选边。`eligible_keys.parquet` 是 G1 release 必需产物，严格只含
`as_of,symbol` 两列、键唯一且排序稳定；G2/G3/G4 不得从 membership 自行再推导一份。跨源证据
未执行、缺双方 receipt、样本集不精确或超阈值时均不得宣称 G1 通过。

G7 的执行事实不得从价格形态猜测。`stk_limit` 映射结果必须通过代码 SSOT
`PriceLimit1dSchema`；`dividend` 只接受 `div_proc=实施` 的行，使用税前每股现金和每股送转比例映射到
`CorporateActionLedgerSchema`。供应商没有公告时分的历史实施事件不得伪造 `announce_time` 后塞入
面向 PIT 研究的 `CorporateActionSchema`。mapper 必须在 raw 留档后处理同一事件的多次公告版本，保留
选择证据；任何 adj_factor 跳变若在相邻交易日无法由已实施公司行动解释，进入 G7 前必须报 ERROR。
`PriceLimit1dSchema.has_price_limit` 必须显式区分“有完整上下限”和“当日依法无限制”；前者要求
up/down 均存在且包围昨收，后者需要另一份已验真交易规则键证明。首版尚未接入该规则源，
因此 M3 v1 不发布 `has_price_limit=false`。真实 `stk_limit` 的 null/zero `pre_close` 是无可用 limit 的供应商
sentinel，只保留在 raw、不映射 clean；它不是无限制日证明。未来要支持合法无涨跌幅限制日，必须新增规则
输入、方法版本和 digest 后升级契约；mapper 不得从 null/zero 或价格形态猜测。

G1 价格限制覆盖不能只检查 `(eligible as_of → next session)`：调出、停牌、涨跌停或 T+1 后仍可能持仓。
每个曾 eligible 的证券从首次 eligible 后第一 SH session 起，直到 `history.end` 或退市日对应最后 SH
session 展开潜在持仓域；有 verified `FULL_DAY` suspension 的 key 因两边均不可成交而从 limit-required 集合
排除，`PARTIAL` 或无 suspension 的 key 必须有一条 `has_price_limit=true` 的 Tushare 行。首次可能持仓前的
合法 extra 行可保留。null/zero sentinel 若没有 FULL_DAY 证据仍 fail-closed。
该 required key 派生表进入 candidate/audit 内容 digest，但不增加 release 普通文件。通用
`PriceLimit1dSchema` 仍保留未来有规则证据的 false 分支，M3 v1 mapper/coverage 不得使用该分支。

公司行动首版多公告选择规则固定为：只保留 `div_proc=实施`；经济事件分组键为
`(ts_code,end_date,record_date,ex_date)`，`pay_date/div_listdate` 是可被后续公告更正的版本属性，不得进入分组键。
组内按 `(imp_ann_date,ann_date)` 降序选唯一最新版本；
排序键完全相同但现金/送转数值冲突时失败，不得 `keep="last"`。`record_date/ex_date` 必需；
`cash_per_share_gross > 0` 时 `pay_date` 必需，否则 `pay_date` 必须为空；`stock_ratio > 0` 时
`stock_list_date` 必需，否则该日期必须为空。事件 ID 是规范分组键+最终数值的 SHA-256，选择证据记录
候选数、被选 raw snapshot/request 和冲突计数。同一 ex-date 的多个不同经济事件在 factor 对账前才汇总，
不得在版本选择阶段相互覆盖。

`dividend` 请求是单证券全历史，不得让范围外旧记录阻断当前研究：对实施行先验证 `ex_date` 可分类，再只对
`HistoryWindow` 内 ex-date 执行完整经济/结算契约；无法解析 ex-date 的实施行不能伪装成范围外。
`imp_ann_date/ann_date` 可 null，total order 中每个 null 都比任何合法日期旧；同 group 同 rank 且决策字段
相同的 raw 重复合并计数，cash/stock/pay/list 任一冲突则失败。范围内 cash>0 当且仅当 pay date 存在，
stock>0 当且仅当 list date 存在；`record_date` 非 null。
合法空 dividend response 或 HistoryWindow 内零实施事件必须形成带精确 Schema/digest 的空 ledger/evidence，
不得当作数据错误。ledger 现行字段数是十列，不是九列。`candidate_id` 规范绑定 event key、imp/ann、
cash/stock、pay/list；同 rank 完全重复折叠后，candidate count 只计不同 candidate ID，raw row count 单独保存。
公司行动数值对账必须保留并重建对应 verified daily raw，因为 Tushare `daily.pre_close` 是除权参考价，而沪深
交易规则的通式含配股且允许发行人/交易所批准调整。现金/送转只能计算
`declared_dividend_factor_ratio = previous_close * (1 + stock_ratio) /
(previous_close - cash_per_share_gross)`；存在 effective-date daily 行时，主门禁使用
`market_reference_factor_ratio = previous_close / daily.pre_close(ex_date)`，并与
`adj_factor(ex_date)/adj_factor(previous_factor_observation)` 在配置 rtol 内对账。若 verified daily 缺该行，
必须另有同键 `FULL_DAY` suspension；此时 market 三字段为 null，且只有 declared ratio 自身在 rtol 内闭合
才可继续。PARTIAL 或无 suspension 的缺行仍失败。
previous factor observation 是该证券严格早于 ex-date 的最后一条可用因子，不要求停牌期间逐 session 有因子；
但事件必须精确落在 factor row，不能把 gap 中事件移动到下一 row。previous close 是 ex-date 前最后一条有效
未复权 bar，允许早于 previous factor date。
多个同日实施事件
按 event ID 排序并用 `math.fsum` 分别合并现金与送转后计算；event-set hash 使用规范数组
`["m3-g1-corporate-action-event-set-v1",*sorted_event_ids]`。有 factor 跳变无事件、有效事件无可用前收，或
market/declared 两条可用证明路径都超容差均为 ERROR。有 daily 且 declared 公式在 rtol 内输出
`MATCHED_EVENT_DECLARED_FORMULA`；无 daily 但 declared 闭合输出
`MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE`；declared 超出但 market reference 闭合时输出
`MATCHED_EVENT_MARKET_REFERENCE`，明确记录配股、差异化分红或批准调整未被 dividend 两字段完整表达，
不得扩大 rtol 让该状态消失。

公司行动 reconciliation 对每个相邻 factor observation 输出一行证据：无事件时 declared/market ratio=1，
有事件时以规范 `event_ids_json` 保留排序去重 event IDs，并从它重算 event count/hash；同时绑定聚合经济分量、previous close、raw ex-reference、declared/market/actual ratio、
两种 relative error、实际 rtol，以及可回指 candidate receipt 的 daily request/stable-response lineage；行数
严格等于各 symbol 的 factor rows-1。`factor_ratio_rtol` 首版必须 finite 且位于 `[0,0.01]`，示例仍为
`0.001`；C0 与 data 函数双重门禁，禁止用 1.0/NaN 把 residual 变绿。

B2C 的现行可执行任务书为
[`M3_G1_P3_B2C执行事实外部闭环任务单.md`](agent/M3_G1_P3_B2C执行事实外部闭环任务单.md)。精确 evidence Schema、
identity、错误码、文件范围、真实探针和外部实现—复验循环以该任务书为准。

P3 初验曾发现只改 `event_ids_sha256` 并同步整表 digest 仍可通过。通用教训是：整表内容 digest 只能证明字段
属于该表，不能替待验证的派生身份自证；自包含 verifier 必须保存并规范化重算所需的最小原始证据。P3 因此
新增 `event_ids_json` 并从中重算 count/hash。若攻击者把证据、派生值和全部 digest 一起替换为另一套内部自洽
结果，来源闭包仍必须由 P4A 从冻结 plan/verified responses/输入表重新执行 P2/P3 关闭，不能继续堆自报 hash。

`HistoryWindow` 定义在 `quant.data.m3_backfill`；P4A 的 `G1QualityIssue` 定义在
`quant.data.m3_g1_candidate`，不得为复用类型而把 B4 继续塞入 `m3_backfill`。二者都不得从
`quant.research.m3.contracts/readiness` 反向 import；data 层不能依赖 research 层。

停牌 clean 契约由 `src/quant/domain/schemas.py` 新增的 `Suspension1dSchema` 作为 SSOT：

```python
class Suspension1dSchema(pa.DataFrameModel):
    symbol: str
    trade_date: pl.Date
    suspension_scope: str  # FULL_DAY / PARTIAL
    suspension_detail: str | None
    source: str
    source_snapshot_id: str
```

唯一键为 `(symbol,trade_date,source)`。Tushare 只请求 `suspend_type="S"`；`suspend_timing` 为空映射
`FULL_DAY`，非空映射 `PARTIAL` 并保留原字符串。若原始同日多行，mapper 只能在 raw 留档后规范化：
多个 partial detail 排序合并，FULL/PARTIAL 冲突拒绝。`无 bar + FULL_DAY` 合法，`无 bar + PARTIAL`
或未知状态非法，`有 bar + PARTIAL` 合法，`有 bar + FULL_DAY` 为冲突。

### 4.11 `a_share_simulator.py`：G7 统一 A 股回测

G7 不是复用当前 ETF 薄模拟器换一个成本对象。股票账户必须显式处理停牌持仓估值、涨跌停开盘拒单、
T+1、公司行动应收款/应收股和历史费率。现行 G7P0–G7F verified-artifact 边界、金额舍入和外部闭环以
[`M3_G7目标到账户回测分包骨架与外部闭环任务单.md`](agent/M3_G7目标到账户回测分包骨架与外部闭环任务单.md)
为执行入口；旧 E4A–E4E 只保留历史。实现时相应输出 Schema 写入
`src/quant/domain/schemas.py` 成为字段 SSOT：

```python
@dataclass(frozen=True)
class VerifiedTargetArtifact:
    root: Path
    targets: pl.DataFrame
    target_daily: pl.DataFrame
    manifest: TargetManifestV1
    manifest_sha256: str
    target_receipt_sha256: str

@dataclass(frozen=True)
class VerifiedBacktestPlanArtifact:
    root: Path
    scheduled_targets: pl.DataFrame
    manifest: BacktestPlanManifestV1
    manifest_sha256: str
    plan_receipt_sha256: str

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
旧 [`M3_G7统一回测实现与初验任务单.md`](archive/M3_G7统一回测实现与初验任务单.md) 仅保留历史。

## 5. 可直接交给另一个 Agent 的任务包

每个任务包都可以独立提交。Agent 开始前必须阅读根目录 `AGENTS.md` 和
`karpathy-guidelines.md`，不得读取 `archive/legacy_pre_greenfield/` 或 `data/legacy/`。

本节 D1–D8 是首轮骨架的历史拆分；当前返工与新增实现不得只按下文摘要执行。现行机械任务唯一入口：

- D1/D4/D5/D7 二次返工：[`M3_D1-D8二次返工任务单.md`](agent/M3_D1-D8二次返工任务单.md)；
- E0/E3 staging/run-state：[`M3_G2-G8另一个Agent任务单.md`](archive/M3_G2-G8另一个Agent任务单.md)；
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
  旧合并任务与一致性历史见 [`M3_G2-G3Provider与标签对账实现初验任务单.md`](archive/M3_G2-G3Provider与标签对账实现初验任务单.md)、
  [`M3_G2-G3跨文档一致性初验报告.md`](agent/M3_G2-G3跨文档一致性初验报告.md)；
- G4–G6 研究链七段式闭环：
  [`M3_G4_G6研究链分包骨架与外部闭环任务单.md`](agent/M3_G4_G6研究链分包骨架与外部闭环任务单.md)；
  旧合并任务与设计历史见
  [`M3_G4-G6研究链实现与初验任务单.md`](archive/M3_G4-G6研究链实现与初验任务单.md)、
  [`M3_G4-G6设计审查与修订记录.md`](agent/M3_G4-G6设计审查与修订记录.md)；
- G7 六段式闭环：
  [`M3_G7目标到账户回测分包骨架与外部闭环任务单.md`](agent/M3_G7目标到账户回测分包骨架与外部闭环任务单.md)；
  旧合并任务与根因历史见 [`M3_G7统一回测实现与初验任务单.md`](archive/M3_G7统一回测实现与初验任务单.md)、
  [`M3_G7设计审查与修订记录.md`](agent/M3_G7设计审查与修订记录.md)；
- G8 六段式闭环：
  [`M3_G8Continuation编排恢复追踪分包骨架与外部闭环任务单.md`](agent/M3_G8Continuation编排恢复追踪分包骨架与外部闭环任务单.md)；
  旧合并任务与设计历史见
  [`M3_G8编排与追踪实现初验任务单.md`](archive/M3_G8编排与追踪实现初验任务单.md)、
  [`M3_G8设计审查与修订记录.md`](agent/M3_G8设计审查与修订记录.md)；
- G9 七段式闭环：
  [`M3_G9最终准入分包骨架与外部闭环任务单.md`](agent/M3_G9最终准入分包骨架与外部闭环任务单.md)；
  旧合并任务与设计历史见
  [`M3_G9最终验收实现与独立初验任务单.md`](archive/M3_G9最终验收实现与独立初验任务单.md)、
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

1. `index_weight(index_code="000300.SH")`：从 signal start 前一个自然月至 signal end 月逐月请求，
   保存原始快照和 request receipt。接口的 `trade_date` 是 observation；月首/月末只是请求边界。
2. 由 observation 构建保守 PIT：状态从 observation 的下一 SH 开市日起可用，直到下一 observation
   生效前一开市日；不得向前回填。每月检查唯一成分、权重和及月间增删，然后确定历史成分并集。
3. 依据 clean SH 日历把 signal window 向前扩 60 sessions、向后扩 10 sessions。对成分并集逐证券
   抓 `daily`、`adj_factor`、`stk_limit` 与全历史 `dividend`，抓 `510300.SH` ETF 日线、复权因子与分红，并按月抓
   `suspend_d`。严格串行限频、endpoint 显式字段、响应原样入 raw；停牌缺 bar 不补价。
4. 全部 receipt 完整后统一映射和审计，发布 immutable G1 release。除标准契约外，每个生效成员开市日
   必须有唯一 bar 或全日停牌证据；证券收益使用两端 adj_factor。再随机抽取至少 30 只证券、20 个
   日期与 BaoStock 或交易所公开行情交叉对账。

Tushare 官方说明 `index_weight` 为月度数据且 2000 积分可用；`daily` 单次最多 6000 行，按单证券
可覆盖约 23 年；`adj_factor` 2000 积分起，可按证券取得全部历史。实际调用频率仍以账户返回为准，
不得把文档上限当作必须打满的并发目标。

2026-07-13 使用当前账户做过脱敏只读探针：`000300.SH` 与 `399300.SZ` 在 2026-01 均返回 300
成分、同一 observation `2026-01-30`，证券集合和权重逐项一致，权重和为 `99.994`；两价格指数代码的
`index_daily` 均返回 20 行。成分接口继续固定 `000300.SH`，不在运行时自动切换别名；标签基准则固定
为已冻结的 ETF 基准 `510300.SH`，两者职责不得混淆。2016-Q1
探针每月均为 300 唯一成分，权重和分别为 `100.002/99.992/100.004`，支持 `[99,101]` 门禁；这些
探针只证明当前权限和样例语义，不代替 2015-12 至 2026-06 的完整 G1 审计。

### 6.5 G2–G3：Alpha158 与标签语义（决策已完成，待真实环境验证）

- 官方 Alpha158 要求 `$vwap`，provider 必须输出 8 个字段：
  `open,high,low,close,vwap,volume,factor` 加日期索引；不得删特征冒充 Alpha158。
- 首版 Qlib 只负责 feature expression；禁用全部 handler processor，独立标签是唯一训练真值。
- G2 先全量验 tree/calendar/instruments，再对账 60 emitted keys×7 fields 与另计 gap；G3 分别对账
  expression-direct、独立 benchmark、provider raw-vs-label raw、relative-vs-label 四个误差序列，不只比较
  最终一列，以便定位 Ref 方向、基准日期或 float32 量化错误。
- 此处仍需 Qlib 真实可运行环境；mock 只能证明适配器调用，不得关闭 G2/G3。
- 机械实现与初验见
  [`M3_G2-G3Provider与标签对账实现初验任务单.md`](archive/M3_G2-G3Provider与标签对账实现初验任务单.md)。

### 6.6 G5–G6：模型与预测证据

每个 fold×horizon 必须产生以下不可变文件：

```text
model.txt                 LightGBM native model
model.metadata.json       feature/params/snapshot/fold/horizon/hash
validation_curve.parquet  仅 validation l2 的逐 iteration 证据
predictions.parquet       PredictionScoreSchema，test 段全量分数
prediction_manifest.json  work/model/feature/资格/日期/文件 hash
daily_ic.parquet          显式 evaluation_dates 的逐日统计
metrics.json              只含 test 汇总指标
evaluation_manifest.json  五层样本域和输入/输出 hash
```

M3 不做超参数搜索；early stopping 固定看 validation l2，Rank IC 只在模型锁定后的 test 报告。每 fold
Alpha158 FeatureArtifact 只生成一次供两个 horizon 共享；train/validation 才 join labels，test inference 不
允许 label 参数。模型发布后对 test 只执行一次 best iteration 的 predict/evaluate。逐日输出 eligible/
scorable/predicted/labeled/evaluated 五层计数和四层 coverage，跨折只聚合不重叠 daily IC，不平均 ICIR。

可复现验收必须从同一 snapshot/config 进行两次独立冷启动训练，不能读取第一次的 model 或 predictions
缓存；两次行键必须一致，score 和指标再按 G5 容差比较。现行七包机械实现、反例和独立初验见
[`M3_G4_G6研究链分包骨架与外部闭环任务单.md`](agent/M3_G4_G6研究链分包骨架与外部闭环任务单.md)；历史
合并任务与根因见 [`M3_G4-G6研究链实现与初验任务单.md`](archive/M3_G4-G6研究链实现与初验任务单.md) 和
[`M3_G4-G6设计审查与修订记录.md`](agent/M3_G4-G6设计审查与修订记录.md)。

### 6.7 G7：组合与统一 A 股回测

M3 首个准入策略冻结为**无状态等权 Top-k**；`n_drop` 暂不进入 M3 完成条件。原因是当前统一
`Strategy` 契约没有显式上期选择输入，隐藏可变状态会破坏重跑和并行 fold。配置与实现均使用
`strategy="topk"`；TopkDrop 作为后续独立接口变更。

预测经 `build_target_artifact` 和 `MlTopkStrategy` 形成完整 target batch 与血缘 manifest，再由
`build_backtest_plan_artifact` 批次映射到共同下一 SH session。最终准入不得调用 Qlib backtest，也不得复用
ETF 薄模拟器；唯一接口与账户事件语义以 4.11 为准。

每个 fold 的 test 信号只允许在该 fold test 日期域内生成，但最后信号必须读取下一 session 完成执行和
终值估值；该尾随日不反写进 IC。0.5×/1×/2×为摩擦压力，只缩放配置 allowlist 中的佣金、最低佣金和
滑点，法定印花税/过户费保持历史期值。三个场景从相同外生输入独立回放，费用不同导致可买合法申报数量不同
是合法结果，不得强制复用 1× fills。现行分包实现与初验见
[`M3_G7目标到账户回测分包骨架与外部闭环任务单.md`](agent/M3_G7目标到账户回测分包骨架与外部闭环任务单.md)；
旧合并任务仅保留历史。

### 6.8 G8：产物与 MLflow 证据链

本地 run directory 是运行产物 SSOT，MLflow 是索引和展示层。tracking 的 allowlist 至少包含：
snapshot/config/code/dependency hashes、fold/horizon、模型参数、feature hash、label version、测试指标、
成本场景和各 artifact hash。禁止记录 token、本机绝对路径、未筛选配置和用户信息。

G8 使用 snapshot request → 内容寻址 snapshot → provider → experiment shared → work 的明确身份链。
snapshot、provider、experiment shared、work 计划分段静态构造，解决 snapshot ID、provider receipt 和
folds receipt 在各自发布前不可知的问题；每个 fold×horizon
是独立 work node，不能把 work identity 塞回 experiment key。跨 scope receipt 通过 root alias 记录上游
文件 digest，损坏或路径逃逸一律 fail-closed。每个 stage 独占一个原子发布目录；计划内输入通过 producer
引用在执行期解析，不能伪造尚未产生的 hash。`run-all` 只隔离独立 work 失败，shared stage 仅阻断其
真实依赖者；MLflow 只在本地产物全部验真后幂等登记。现行 G8A–G8F 分包、崩溃恢复与独立初验要求见
[`M3_G8Continuation编排恢复追踪分包骨架与外部闭环任务单.md`](agent/M3_G8Continuation编排恢复追踪分包骨架与外部闭环任务单.md)，旧设计缺陷和回归反例见
[`M3_G8设计审查与修订记录.md`](agent/M3_G8设计审查与修订记录.md)。

### 6.9 尚未关闭的外部门禁

1. G0 Python 兼容子项已在 `py312` 通过主验且 base 未变；正式 G0 readiness/Gate 与后续真实数据/provider 证据仍未闭合，G0 Gate 未关闭。
2. CSI300 PIT 长历史尚未完成抓取与质量验收，G1 仍阻塞。
3. E3 严格 receipt 增量 R1–R4 与 C0 已通过主 Agent 最终验收；D1/D4/D5/D7、Benchmark/label v2 Schema
   及其真实数据链仍未完成主验，不能关闭 G1–G3。E3 终验证据见
   [`M3_E3严格Receipt主Agent最终验收报告.md`](agent/M3_E3严格Receipt主Agent最终验收报告.md)。
4. G4–G6 已按 G4A/G4B/G4C/G5A/G5B/G6A/G6B 七个 verified-artifact 边界冻结 FoldPlan、fold-shared
   FeatureArtifact、无标签 test inference、validation-l2 模型、全量 prediction 和 coverage ladder；七包均
   未实现，也没有兼容环境的真实 Qlib/LightGBM 验证。
5. G7 已冻结 G7P0 与 G7A–G7F 七个 config/verified-artifact/纯状态边界，但当前仍只有 ETF 薄模拟器和
   早期成本/规则零件；四个新增 config 字段、target、backtest plan、双-leg entitlement、execution、账户
   循环和三场景 artifact 均未实现，仍需独立手算验收。
6. G8 已按 G8A registry、G8B StageRunner、G8C CLI、G8D tracking、G8E fresh-process reproducibility、
   G8F fake 全 DAG 六个边界冻结；全部尚未实现，真实 handlers 与 MLflow 也未验。
7. G9 已按 G9A quality、G9B evidence plan、G9C G0–G4、G9D G5–G7、G9E G8–G9、G9F publish/CLI、
   G9G fake integration 七个边界冻结；全部尚未实现，尚无跨 Gate 或真实 tracking 运行证据，G8/G9 未关闭。

## 7. Agent 提交格式

### 7.1 四阶段交付与验收流程

M3 后续任务统一采用以下职责分离，不允许实现者自己宣布最终通过：

1. **主 Agent 冻结任务书。** 明确 SSOT、文件所有权、函数签名、失败语义、排除项、验收命令与
   至少一组反例；契约未冻结的高风险判断不下放。
2. **实现 Agent 交付。** 只在任务书范围实现并提交自测报告；发现契约缺口时报告，不自行改变
   业务语义来让测试通过。
3. **独立验收 Agent 初验。** 不参与实现，先核对任务书逐项证据，再增加实现者未提供的对抗性
   反例。初验不通过时形成返工清单，必须写清“现象—根因—应遵循规则—最小复现—通过条件”。
4. **主 Agent 最终验收。** 在初验通过后复核代码边界、SSOT、全量回归和跨模块不变量，并再次
   抽取未公开反例。只有主 Agent 最终验收通过，才能更新 G0–G9 或路线图状态。

实现 Agent 与独立验收 Agent 原则上不是同一个 Agent。若受并发或环境限制无法分离，报告必须明确，
主 Agent 增加独立检查强度，不能把实现者自测改名为独立验收。

### 7.2 问题反馈必须沉淀为规则

- 因实现 Agent 考虑不周产生的问题，主 Agent 不只给出补丁结论，还要说明遗漏的系统不变量，并
  更新 SSOT/任务书和最小反例，使同类错误不再依赖人工记忆。
- 实现 Agent 发现任务书内部矛盾、真实 SDK 行为或数据反例时，主 Agent必须重新审视原设计；确认
  有效后先更新权威契约，再允许返工，不能要求实现迁就错误任务书。
- 每轮交付、初验和终验报告相互链接。已关闭问题保留根因和回归测试；新问题不得覆盖旧报告。
- 任务状态只允许 `未开始 / 实现中 / 待初验 / 初验返工 / 待终验 / 终验返工 / 已通过`。测试绿
  但证据不完整时仍是 `待初验` 或 `待终验`，不是 `已通过`。

### 7.3 实现 Agent 提交内容

另一个 Agent 完成一个任务包后，交付说明必须包含：

1. 任务包编号；
2. 修改文件；
3. 每个函数是否完全符合第 4 节签名和语义；
4. 针对性测试命令与结果；
5. Ruff/mypy 结果；
6. 未实现项和真实原因；
7. 是否改变配置、公共契约或文档；若改变，列出同步位置。

禁止把“mock 通过”描述为 Qlib 真实运行通过，禁止把“缺依赖”描述为代码缺陷或验收成功。

## 8. 主 Agent 验收矩阵

| Gate | 证据 | 通过条件 |
|---|---|---|
| G0 运行时 | `readiness` JSON | Python/Qlib 兼容、依赖版本可记录 |
| G1 数据 | snapshot manifest + quality JSON | PIT、字段、日期、因子、覆盖门禁全通过 |
| G2 provider | 全量结构验真 + 确定性 Qlib 回读 | 权威 calendar/instruments/bin 树完整；60 emitted keys/420 字段比较与 staging 转 `<f4` 后精确一致；另计 gap 全为 NaN |
| G3 标签 | Qlib expression/direct + 独立 benchmark + Float64 label 全量对账 | 行键一致；四个误差序列分别按 expression、benchmark、raw/relative label 三组配置容差通过 |
| G4 切分 | fold manifest | 无重叠；embargo >= 10 sessions；尾部完整 |
| G5 模型 | 两次 predictions Parquet | 行键一致，score 最大差 <= `1e-12` |
| G6 研究指标 | test metrics JSON | 含 IC/RankIC/ICIR/覆盖率，只有测试段 |
| G7 组合 | target weights + unified backtest | 合同通过，次日成交，0.5×/1×/2×成本 |
| G8 追踪 | MLflow run + 本地 artifacts | snapshot/config/code/deps/fold/horizon 全可追溯 |
| G9 最终质量 | acceptance report + quality receipt | G0–G8 身份闭包、每 work 复现/阈值、MLflow current target、pytest/Ruff/mypy/import 隔离全部通过 |

只有 G0–G9 全部通过，路线图 M3 才能标记完成。当前只完成契约与骨架，不满足完成条件。
配置 C0 是所有 Gate 的共同前置；没有已验真的 `LoadedM3Config` 时，不得计算或验收任何身份。

## 9. 官方参考

- [Qlib Alpha158 + LightGBM 官方 workflow](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml)
- [Qlib 官方 dump_bin.py](https://github.com/microsoft/qlib/blob/main/scripts/dump_bin.py)
- [Qlib 数据字段与 factor 约定](https://qlib.readthedocs.io/en/v0.9.6/component/data.html)
- [Qlib Yahoo 日频价格/成交量归一化实现](https://github.com/microsoft/qlib/blob/main/scripts/data_collector/yahoo/collector.py)
- [Qlib 数据准备与健康检查](https://github.com/microsoft/qlib/blob/main/README.md)
- [Qlib 0.9.7 PyPI 发行文件与 Python wheel](https://pypi.org/project/pyqlib/0.9.7/)
- [Tushare 指数成分和权重](https://tushare.pro/document/2?doc_id=96)
- [Tushare A 股日线](https://tushare.pro/document/2?doc_id=27)
- [Tushare 复权因子](https://tushare.pro/document/2?doc_id=28)
- [Tushare 每日涨跌停价格](https://tushare.pro/document/2?doc_id=183)
- [Tushare 每日停复牌信息](https://tushare.pro/document/2?doc_id=214)
- [Tushare 分红送股](https://tushare.pro/document/2?doc_id=103)
- [财政部、税务总局 2023 年证券交易印花税减半公告](https://www.mof.gov.cn/jrttts/202308/t20230828_3904235.htm)
- [MLflow 本地 SQLite Tracking](https://mlflow.org/docs/latest/ml/tracking/tutorials/local-database)
- [LightGBM 确定性参数](https://lightgbm.readthedocs.io/en/stable/Parameters.html)
