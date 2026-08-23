# 投研文档索引

本目录保存研究方法、假设卡、实际运行结论、否证记录和冻结的后续观察合同。

- 当前 M2 owner、执行顺序、TARGET R11 HOLD 与证据状态以
  [M2 策略与因子库并行建设路线图](roadmaps/M2_策略与因子库并行建设路线图.md) 为唯一执行 SSOT；
  项目级里程碑仍以根目录 `项目实施路线图.md` 为准；
- 单次投研 Agent 任务书和验收记录放在 [`agent/`](agent/)；
- 不可覆盖的机器可重放结果放在 `artifacts/research/runs/<run_id>/`；
- 本目录只概述研究结论并链接机器产物，不复制完整输出，也不在此维护实时进程状态。

> **TARGET R11 证据 HOLD（2026-08-16）**
>
> 13 个受影响 immutable run 的字节与原状态保持不变，`REJECTED` 不升级；四个历史
> `RESEARCH_ONLY` 经济腿当前为 HOLD。受影响 run 的 targets、NAV、组合收益、换手和 0.5x/1x/2x
> 成本字段不得作为当前通过、forward、S2/admission 或 PAPER 证据。完整 run 清单和处置边界见
> [M2 执行路线图](roadmaps/M2_策略与因子库并行建设路线图.md)。

> **`M2-EVAL-STOP-001`（2026-08-16）**
>
> R11 只关闭 Top-K 替补；shared outcome cohort、漂移后换手、对称 redundancy coverage、same-bytes
> config/cost identity、分组单调否证与 PIT version/comp-type 链仍未闭合。首个 PIT 与任何 corrective replay
> 均暂停；历史 IC/group/direction/fold 与经济字段不得作为 promotion 证据。完整合同只见上述 M2 执行路线图。

## 方法论与行业调研

- [量化机构投研与实盘基础设施调研](量化机构投研与实盘基础设施调研.md)
- [量化拥挤时代的因子发现与策略生存方法论](量化拥挤时代的因子发现与策略生存方法论.md)

## 外部参考资料

- [`quant_factor_research_v2`](references/quant_factor_research_v2/README.md)：用户提供的因子研究参考资料包。
  它是知识输入，不是项目 SSOT、已验证研究结论或准入证据；实际采用的公式、方向、数据和门禁仍须独立预注册与验证。

## 经典日频因子总览

- [经典日频因子第一轮研究结果](M2_经典日频因子第一轮研究结果.md)
- [经典日线因子阶段总结与下一分支](M2_经典日线因子阶段总结与下一分支.md)

## 第二批与第三批价量机制

- [第二批价量机制假设卡](M2_经典因子第二批价量机制假设卡.md)
- [第二批价量机制研究结果](M2_经典因子第二批价量机制研究结果.md)
- [第三批正交日线机制假设卡](M2_经典因子第三批正交日线机制假设卡.md)
- [第三批正交日线机制研究结果](M2_经典因子第三批正交日线机制研究结果.md)

## 因子组合、市场风险与前向观察

- [三因子组合假设卡](M2_经典因子三因子组合假设卡.md)
- [三因子组合第二轮研究结果](M2_经典三因子组合第二轮研究结果.md)
- [510300 市场风险覆盖假设卡](M2_经典因子510300市场风险覆盖假设卡.md)
- [510300 市场风险覆盖第三轮研究结果](M2_经典因子510300市场风险覆盖第三轮研究结果.md)
- [510300 候选前向观察合同](M2_经典因子510300候选前向观察合同.md)

## 轻量模型研究

- [五因子 LightGBM 假设卡](M2_经典因子五因子LightGBM假设卡.md)
- [五因子 LightGBM 研究结果](M2_经典因子五因子LightGBM研究结果.md)

## 基本面与 PIT 因子

- [`daily_basic` 价值代理因子假设卡](M2_daily_basic价值代理因子假设卡.md)
- [`daily_basic` 价值代理因子研究结果](M2_daily_basic价值代理因子研究结果.md)
- [PIT 财务质量因子首批假设卡](M2_PIT财务质量因子首批假设卡.md)

## 流动性与交易活动因子

- [Amihud 非流动性因子假设卡](M2_Amihud非流动性因子假设卡.md)
- [Amihud 非流动性因子研究结果](M2_Amihud非流动性因子研究结果.md)
- [自由流通换手因子假设卡](M2_自由流通换手因子假设卡.md)
- [自由流通换手因子研究结果](M2_自由流通换手因子研究结果.md)

两项真实不可变运行均已完成；三个候选因子全部 `REJECTED`，未生成 `PAPER_CANDIDATE`，也未启动 PAPER。

## Benchmark 条件市场风险因子

- [510300 下行 Beta 因子假设卡](M2_510300下行Beta因子假设卡.md)
- [510300 下行 Beta 因子研究结果](M2_510300下行Beta因子研究结果.md)

真实不可变运行结论为 `REJECTED`：coverage、调仓日对账和冗余门禁通过，但 RankIC、跨 fold 方向稳定性和
2 倍成本后收益不足。预注册方向是防御型低 beta/BAB 风格的 `-1`，并不冒充经典 downside-risk positive
premium；没有生成 `PAPER_CANDIDATE`，也没有启动 PAPER。

## Alpha158 第四批残差、时点与量能

- [第四批残差、时点与量能假设卡](M2_经典因子第四批残差时点量能假设卡.md)
- [第四批残差、时点与量能研究结果](M2_经典因子第四批残差时点量能研究结果.md)

真实不可变运行结论为三个因子全部 `REJECTED`。coverage 和预注册调仓日对账全部通过，但 `IMXD20` 触发
严格冗余线且成本后为负，`RESI20` 的 RankIC 和成本证据不足，`VSUMD20` 的方向、RankIC、折数和成本证据
不足。没有生成 `PAPER_CANDIDATE`，也没有启动 PAPER。

## MAX 彩票偏好因子

- [MAX 彩票偏好因子假设卡](M2_MAX彩票偏好因子假设卡.md)
- [MAX 彩票偏好因子研究结果](M2_MAX彩票偏好因子研究结果.md)

本轮 trial budget 固定为 1，研究过去 20 个严格连续 session 的最大单日复权收盘收益，并将经济方向预注册
为低 MAX 优先的 `-1`。它不是 Qlib Alpha158 的 `Max(high,20)/close`。原始 run 的历史状态仍为
`RESEARCH_ONLY`，但其目标、组合与成本证据因 TARGET R11 进入 HOLD；规模/换手控制的不可变状态仍为
`REJECTED`，其历史 2x 成本腿也不得继续作为有效经济证伪。forward、统一回放和人工 admission 仍暂停。

### MAX 规模与换手二阶段控制

- [MAX 规模与换手二阶段控制假设卡](M2_MAX规模换手二阶段控制假设卡.md)
- [MAX 规模与换手二阶段控制研究结果](M2_MAX规模换手二阶段控制研究结果.md)

该确认性控制沿用同一 canonical MAX 假设，以同日总市值和自由流通换手率的横截面 average-rank OLS 残差
检验增量；不是新候选。数值闭包、`-1` 固定方向、coverage、预注册调仓日和成本门禁均已在真实运行前冻结。
唯一真实 run 的 RankIC、方向、coverage、调仓日与 OLS 数值闭包均通过；历史产物记录的 2 倍成本后三折
链式收益为 `-5.0079%`。TARGET R11 表明该成本腿不能继续作为有效经济证伪；run 的 `REJECTED` 状态仍保持
不可晋级，原始 run 的历史 `RESEARCH_ONLY` 标签也保持不可变，二者均不得进入 S2、`PAPER_CANDIDATE` 或 PAPER。
