# 裁定

带日期的口径与架构决定。改门槛必须先在这里追加一行，再重算。

| 日期 | 裁定 |
|---|---|
| 2026-09-08 | 取消多 Agent 治理；单一 Agent；默认授权跑 Python/数据/Tushare/DeepSeek（月≤$30）。 |
| 2026-09-10 | 禁止单因子微假设流；因子一律进库走电池。 |
| 2026-09-12 | 策略按持股期报告；股票基准必须是收益指数；空仓压力窗口标不适用。 |
| 2026-09-13 | 实验结果不手写成文档。换手=年单边成交/日均净值，报中位数；6–8× 且 2× 超额≥5pp 视为通过。Q10 按此进模拟盘第二账户。 |
| 2026-09-14 | 持续挖掘替代夜间调度；NightlyResearch 停用。 |
| 2026-09-15 | 全量重构：死代码进 `legacy/`；统一 `python -m quant`；新增 `core`/`llm`/`notify`/`intel`；GPU 为配置项默认 CPU；交易网关仅 `ManualGateway`。不改回测器与 m3 合约，不迁 artifacts。 |
| 2026-10-13 | [优化工作清单_20261009](优化工作清单_20261009.md) 四周任务与 §3 总验收闭合：`quant status` 字段齐、注册表监控列、`q10_plus_admitted_v1=PAPER_CANDIDATE`、LLM 月花费>$2 可对账、全量 `pytest` 6999 passed / 107 skipped。不改 §1.2；真钱下单仍须用户确认。 |
| 2026-10-14 | `ts_corr` 对近 ±1（1e-3）与近 0 做 ULP 吸附；`ts_argmax/min` 先 `round_sig_figs(10)`；GP 上下文对齐阈值 1e-9→1e-6。不改准入门槛与因子定义语义。 |
| 2026-10-14 | 分钟/BaoStock 调度在挖掘/GP 持有冻结 bar 时 `deferred`；过期冻结由 `invalidate_stale_gp_context` 归档后重钉。formal CLI 每轮清空 reparse 祖先缓存；可选 `QUANT_FORMAL_CLI_RESOLVE_DETAIL=1` 输出路径细节。 |
| 2026-10-15 | g8c formal resolve 观测用模块 shim 替代 `sys.setprofile`（后者在 Windows 上使嵌套 verify 病态变慢）。契约与门槛不变；复验 11 passed / 1 skipped。 |

来历：`docs/archive/` 与 `docs/research/experiments_2026-09/`。当前任务见根目录 `项目实施路线图.md`。
