# quant-handbook 复核与本项目借鉴路径

调研日期：2026-11-08。对象：[QuantMLResearch/quant-handbook](https://github.com/QuantMLResearch/quant-handbook)。

本次在[详细调研报告（2026-10-29）](quant-handbook项目调研_20261029.md)基础上，重新核查上游版本、文件树、代表性源码和当前本地实现。两份文档配套使用：旧报告保留课程与算法分析，本篇更新证据状态、当前差异及后续参考实现边界，不覆盖旧结论。

## 1. 核心结论

这是一个量化研究教程与合成数据示例库，不是已经验证盈利的交易策略，也不是本项目需要整体迁移的业务框架。最有价值的是把 PIT、标签成熟、成本单位和账户守恒转化成具体代码及反例。

本项目已具备相关基础设施。当前合理用途是：遇到实际数据、订单或净值问题时，借助它设计最小反例，检查现有实现；确认缺口后再定向修复。**不能因为教程覆盖全面，就另外建设 PIT 平台、回测器、风险审批体系或深度学习流水线。**

本次没有发现上游新增源码。应优先复用已有详细调研，而不是将一次重复阅读包装成新研究成果。

## 2. 本次可核查事实

| 项目 | 本次核查结果 | 证据 |
|---|---|---|
| 默认分支 | `main` | GitHub 仓库接口 |
| 当前提交 | `29665c79e83aad17aba971721e2f28882630bc25` | [提交记录](https://github.com/QuantMLResearch/quant-handbook/commit/29665c79e83aad17aba971721e2f28882630bc25) |
| 提交时间 | `2026-10-29T07:37:31Z`，GitHub committer 字段 | 同上 |
| 相较旧报告 | 固定提交完全一致，没有源码版本增量 | 旧报告版本与当前分支提交对照 |
| 示例规模 | `examples/lecture_*.py` 共 31 个 | [固定版本目录](https://github.com/QuantMLResearch/quant-handbook/tree/29665c79e83aad17aba971721e2f28882630bc25/examples)及递归树 |
| 测试文件 | `test_execution_monitoring.py`、`test_factor_modules.py`、`test_ml_risk_modules.py`、`test_tutorial.py` | [tests](https://github.com/QuantMLResearch/quant-handbook/tree/29665c79e83aad17aba971721e2f28882630bc25/tests) |
| 许可元数据 | 仓库接口 `license=null`；递归树未找到 LICENSE/COPYING/NOTICE 命名文件 | 仓库元数据与完整递归树 |
| CI 文件 | 固定树中没有 `.github/workflows/` 文件 | 同上；不据此推断所有外部 CI 都不存在 |
| 本地对照版本 | `b36e8a4b471748ccf2dcf89d2b6f3741a66b4c3b`，并结合当时工作区读取 | 本地 `git rev-parse HEAD`；工作区并非干净快照 |

目录统计来自本次成功返回且 `truncated=false` 的[GitHub 递归树 API](https://api.github.com/repos/QuantMLResearch/quant-handbook/git/trees/29665c79e83aad17aba971721e2f28882630bc25?recursive=1)，不是从宣传语推算。首次 PowerShell API 请求认证失败，改用 Python 标准库只读 GET 成功；失败请求产生的空计数未作为证据。

本次重新阅读了开盘撮合与公司行动、ML 时间与收益校准工具、PIT 财务引擎、Purged/CPCV 切分、执行与监控测试，以及依赖声明。其余算法分析沿用固定版本未变的旧报告，不能视作本次逐行重审。

## 3. 项目内容与适用位置

项目按八个模块组织：工程基础、数据/PIT、特征、因子评估、金融 ML、风险/优化、回测执行、归因/监控。文档使用 VitePress，Python 为独立示例加共享工具；不是一套可直接替代 `quant` 的生产 SDK。[README](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/README.md)

其 Python 版本范围为 `>=3.11,<3.14`，基础使用 NumPy、Pandas、Polars 等，可选依赖涉及 ML、深度学习和优化；`tool.uv.package=false`。不能因为有锁文件和测试入口，就推定所有依赖与本项目兼容。[依赖声明](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/pyproject.toml)

| 维度 | quant-handbook | 当前 QuantitativeTrading |
|---|---|---|
| 核心目标 | 解释方法，演示工程契约与数学行为 | 每日可执行订单、模拟净值、风险调整后的真实收益 |
| 默认数据 | 自包含合成夹具，真实源接入需另外完成 | 本地 raw/clean、实际来源与留存记录 |
| 输出组织 | 按讲次运行与教学测试 | `python -m quant`、版本化配置、机器产物与注册表 |
| 时间约束 | 示例按调用方契约检查 | 实际信号、接收/可得时刻、标签成熟与成交时点共同约束 |
| 策略判定 | 测试不能证明市场收益 | 固定电池、实际持股期、收益指数基准及三档成本 |
| 执行范围 | 开盘保守撮合、账户与权益示例 | 统一模拟器、日账户、证券规则及人工订单路径 |
| 投资假设 | 含指增、风险约束和连续权重优化教学 | 个人 A 股/ETF，允许已有预注册集中持仓与现金规则 |
| 自动交易 | 教学控制输出不等于券商执行 | `auto_trade=false`，LLM 不直接交易 |

本地规则依据：[AGENTS](../../../AGENTS.md)、[架构](../../ARCHITECTURE.md)、[研究协议](../../RESEARCH_PROTOCOL.md)。这里是定位对比，不表示本地每条生产路径都已通过运行验收。

## 4. 最值得借鉴的四组具体机制

### 4.1 开盘撮合：不变性与守恒，比增加模型更直接

外部撮合只读取开盘、限价、停牌和显式开盘流动性，不使用当日稍后的高低收价；未知流动性为零。公司行动按登记、除权、派息、股份上市分阶段处理，使用事件和阶段标识防止重复结算。[撮合与权益源码](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_29_matching_rules_limits_suspensions.py)

本次已确认本地有对应代码和断言：

- [开盘与流动性不变性测试](../../../tests/unit/test_matching_invariants.py)：扰动 high/low/close 不改变开盘成交；同一证券当日容量不能重复花费；未成交买单不扣费用、资金留在现金。
- [ETF 公司行动测试](../../../tests/unit/test_etf_corporate_actions_master.py)：只选择已公告的未来事项，除权日买入者不享受登记日旧持仓权益，派息从应收转现金。
- [日账户](../../../src/quant/backtest/daily_account.py)、[统一日模拟器](../../../src/quant/backtest/daily_simulator.py)、[ETF 公司行动主表](../../../src/quant/data/etf_corporate_actions.py)：已有落地入口。

因此，不应再把这些事项写作“本项目尚未实现”。但**源码与测试存在，不等于这次已经重跑测试或验证所有账户**。后续只针对真实调用链未覆盖的边界补测。

适配注意：教程的开盘流动性需要事前可信数据，不能用全日成交量回填；保守拒单不等于真实排队模拟；A 股股票与不同 ETF 的 T+0/T+1 规则不能一概处理；内存中的幂等集合不等于进程重启后的可靠恢复。

### 4.2 PIT：查询正确与历史输入真实，是两回事

外部财务引擎先过滤 `available_at <= cutoff`，再按证券及报告期选择当时可见的最新修订，最后选报告期。这能避免旧年报晚到更正使默认财务快照倒退。[财务 PIT 源码](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_06_pit_financial_engine.py)

可参考的反例是“新季报已披露，旧年报后来修订”，而不是只验证一次普通 as-of join。生产还必须验证首次披露、修订和系统实际接收的来源；一份今天下载的旧公告列表，并不能单靠日期字段变成当年的真实可得数据。

本地 ETF 主表代码已明确标注重建的发行人历史条款与真实采集 `observed_at` 的区别。因此后续评估应逐数据集解释历史口径，不宜将公司行动估值修复、原始前向留存和研究特征 PIT 混为一项“通过”。

### 4.3 ML：标签结束、模型冻结和校准必须独立核对

外部工具按日期整组取最晚标签终点；`purged_holdout` 根据真实结束日期清洗。`RankReturnCalibrator` 把截面排序百分位映射为持有期超额收益，检查标签成熟及禁止把后拟合校准器用于更早决策；它仍依赖调用方证明分数确由冻结模型产生。[ML 公共工具](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/ml_utils.py)

本地[年度训练前缀](../../../src/quant/research/model_training_prefix.py)已有 `known_outcomes`，按 `exit_date_rebalance <= cutoff` 选择已知结果；不能只依据特征日筛训练样本。值得继续核查的是具体模型消费者是否贯穿使用这些边界，而不是新增另一套通用切分框架。

两个容易误读的地方：

- 前向 `PurgedGroupTimeSeriesSplit` 的 `embargo_pct` 为兼容参数，该路径不使用未来训练段；不能看到参数就声称施加了后置 embargo。
- `CombinatorialPurgedCV` 提供切分，但不拼接策略回测路径、不计算 PBO；组合切分数不是独立样本数。[CV 源码](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/examples/lecture_18_financial_cv_purging_embargo.py)

本项目若维持等权 Top-K，并不需要为了学习校准器而强行改变权重。只有明确要优化预期收益、且单位不匹配时，才研究冻结模型后的校准段和最终留出段。

### 4.4 风险、成本与归因：参考单位和反例，不抄阈值

旧报告已分析持有期收益与年化协方差、连续权重与整手成交、`0.5 × L1` 单次换手与账户年化换手之间的差别。后续参考 24/25 讲优化器时，必须先写清这些单位，不能直接套用目标函数后声称交易费用已降低。

第 31 讲和执行测试有 PSI、相对净值及滞回控制。PSI 只能指示输入分布变化，不能独立证明预测关系失效；测试中也明确区分了两者。[执行与监控测试](https://github.com/QuantMLResearch/quant-handbook/blob/29665c79e83aad17aba971721e2f28882630bc25/tests/test_execution_monitoring.py)

本地已有[容量模块](../../../src/quant/portfolio/capacity_limits.py)与[风险归因](../../../src/quant/reporting/risk_factor_attribution.py)。优先检查现金、费用、风格解释和残差是否闭合；残差不自动命名为纯 alpha。示例风险阈值、审批层级和 PSI 禁买规则均不自动引入本项目。

## 5. 与此前几个项目的取舍

以下是既有调研的定位衔接，不是对其他仓库进行本次最新版本复核：

| 对象 | 适合参考 | 不宜据此推断 |
|---|---|---|
| TradingAgents | 多角色分析、反方质询、机制候选 | LLM 辩论形成稳定可交易 alpha |
| daily_stock_analysis | 报告工作台、通知和信息交付 | 信号事后统计等同统一账户回测 |
| QuantMind | 特征、排名、预测、成熟 IC 与模拟损益的联合诊断 | 整套研发平台值得迁移，或重跑预测等同前向证据 |
| quant-handbook | 数学边界、执行守恒、时间隔离的反例 | 合成测试通过就具备长期市场收益 |

QuantMind 的细节见[对应报告](QuantMind项目调研_20261029.md)。对当前项目，quant-handbook 的优先级是正确性参考，QuantMind 更偏预测运行诊断，两者都不能替代订单和净值的真实机器产物。

## 6. 后续参考实现的有界路径

本节是后续方向，**本次没有启动实现或实验，不作为新工作清单**。推进依当前用户授权与[当前清单](../../worklists/工作清单_20261109.md)，不挤占正在运行的采集、回放或账户任务。

| 实际触发问题 | 最小工作范围 | 验证产物与停止条件 |
|---|---|---|
| 账户出现无法解释的跳变或权益异常 | 沿现有日账户与公司行动读取链定位；对缺口补一个反例 | 机器输出订单、现金、应收、持仓、净值差异；已有覆盖且无异常则停止，不建新账本 |
| 训练或选因子疑似使用未成熟收益 | 检查真实退出日、重跑版本、训练截止及消费者 | 扰动未来未成熟标签不改变当时选择；保留原预测，禁止历史回填冒充前向 |
| 明确存在权重或执行成本问题 | 使用现有真实资金档、整手、最低佣金、ADV 和既有冻结配置 | 最终回到统一回放与三档成本；无必要不引入优化器，不扫参救援 |

任何新因子仍按本地电池批量评估；模型/组合规则变更按现有预注册执行。保持实际持股期、收益指数基准、空仓压力窗口标不适用，以及现有换手判定规则。不能用短窗口 Top-K 差异替代准入。

明确暂不做：采购 L2 来复现 OFI、引入 PyTorch、重写统一模拟器、把教程填零当数据质量修复、给 PSI 自动挂交易开关、增加正式身份/审批治理层、接券商真钱自动下单。

## 7. 证据与许可边界

1. 这是源码和文档调研。**本次未运行上游 unittest、未安装上游依赖、未构建站点、未下载市场行情、未复现真实策略收益，也未重跑本地回测或测试。**
2. 测试断言证明的是作者期望保护的行为；“本次阅读到测试”和“本次运行通过”严格分开。不存在本次新增收益、订单或净值改善的结论。
3. 未发现许可证文件且仓库元数据未识别许可证。本报告不据此作法律定性，但在明确复用授权前，不把上游代码复制进本项目；优先学习方法、自行编写最小反例。公开可读不自动构成复制和再分发授权已确认。
4. 没有修改 raw、策略门槛、运行配置、交易代码或 `auto_trade`；其他任务的未提交改动保留。GitHub 技能用于优先读取仓库元数据与固定源码，没有进行任何远端写入。
5. 本次交付为本文、旧报告的复核入口及 surveys 导航；旧报告中的历史核验记录继续保留其原日期语义。文档链接与格式检查只是交付校验，不是策略验证。

推荐阅读顺序：先旧报告 §1/§5.8 及本篇 §4.1，再按实际问题读 PIT、ML 时间边界，最后才考虑优化器。不要按课程目录重新建设本项目。
