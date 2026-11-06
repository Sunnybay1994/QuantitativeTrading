
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
  [`M3_G2-G3Provider与标签对账实现初验任务单.md`](../../M3_G2-G3Provider与标签对账实现初验任务单.md)。

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
合并任务与根因见 [`M3_G4-G6研究链实现与初验任务单.md`](../../M3_G4-G6研究链实现与初验任务单.md) 和
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
5. G7 formal target、backtest plan、八表 facts、公司行动状态机、开盘撮合、三场景账户回放与 29 文件
   backtest artifact 已完成 Windows 工程闭包，并由 honest 300 public CLI 实际消费。
6. G8A registry、G8B StageRunner、formal backtest/tracking 单 WORK wave、fresh-process reproducibility、fake
   full DAG 与 C0/C1 已完成；C1 honest 300 在最终 revision 完成首发与 completed resume。C2 单 work
   `tracking` public CLI 已接线并通过正常开发检查，尚未在 honest 300 retained tree 上登记真实 MLflow run。
   `run-all` 仍未实现，Linux/ext4 Gate按当前项目阶段暂缓。
7. G9A–G9G 的 quality、evidence plan、分层审计、PASS-only publication/CLI 与 fake integration 已完成 Windows
   工程闭包；honest 300 backtest 证据已取得。真实 tracking markers/remote observations 与最终 acceptance
   report 尚未生成，因此 M3 总 Gate 仍未关闭。

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
