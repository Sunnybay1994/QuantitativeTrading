# M3 Qlib/LightGBM 实施与 Agent 交接

状态（2026-08-02）：正式 Windows G1 已完成 INDEX→HISTORY→REFERENCE→PREPARE→PUBLISH，发布
`release_id=08eb9b31…`、manifest `d3923fa1…`；独立磁盘 `verify_g1_release` 正在后台执行，通过前仍不把
Windows G1 Gate 标记为最终关闭，且 Windows 结果不替代 Linux/ext4 Gate。隔离 development/example 路径已完成
G2B、G2C、G3A、G3B、G4A，并通过 G4B parent/fresh-worker/receipt 与 G4C 监督对齐/无标签 inference
阶段验收；development 结果不升级为 formal verified artifact，也不关闭真实 Qlib、正式 G2–G9 或性能
Gate。正式 G1 Windows 发布物已通过磁盘验收；正式 G2A 与 development G5A 为两条互不阻塞的推进线，
Linux/ext4 Gate 仍单独保留。
当前状态与返工顺序以代码、根 [`项目实施路线图.md`](../../../../项目实施路线图.md) 和 [`CODEX_HANDOFF.md`](../governance/CODEX_HANDOFF.md) 顶部最新摘要为准；截至2026-07-31的旧总览仅保留在 [`archive/agent-history/`](../../agent-history/README.md) 供审计。
本文是 **M3 实现契约的 SSOT**；技术选型理由仍以
[`../A股港股通个人量化投研交易系统调研.md`]（历史路径 `../../A股港股通个人量化投研交易系统调研.md`，当前仓库未收录）
为准，里程碑状态以 [`../项目实施路线图.md`](../../../../项目实施路线图.md) 为准。
当前 D1–D8 的执行范围和禁止事项见 [`M3另一个Agent任务单.md`](../../M3另一个Agent任务单.md)。

> **2026-08-13 路线定位：** M3 是机器学习基准与 formal 晋级稳线，不再是开始日常策略研究的
> 全局前置。新策略先在 M2 已验收的数据、`target_weight` 和统一事件回测器上走轻量
> 研究 MVP；M3 honest 300 长运行作为后台 S3 基准继续推进。候选要进入 PAPER/影子/实盘时，
> 才按风险逐级消费本文冻结的 verified artifact、fresh verification 和 G9 准入能力。实施优先级
> 以 [`M3_M4实施总规划.md`](M3_M4实施总规划.md) 和根目录 [`项目实施路线图.md`](../../../../项目实施路线图.md) 为准；本文的严格契约继续有效，但只在对应晋级边界触发。

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
