# 架构

个人 A 股/ETF 量化投研系统。投研是主干，交易只预留人工通道。研究与交易解耦，共享 `target_weight`。

## 包结构

```
src/quant/
  core/        运行时设置、路径、GPU 探测
  data/        连接器、raw/clean、PIT、刷新     ← 唯一允许打开 data/ 的包
  factors/     DSL、因子库、计算、评估电池
  research/    GP/队列/研究循环/日更/夜间/持续挖掘
  research/m3/ FROZEN：回测器依赖的合约/发布/状态，只修不扩
  backtest/    统一 T+1/整手/费用模拟器
  portfolio/   组合约束与换手预算
  risk/        轻量风险模型
  execution/   模拟账本、人工订单单、gateways
  llm/         DeepSeek 唯一入口与月度预算
  notify/      邮件 / 企微 / 飞书 / wxauto
  intel/       arXiv / GitHub / RSS → 因子队列
  reporting/   排行榜、仪表盘、digest
  cli.py       python -m quant <组> <命令>
legacy/        运行时无引用的旧模块，PYTHONPATH=legacy;src 可复现
```

依赖方向：`core` ← 业务包；`llm`/`notify`/`intel` 只被入口和调度使用，不被 data/backtest 依赖。

## 运行时数据流

数据刷新 → 因子计算 → 评估电池 → 准入入库 → 年度模型 walk-forward → 模拟账户日更 → 人工订单单（notify）→ 用户下单。

后台两条计划任务：

| 任务 | 时间 | 命令 |
|---|---|---|
| DailyObservation | 工作日 17:30 / 21:30 | `python -m quant research daily` |
| ContinuousMining | 登录后每 10 分钟尝试接续，2 小时片 | `python -m quant research mining` |

NightlyResearch 默认停用；持续挖掘已覆盖其 N1–N5。情报扫描：`python -m quant intel scan`。

## GPU

`QUANT_DEVICE=cpu|gpu|auto`（默认 cpu）。本机 GTX 1070 走 LightGBM OpenCL，失败回退 CPU。配置冻结里写了 `device_type` 的不被覆盖。不引入 torch。

## 不在当前运行路径里的东西

- `execution/paper_formal_*` 与 OMS 状态机：历史正式身份体系，模拟盘不用。
- `legacy/`：审计脚本、港股分钟探针、P7 文本批次、GUI。
- 实盘券商 API：未接。`ManualGateway` 只发消息。
