# quant-handbook 项目调研与本项目借鉴分析

调研日期：2026-10-29。对象：[QuantMLResearch/quant-handbook](https://github.com/QuantMLResearch/quant-handbook)。

外部源码固定版本：`29665c79e83aad17aba971721e2f28882630bc25`。GitHub API 返回该提交的 committer 时间为 `2026-10-29 07:37:31 UTC`。本报告的源码链接固定到该提交，后续版本变化须另行核对。

本地对照：调研时 HEAD 为 `9bc575ca1a45ba0888ed9abc21a4bff8e4b95c52`，结合当前工作区的研究协议、相关模块与文档。已有 QuantMind 调研和排行榜修改保留；本次仅新增本文及导航。

## 1. 结论

quant-handbook 是一套面向 A 股的量化教学与示例工程，最适合当作**方法解释、反例设计和小规模正确性对照的参考库**。它没有提供经过真实长期市场验证的策略收益证据，也不是可直接接入本项目的完整交易平台。

相较前一项 QuantMind，本文对象更重视“某个算法或账户行为为什么正确、如何用小样本验证”。目录树实际包含 31 个讲次 Python 脚本、4 个 `test_*.py` 测试文件，另有数据、因子、机器学习和组合工具模块。README 也明确说明默认使用合成教学数据，测试通过不代表真实收益。[H1]

对本项目最有价值的内容按用途排序：

1. **执行反例**：开盘成交不应受到当日稍后的高低收盘价影响；未成交不得释放虚构资金；同一份流动性不能重复使用。
2. **时间隔离**：按日期整组处理标签区间，模型冻结、校准和最终评估分开；旧财报晚到更正不能覆盖更新报告期。
3. **单位闭合**：排序分数与持有期收益分开，年化协方差与持有期风险分开，成本与换手的单位明确。
4. **归因和解释**：将现金、交易费用、共同风格与残差区分，避免把未解释收益直接命名为纯 alpha。

本项目已有 PIT、因子电池、风险归因、容量诊断、公司行动和模拟账户等实现。后续应先用这些教学反例核对实际路径，发现缺口才补定向实现；不重新搭建教程中的通用框架。

## 2. 证据范围与核验方式

本次通过 GitHub 公共目录 API 固定版本和核对文件，通过仓库读取接口阅读代表性源码、测试和正文；结合本地协议与实现进行静态对照。

已深入阅读的主题包括 PIT 财务、时序切分、排序收益校准、选股流水线、因子 IC、OFI、组合优化、成本约束、开盘撮合、公司行动、监控，以及机器学习/执行测试。没有逐行审计全部 31 讲，也没有重新打开其引用的每篇论文或交易所规则。

本次**未安装外部依赖、未执行其 unittest、未构建文档站、未下载真实行情、未复现策略收益**。后文“测试覆盖”指仓库中存在相应断言，不是本次运行通过。数学或工程建议是结合源码的判断；仓库宣传语和教学输出不作为实验结果。

## 3. 项目结构、内容与运行方式

### 3.1 内容地图

| 模块 | 讲次 | 主要内容 | 对本项目的直接价值 |
|---|---|---|---|
| 工程与认知 | 01–04 | 盈利/成本、回测偏差、Polars/DuckDB、数据落库 | 检查计算口径与数据分层；不必迁移技术栈 |
| 数据与 PIT | 05–08 | 动态股票池、财报修订、行业事件、截面检索 | 覆盖晚到修订、可见时间、候选资格与持仓的区别 |
| 特征工程 | 09–13 | 量价、财务、OFI、预处理、中性化与正交化 | 算子边界和小样本数学对照 |
| 因子评估 | 14–17 | IC/HAC、分层、衰减、伪 alpha 排查 | 对照现有电池和失败诊断，不替换准入 |
| 金融 ML | 18–22 | Purged/CPCV、LightGBM、SHAP、深度模型、选股 | 标签成熟、冻结预测、收益校准与独立测试 |
| 风险与组合 | 23–26 | 多因子风险、TE 约束、换手成本、风险平价/HRP | 风险单位、求解可行性和研究对照 |
| 回测执行 | 27–29 | 事件账户、费用/冲击、开盘限制、公司行动 | 订单/账户守恒及无前视反例，优先阅读 |
| 归因监控 | 30–31 | Brinson/因子归因、相对净值、PSI、滞回控制 | 归因闭合与输入错误处理，阈值不可直接套用 |

该表依据 README 的课程映射和实际文件树；没有把每讲标题中的“工业级”“全真”等用语视作生产认证。[H1]

### 3.2 技术形态

- 文档：VitePress，含数学渲染和 Mermaid。
- Python：独立 `examples.lecture_XX_*` 脚本，使用共享的 `common.py`、`fixtures.py`、`factor_utils.py`、`ml_utils.py`、`portfolio_utils.py`。
- 基础依赖：NumPy、Pandas、Polars、PyArrow、SciPy；并非完全消除 Pandas。
- 可选组：`data`、`ml`、`deep`、`optimization`，分别涉及 AKShare、LightGBM/SHAP、PyTorch、CVXPY。
- 解释器范围：`>=3.11,<3.14`，使用 `uv.lock`；`tool.uv.package=false` 表明它按示例项目组织，而不是本次已确认可直接安装的业务 SDK。[H2]

`package.json` 的 `test:examples` 会启用 ML、deep、optimization 三个可选组并运行 unittest。目录树中未发现 `.github/` 工作流文件。因此可以确认存在本地测试入口，不能从 README 徽章推断持续集成已经自动验过每次提交。[H3]

下列为外部项目的参考命令，本次没有运行；将来如需复现，应在独立目录/环境中使用固定提交，不修改本项目依赖：

```bash
uv sync --locked
uv run --locked python -m examples.lecture_18_financial_cv_purging_embargo
uv run --locked --extra ml python -m examples.lecture_22_ml_stock_selection_pipeline
# 该入口会启用深度学习与优化依赖，不是最轻量的首个检查：
npm run test:examples
```

## 4. 与本项目的关系

本项目以 [研究协议](../../RESEARCH_PROTOCOL.md)、[架构](../../ARCHITECTURE.md) 和 [路线图](../../../项目实施路线图.md) 为准。教程里的统计阈值、假设成本、交易日数、股票池和资金规模都不自动成为本项目规则。

| 主题 | 本项目可核对入口 | 参考方式 |
|---|---|---|
| IC/统计 | `research/factor_battery_statistics.py`、`reporting/rolling_signal_monitor.py` | 核对无效截面、重叠标签和实际频率，维持原电池 |
| 模型前向 | `reporting/daily_forecast_monitor.py` | 继续要求提前留存、冲突识别和历史演练分离 |
| 特征健康 | `reporting/factor_health.py`、`data/daily_factor_health.py` | 对照常量/缺失 PSI 处理，不直接连接交易熔断 |
| 执行与公司行动 | `backtest/daily_simulator.py`、`backtest/corporate_actions.py`、`execution/` | 追踪实际调用链后补针对性反例，不改冻结 M3 |
| 容量与成本 | `portfolio/capacity_limits.py`、`research/capacity_diagnostic.py` | 比较 AUM/ADV 单位和成交参与率；保留三档成本 |
| 风险归因 | `reporting/risk_factor_attribution.py` | 核对滞后暴露、现金/费用/残差，不将风险解释冒充准入基准 |

以上是阅读入口清单，不宣称每个文件都是当前日更必经路径。特别是历史/冻结模块须先确认消费者，不能因教程提供简洁实现而替换已有兼容逻辑。

## 5. 代表性源码分析

### 5.1 PIT：先还原版本，再选择报告期

`AsharePITFinancialEngine.snapshot` 先过滤 `available_at <= cutoff`，再在每个 `(symbol, report_period)` 内取当前可见的最新版本；默认结果最后按最新报告期选择。这样可避免旧年报在晚到更正后覆盖已披露的新季度。[H4]

这是值得保留的具体反例：公司已披露新一季报，后来更正上一年年报；查询默认最新财务指标不应退回年报。显式指定旧报告期时，仍应能看到当时已知的修订。

边界：

- 生产数据必须真实保留首次披露、修订版本和到达时间；查询代码无法恢复供应商未提供的历史。
- 示例按 15:00 拼接日线和财务。README 明确承认这是假设，生产需要计入实际入库延迟。
- 时间戳采用先转换到上海时间、再保存为本地无时区值的约定。接入时必须映射本地时间契约，不能直接去除 UTC 时区。
- 多报告期、同比、TTM 的构造不能被“最新一行”替代；财务同比增长也不自动等于分析师预期差或 SUE。

### 5.2 交叉验证：日期整组与实际标签结束时间

`interval_coordinates` 支持逐行提供 `label_end_dates`，并按特征日期取组内最晚标签终点。`PurgedGroupTimeSeriesSplit` 仅使用测试开始前、标签已经结束的训练日；清洗后空训练集会报错。前向切分的 `embargo_pct` 仅保留兼容参数，源码解释该路径不使用未来训练段。[H5]

`CombinatorialPurgedCV` 支持测试块两侧清洗及测试标签结束后的 embargo，并明确说它不拼接回测路径、不计算 PBO。这个边界比仅宣称“支持 CPCV”更有用。

本项目可参考的测试要求：

- 同一日期的股票不得因标签长短不同被拆散到训练与测试。
- 标签终点等于测试起点时也应按选定闭区间规则隔离。
- 持股期/实际结束日可变时，不能仅按固定行数删除。
- 未提供标签结束日期时，调用方必须保证输入为完整且一致的交易日历。

教学 `demo_dates` 使用普通工作日序列，源码明确它不是交易所日历。CPCV 中使用未来时间块训练的研究切分，也不等于模拟真实时点只能用过去数据的 walk-forward。不可把切分组合数当成独立样本数量或新增前向历史。

### 5.3 排序到收益：先校准，后谈优化

`RankReturnCalibrator` 在模型冻结后的历史预测上拟合截面百分位到持有期超额收益，要求校准标签在 `as_of` 之前成熟，并禁止将后来拟合的校准器用于更早决策。输出不自动年化。[H6]

第 22 讲示例依次划分训练/早停、模型冻结后的校准、最终诊断与当前选股；还限制后来训练的模型回填历史交易信号。目标权重与下一日撮合明确分开。[H7]

这些实现有助于防止直接把 LambdaRank 分数当收益输入组合目标。但仍有调用方责任：

- `model_available_at` 是传入值，类本身不能证明分数确由该时刻冻结的模型生成。
- 校准器记录 `horizon_days`，并不自动验证每条标签的真实起止交易时点、收益指数口径和预测数据来源。
- 示例用截面均值收益构造超额，是教学基准，不能替代本项目预注册收益指数。
- 同日排名计算必须基于明确股票池；缺失、停牌与过滤顺序变化可能改变百分位含义。
- 线性校准不证明收益关系稳定，应报告留出段校准误差与不确定性。

若本项目继续采用等权 Top5，收益校准并不是必须增加的步骤。只有确实要按预期收益配置权重，且现有分数与收益单位不匹配时，才需要研究它。

### 5.4 特征预处理：全缺失填零是教学选择

第 22 讲在同日截面计算中位数、MAD 裁剪和标准化，常量或全缺失截面最后落为零。这个处理可使示例继续运行，但不能证明真实日更输入可用。[H7]

本项目应沿用已有缺失覆盖和数据质量约束。对一个突然整列缺失的关键特征，先报告真实故障；是否允许已注册的降级模型另行决定。不得借用教程填零逻辑绕过数据问题。

### 5.5 IC：均值检验与收益结论分开

第 14 讲计算逐日 Pearson/RankIC，显式保留无效日期；累计曲线中填零仅作展示，统计使用有效截面。启用 HAC 且存在被排除日期时拒绝删行压缩时间。公共工具说明 HAC 不能解决数据窥探和多次试验。[H8]

需要区分默认与可选：`hac_lags` 默认是零，即 iid 均值检验；非零带宽需要调用方按标签重叠等设置。年化 ICIR 采用平方根时间缩放，也不自动解决序列相关。

对本项目而言，该模块可作为小样本计算对照。最终因子仍走原全历史电池，保留真实频率、HAC 设置、候选尝试数量和成本。合成数据预先注入特征—收益关系后测出的 IC，不是发现了真实市场信号。

### 5.6 高频低频化：先区分数据能力

第 11 讲源码按 `(symbol, trade_date)` 分组滞后，计算最佳报价变化对应的 OFI，再聚合为日频因子，避免跨日衔接。[H9]

正文存在较强的效果叙述，包括典型夏普范围、容量和微观解释力；本次未逐项追溯原始研究，不把这些数字用于本项目判断。短时价格解释能力也不能直接转化为次日可交易收益。

分钟 OHLCV 无法重建买卖报价和队列，三秒快照也不等同逐笔事件。若现有数据不含可信的盘口历史、单位及到达时间，不能用分钟量价代理后仍称原始 OFI。当前只保留方法线索；不为复现教程新增 L2 数据采购或秒级系统。

### 5.7 组合优化：单位自洽，但目标与本项目不完全相同

第 24 讲以持有期预期收益为 alpha，输入年化因子协方差和特异方差；目标中的风险按持有期换算，年化 TE 保留独立硬约束。求解后检查可行性，不通过简单裁剪/重新归一化掩盖约束破坏。[H10]

第 25 讲在此基础上加入线性换手成本和与 AUM、历史 ADV、波动率相关的二次冲击惩罚，并明确不做全截面再归一化。它的 `turnover` 为本次 `0.5 × L1` 权重变化；不能直接与本项目按实际成交额/年度日均净值计算的年化换手比较。[H11]

限制与适配：

- 指数增强示例要求全额投资、行业中性、主动权重限制；可能与个人 Top5 集中持仓和现金要求冲突。
- 连续权重满足 TE/换手约束，不代表整手、最低佣金、T+1、停牌和现金限制后的实际订单仍满足。
- 目标函数中的近似成本与真实回放费用不是同一事实来源，最终要通过统一账户及三档成本重算。
- 二次冲击惩罚与第 28 讲平方根型冲击模型不应混称同一个已校准模型；参数需要现实成交证据或明确压力假设。
- 本项目现有依赖没有因此自动增加 CVXPY；先发现实际组合问题，再决定是否需要新求解器。

### 5.8 撮合和公司行动：优先借鉴反例

第 29 讲 `DailyMarketBar` 将开盘、限价、停牌、显式开盘流动性与高低收盘字段区分；撮合函数只读前一组。未知开盘流动性默认为零，触及不利限价时保守拒绝，不推断当日后来是否开板。[H12]

`CorporateActionBook` 在登记日冻结权益，在除权日确认应收红利与股份，在派息日和送股上市日分别释放；重复阶段不会二次到账，零碎股需上游提供结算结果。第 27 讲账户还处理现金、持仓、应收、T+1 和同日流动性消耗。[H13]

执行测试中值得复用的设计：

| 仓库断言 | 要保护的行为 | 本地参考方式 |
|---|---|---|
| 改动当日 high/low/close，开盘撮合结果相同 | 后续行情不能参与开盘决策 | 在实际执行函数上做不变性测试 |
| 同日买入不可立即卖出，下一交易日才可卖 | 可卖份额与总持仓不同 | 结合本地证券规则区分 T+0/T+1 |
| 第二笔订单不能重复使用第一笔已消耗流动性 | 成交容量守恒 | 检查部分成交和重试路径 |
| 全仓目标保留费用，现金不负 | 权重不等于可成交股数 | 覆盖 10 万元账户、整手和最低佣金 |
| 登记持仓冻结、应收、支付、上市与重复调用 | 权益时点和账本幂等 | 对照现有公司行动，不替换冻结模块 |
| 缺行情、日期倒退、重复收盘报错 | 不能默默生成净值 | 在最小日更路径核对失败结果 |

这些是阅读到的测试断言，本次未执行。[H14]

边界也必须保留：显式流动性字段需要可信来源，不能用当日全日成交量事后填入开盘；保守限价拒绝不模拟真实排队；公司行动例子不覆盖税补扣和零碎股分配。账户对象和事件处理集合主要在内存中，本次所读示例未提供完整进程重启持久化恢复链路。

### 5.9 风控监控：滞回有用，阈值仍须本地验证

第 31 讲包含相对净值回撤、TE、风格暴露、PSI 和控制输出。最高风险状态锁定，恢复需要显式复位；数据错误不会自动解除原有最高风险状态。执行测试还验证控制结果确实阻止新增买单。[H15][H14]

可借鉴：观测值与控制结果分开、输入不可靠不能默认为健康、风险恢复不在阈值附近反复抖动。不可直接照搬：示例数值阈值、三级审批流程和 PSI 自动禁止买入。本项目不新增治理层，任何策略控制变化都要按既有规则证明必要性。

PSI 是输入分布差异，不能独立识别预测关系变化或证明失效。该点与前一份 [QuantMind 调研](QuantMind项目调研_20261029.md) 的联合诊断方向相通。

## 6. 与前期调研的衔接

| 对象 | 最适合参考的内容 | 当前借鉴方式 |
|---|---|---|
| TradingAgents | 多角色分析和多空质询 | 生成候选机制与反例，LLM 不直接交易 |
| daily_stock_analysis | 报告工作台与通知 | 优化信息交付，复用现有结果 |
| QuantMind | 研发流程、预测诊断与运行衔接 | 窄模块增量研究，避免迁移整个平台 |
| quant-handbook | 数学/时间/账户的示例和测试 | 用小反例检查当前真实调用链，必要时补测试或修复 |

前两项沿用本会话此前调研，本次未重新核对其最新版本。该表用于区分参考价值，不是同日功能排名。

## 7. 后续有界工作建议

### 7.1 首项：用不变性反例核对真实模拟路径

先定位当前订单→成交→持仓→净值的最小调用链，阅读现有对应测试。仅对尚未覆盖的场景增加定向反例：未来 high/low/close 扰动、未成交留现金、重复流动性、同日可卖量、公司行动重复与缺失行情。

成功产物应是具体缺口及其修复，或明确已有覆盖无需变更。若改动影响执行，定向测试后重放一个冻结账户，对比订单、费用、持仓和净值；业务结果放机器报告，不在本文手写收益。没有具体缺口就停止该分支，不新建另一套回测器。

### 7.2 第二项：核对模型/校准/评估的时间边界

当未来研究需要从排序转向收益加权时，参考 H5–H7。先核对实际标签起止、模型冻结、校准样本成熟和最终测试段；固定校准方法后只做一次有界比较。等权 Top5 仍可作为基线。

对照至少包括：修改尚未成熟标签不能改变当时模型；晚到重跑预测不能替代原前向记录；后拟合校准器不得回填历史决策。指标按当前协议、实际持股期和收益指数测量。新增因子仍走电池，模型/组合变化才进入策略级预注册。

### 7.3 储备：成本与风险优化

仅当现有结果显示组合层面存在可定位的风险或执行成本问题时，阅读 H10–H11。先用本地真实资金档、最低佣金、ADV 和整手约束做确定性小例子，再考虑是否需要优化器。

优化器预期改善不能作为收益事实；最终看统一回放的 0.5×/1×/2× 成本、换手、不可成交和风险调整收益。沿用路线图既有换手豁免和准入规则，不临时改变门槛，不用短期最优曲线选择规则。

### 7.4 暂不推进

不因课程内容齐全而采购 L2、引入深度模型、重建 PIT 平台、改造正式身份体系或开启券商自动下单。本次调研不启动任何新实验、付费订阅或账户变更。

## 8. 许可、数据和工程限制

固定提交的递归文件树中未发现 `LICENSE`、`COPYING` 或 `NOTICE` 文件。本次也未确认其他明确允许复制/修改/再分发代码的授权声明。**公开可读不等于已有明确复用许可证**；后续直接复制代码前应补查授权，当前报告以链接、方法分析及自行设计反例为主。该发现不等于法律结论。

合成测试数据可验证指定例子的数学与状态变化，不能覆盖真实供应商版本、停牌/退市历史、财务修订、极端行情和长期统计功效。真实研究仍需要本地数据与现有电池。

第 4 讲年度行情 upsert 使用临时文件原子替换；原子写能避免半文件，不代表 raw 不可覆盖或已保留历次供应商响应。[H16] 借鉴到本项目时必须维持 raw 追加留档，不把示例数据湖当作原始层完整方案。

教程正文部分用语和示意性能数字较强，示例头部、README 的边界说明更克制。判断应同时看代码、测试和输入契约，不能仅凭“工业级”“100% 离线通过”“全真”推断生产可靠性。

## 9. 推荐阅读顺序与核验记录

建议先读 27/29 及执行测试，再读 06/18/22 和 ML 测试，随后按实际问题读 14/17、24/25、30/31。11 讲只作数据能力明确后的方法储备。学习目录可用，没必要按 01–31 顺序重新建设本项目。

本次可复现的核验记录：

- GitHub API 固定提交并遍历文件树：31 个讲次脚本、4 个测试文件、6 个共享/包入口 Python 文件；未发现许可证命名文件和 `.github/` 工作流。
- 仓库读取接口核对本报告所列代表性文件；未下载整个仓库或写入外部代码到业务目录。
- 本地对照了当前研究协议、因子健康/前向监控、风险归因、公司行动和容量相关模块及测试入口。
- 文档交付检查包括本地链接存在性、Markdown 空白、固定提交链接一致性、单文件大小与行数；不冒充外部算法运行结果。

后续实验写入独立机器产物目录，本文只追加源码版本变化、方法判断和产物链接。若上游发生修改，应核对具体函数差异，保留本次基线，不直接将新 README 描述当成旧版本事实。

## 10. 固定版本来源索引

所有外部源码链接固定到 `29665c79e83aad17aba971721e2f28882630bc25`：

- **H1** [README](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/README.md)：定位、课程映射、合成数据声明、运行方式及实现边界。
- **H2** [pyproject.toml](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/pyproject.toml)：解释器、基础依赖及可选组。
- **H3** [package.json](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/package.json)：VitePress 与全量测试入口。
- **H4** [lecture_06_pit_financial_engine.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_06_pit_financial_engine.py)：财务可见版本和最新报告期选择。
- **H5** [lecture_18_financial_cv_purging_embargo.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_18_financial_cv_purging_embargo.py)：前向与 CPCV 的不同边界。
- **H6** [ml_utils.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/ml_utils.py)：日期区间、purged holdout、RankIC 和收益校准。
- **H7** [lecture_22_ml_stock_selection_pipeline.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_22_ml_stock_selection_pipeline.py)：截面清洗、模型训练、冻结、校准与收盘目标。
- **H8** [lecture_14_factor_ic_metrics.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_14_factor_ic_metrics.py)、[factor_utils.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/factor_utils.py)：IC、无效截面、HAC 和显示指标。
- **H9** [lecture_11_high_freq_to_low_freq.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_11_high_freq_to_low_freq.py)、[第 11 讲正文](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/module_03/11_high_freq_to_low_freq.md)：OFI 状态转移、分组与数据/效果叙述。
- **H10** [lecture_24_cvxpy_portfolio_optimization.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_24_cvxpy_portfolio_optimization.py)、[portfolio_utils.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/portfolio_utils.py)：预期收益、年化风险、TE 约束及求解检查。
- **H11** [lecture_25_turnover_constraints_and_costs.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_25_turnover_constraints_and_costs.py)：权重换手、线性成本、AUM/ADV 冲击惩罚。
- **H12** [lecture_29_matching_rules_limits_suspensions.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_29_matching_rules_limits_suspensions.py)：开盘撮合和公司行动阶段。
- **H13** [lecture_27_vectorized_vs_event_driven_backtest.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_27_vectorized_vs_event_driven_backtest.py)：事件账户、T+1、费用、流动性与权益。
- **H14** [test_execution_monitoring.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/tests/test_execution_monitoring.py)、[test_ml_risk_modules.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/tests/test_ml_risk_modules.py)：本文关注的执行和模型测试断言。
- **H15** [lecture_31_live_monitoring_risk_dashboard.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_31_live_monitoring_risk_dashboard.py)：监控、PSI、风险控制与复位。
- **H16** [lecture_04_industrial_data_pipeline.py](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_04_industrial_data_pipeline.py)：原子替换、行情 upsert 和在线取数边界。

补充阅读：[伪 alpha 排查源码](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_17_fake_alpha_forensics.py)、[公开资源导读](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/resources.md)、[第 18 讲正文](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/module_05/18_financial_cv_purging_embargo.md)。

本地权威规则：[AGENTS.md](../../../AGENTS.md)、[研究协议](../../RESEARCH_PROTOCOL.md)、[架构](../../ARCHITECTURE.md)、[路线图](../../../项目实施路线图.md)。本文是外部项目调研，不新增准入门槛或运行前置条件。
