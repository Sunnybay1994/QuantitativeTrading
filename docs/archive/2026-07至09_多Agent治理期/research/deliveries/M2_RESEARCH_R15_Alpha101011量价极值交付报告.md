# M2 Research R15 Alpha101 #011 量价极值交付报告

> task id：`M2-RESEARCH-R15-ALPHA101-011-VWAP-VOLUME-EXTREMES`
> 状态：`DELIVERY_READY / STATIC_ONLY / IMPLEMENTED_PENDING_REVIEW_AND_VALIDATION / ECONOMIC_IO0 / TRIAL0`

## 1. 交付结论

本包完成了`alpha101_011`本地A股适配的窄静态实现、单元测试合同和冻结配置。实现严格保留原式的三个独立
横截面rank结构：三session复权VWAP-close价差最大值、三session复权VWAP-close价差最小值，以及raw volume
lag3差分。三个组件各自在自己的finite证券集合中使用升序average-tie零一归一rank，最终计算
`(r_max + r_min) * r_volume`。

本交付没有接入runner、label、shared evaluator或公共receipt，没有读取数据或收益，没有运行Python、pytest、
Ruff、mypy或回测。因子当前仍为`UNASSESSED`；静态实现和公开公式都不能证明其在A股、long-only Top50和真实
成本下有效。

## 2. exact实现范围

实现Worker仅新增任务书批准的四条路径：

1. `src/quant/factors/classic_ninth_batch.py`；
2. `tests/unit/test_classic_ninth_batch.py`；
3. `configs/research/m2_classic_daily_factors_ninth_batch.toml`；
4. `docs/research/deliveries/M2_RESEARCH_R15_Alpha101011量价极值交付报告.md`。

任务书、roadmap、共享报告、`quant.factors.__init__`、runner、evaluator、schema和repository均未修改。

## 3. 实现说明

### 3.1 VWAP与复权gap

- `raw_vwap = amount / volume`，amount按元、volume按股；
- amount和volume只有同时finite且严格大于0时才形成VWAP；零值只使该行gap为null；
- `adjusted_vwap = raw_vwap * adj_factor`；
- `adjusted_close = close * adj_factor`；
- `adjusted_gap = adjusted_vwap - adjusted_close`；
- 不使用百分比gap、epsilon、填0、上一日VWAP或横截面均值。

乘除法或差分产生非finite时整次计算fail-closed。close、volume、amount和adj_factor的bool/NaN/Inf在计算前
拒绝；Bar1dSchema继续负责价格正值、成交非负和OHLC等基础契约。

### 3.2 严格session窗口

实现先构造symbol×frozen sessions完整网格，再回贴原始bar：

- gap max/min必须有`t-2..t`三个连续finite gap；
- volume delta固定为`volume_t - volume_t-3`；
- volume端点允许0，但`t-3..t`四个session都必须有bar；
- 内部或边缘缺bar不使用上一可用观测桥接；
- 输出只回到原bars已有key，不补写网格行。

因此第一个可能形成的因子值需要四个连续session，而不是三个或五个。

### 3.3 三个独立横截面rank

公共计算内部依次对`gap_max_3`、`gap_min_3`和`volume_delta_3`调用同一个窄rank helper，但每次count、average
rank和归一化分母都来自该组件自己的finite集合。有效数少于2时该组件rank全为null。实现没有先求共同交集、
没有先合成再rank，也没有使用dense/min/max/descending rank。

最终只在三个rank对同一symbol/date全部存在时形成Float64值，并验证范围`[0,2]`；零值显式规范为正零。

### 3.4 公共身份与配置

模块输出：

- `NINTH_BATCH_FACTOR_SPECS`；
- `NINTH_BATCH_FACTOR_NAMES = ("alpha101_011",)`；
- `compute_ninth_batch_daily_factors(bars, *, sessions)`。

配置冻结catalog、hypothesis、VWAP/复权gap、3-session extrema、raw-volume lag3、4-session bar要求、组件独立
ascending average normalized rank、minimum symbols=2、expected direction=+1，以及close-known到next-open时间
语义。`trial_delta=0`且`economic_execution=BLOCKED_PENDING_PUBLIC_RECEIPT_AND_RUN_TASKBOOK`。

## 4. 静态测试合同

新增测试覆盖：

- raw amount/volume VWAP与同一adj_factor作用于VWAP和close；
- gap extrema三session、volume lag3四session和off-by-one；
- 内部/首尾缺口不桥接；
- 三组件不同finite集合、不同分母、average tie和`n<2`；
- 最终公式、`0/2`边界、正零及`[0,2]`范围；
- raw volume lag3，不使用一日变化、ratio、log或复权volume；
- zero amount/volume局部null，以及lag端点zero volume仍能形成volume delta；
- duplicate key、calendar越界、session乱序/重复；
- bool、NaN、Inf、schema负值和VWAP/复权乘法溢出；
- 行置换不变、input-only keys、exact columns/order/dtypes；
- TOML exact key/order/value/type、固定方向、close→next-open和经济阻断。

这些测试当前仅作为待执行合同落盘；本阶段禁止运行，不能将其存在表述为PASS。

## 5. 验证与资源事实

- Python：`0-call`；
- pytest/Ruff/mypy/cold：`UNRUN`；
- data/raw/snapshot/run/ledger/holdout：`0-read`；
- label/evaluate/backtest：`0-call`；
- trial delta：`0`；
- network：`0-call`；
- stage/commit：`0`；
- CPU lease：`NONE`。

本阶段只允许静态独立review。review通过后，仍须由统筹另行授权Windows开发验证；Windows反馈也不能替代
WSL/Linux目标平台Gate或未来真实经济检验。

## 6. 剩余风险与下一步

1. 原论文并未逐字冻结本项目的amount/volume单位、复权、tie和缺失语义，本实现是明确标注的本地适配；
2. `vwap-close`保留价格尺度暴露，未来须诊断价格、市值、行业、复权断点和低价股贡献；
3. volume jump可能被异常成交、公司行动、停牌复牌或微盘驱动，必须独立报告；
4. 横截面组件集合不同会使最终交集coverage下降，未来必须披露三个分母和最终coverage；
5. expected direction `+1`只是预注册假设，反向证据只能拒绝，不能在同一attempt翻向；
6. receipt、snapshot、candidate universe、fold、cost、signal dates和admission尚未形成运行身份。

下一步顺序固定为：独立静态review → 另获授权的focused Windows开发验证 → 公共receipt合流后另立
runner-integration/run任务书 → 真实walk-forward与成本/容量/状态诊断。当前不得产生有效性、promotion、PAPER
或LIVE结论。

## 7. Validation1 原生证据追加与替代实现收口

本节仅追加既有 Validation1 证据，不重跑、不补造、不删除任何现场。证据根目录为
`artifacts/agent_runs/m2-research-r15-alpha101-011-vwap-volume-extremes-windows-validation1`。
执行与当前只读 HEAD 均为 `dfe49df5e8dfd9d929eb8ad196beced1da19715d`，branch 为
`codex/m2-research-r15-alpha101-011-vwap-volume-extremes`。

### 7.1 产品阶段结果

| 阶段 | 原生 stdout 结论 | stdout bytes / SHA256 | exit / stderr |
| --- | --- | --- | --- |
| focused `test_classic_ninth_batch.py` | `23 passed, 258 warnings in 3.75s` | `1119 / 6b576f534222b6a6901d3a56e9c167c96bab155c31fc3f4ff74ccf3fa1e3dc97` | `0 / 0 bytes` |
| Ruff production+test | `All checks passed!` | `19 / 82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` | `0 / 0 bytes` |
| mypy production | `Success: no issues found in 1 source file` | `43 / 8e63ae22e8213e327a5e9cbd584067681681bd8ef7f25c869877887ccdcfc4ff` | `0 / 0 bytes` |
| config/cold identity node | `1 passed in 2.09s` | `100 / edfbe512ab5943799cf48447d110ec71dc2a90f7b8e906f1ba9c86ccf7b8a94e` | `0 / 0 bytes` |

四个 exit 文件均为 `2 bytes / 9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`，内容为 `0` 加 LF；四个 stderr 均为 `0 bytes / e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。focused 的 258 条 warning 是 Pandera/Polars horizontal concat 弃用提示，不在本包顺手升级依赖。

配置节点只证明 tracked config identity 与普通 factor import surface 的测试合同；未调用 runner、repository、data loader、label/evaluator、receipt 或 output writer。配置冻结 identity 为 `configs/research/m2_classic_daily_factors_ninth_batch.toml`，`3227 bytes / 633f49256ecda29daaf3039e3a7684bfa5be617ea869b6d530594708cd088674`。

### 7.2 scope、资源和保留现场

原生辅助证据为：`run_contract.json` `3789 bytes / fb632de24a5f9373690dea9169454fd3643f10c5e07187b220cde0dc4b3a555b`；`scope_exact6.json` `2502 / 23d8de31144bbf45826b678a5d0aa947bb20b367dde91fda9013d318c8b314e8`；`scope.json` `1060 / 1e4187df6ef3c26866a3f10fbbfb5b02ca47b7c5c8a991dcca834d61edbb01ac`；`resource_before.json` `52 / 82ca5bd040369b44cf4622ff27a45704b42243d91c1f61b2d9d133b768997c83`；`resource_release.json` `79 / df7ad0f5d23ae5f6dc70c7f2311f11ad98790f92d0312833c6e1020e00bf4b95`。释放记录为 priority `Normal`、affinity `0xFFF`、`python_processes=[]`，不冒充新的 fresh 资源检查。

scope 记录 actual exact6 全为 untracked、cached 为 0、ordinary `git diff --check` exit 0 但 `tracked_untracked_exact6_coverage=0`，语义为 `VACUOUS_FOR_EXACT6`，不能替代六文件 raw-byte identity/卫生证据。Validation1 Temp 仍为 `artifacts/validation_tmp/m2-research-r15-alpha101-011-vwap-volume-extremes-windows-validation1` 且 `temp_exists=true`；`summary`、`terminal`、`manifest-last` 均缺失。这是任务书 §13.4 冻结的 `FINAL_CLOSURE_INCOMPLETE`，不是 evidence 缺失失败，也不是完整 Gate。不得在本交付中删除 Temp、补写三件终态文件、重跑产品阶段或提交。

### 7.3 替代实现历史与最终边界

中央已明确记录 `AUTHORIZED_IMPLEMENTER_REPLACEMENT`：原 R15 implementer handle 已不存在，本次由唯一获准替代实现者仅完成本交付文档收口；历史 owner、原 review、Validation1 原生证据和矛盾现场均保留，未创建重复实现者、未创建 subagent、未修改 production/test/config/taskbook/review 或任何共享文件。本节也不把替代身份当作新的实现提交或新的 Validation attempt。

本次文档追加后的交付文件 identity 需以追加完成后的 fresh bytes/SHA 为准；追加前历史 identity 保留为 `5970 bytes / 2d1ca30c7edd0714d4d4ae1214a1fc7de3cf7d3a0320e520175641fbf5a57792`。taskbook 当前 identity 为 `41206 bytes / 969b0e10fd898cb16e17c548230b1870c07a6d2eef67cdf8ec3eb9336efc3821`，本次未改写。

最终状态严格保持：`R15_WINDOWS_PRODUCT_STAGES_PASS / FINAL_CLOSURE_INCOMPLETE / ECONOMIC_UNASSESSED / TRIAL0`。产品阶段通过只证明 Windows 开发反馈环的 23 个 focused tests、Ruff、mypy 和 config node 通过；不构成 Linux/WSL Gate、因子有效性、RankIC、Sharpe、真实成本容量、promotion、PAPER 或 LIVE。真实 data/economic I/O、public receipt、runner/run taskbook 仍为后续独立准入事项。
