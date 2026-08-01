# M2 U1：统一股票 / ETF 日频事件模拟器主 Agent 最终验收报告

日期：2026-07-31（Asia/Shanghai）

结论：**已合流 main 并完成双平台复验，关闭 M2 统一回测器工程项。**

分支：`codex/m2-unified`

2026-08-02 合流证据：main 由 `6b64973` fast-forward 至 `e487581`；合流后 Windows Miniforge 与 WSL
Miniforge `base` 分别重跑同一组 `118 passed`，Ruff 与 5 个生产源码 mypy 均通过。WSL 工作区位于
DrvFS，该结果证明 Linux 解释器兼容性，不宣称 ext4 平台 Gate。

## 1. 交付内容

- 新增以权威交易日历驱动的股票 / ETF 共用日频账户循环；
- 显式处理停牌无 bar 持仓估值、涨跌停、股票 T+1、整手、先卖后买、现金约束和稳定 rejection；
- 证券上市/退市生命周期、Instrument policy、market state、bar 和多市场 calendar 缺失均 fail closed；
- 新增 position / rejection Schema，输出稳定排序并验证账户守恒；
- ETF 与股票费用选择显式分离，支持 0.5× / 1× / 2× 独立压力重放；法定印花税和过户费不随执行摩擦倍数缩放；
- 旧 `simulate_etf_targets` 签名和经济结果保持；S0/S1 JSON 固定 POSIX 相对配置路径和 UTF-8/LF，消除
  Windows/WSL 仅因路径分隔符或换行造成的 hash 漂移。

## 2. 对抗审计返工

内部只读审计对原提交 `88b739e` 发现两个 P1 和一个 P2；主 Agent 逐项复现后返工：

### P1-1：缺失 calendar 行被误当成休市

- 现象：另一市场贡献 global session 时，缺 calendar 行的持仓静默 carry mark；
- 根因：实现只保存 open pairs，丢失“closed”与“missing”的区别；
- 应遵循规则：每个 active market 对每个推进日期必须有显式 calendar 行；
- 最小复现：SH/SZ 初始持仓，calendar 只有 SH 当日行；
- 新增测试：`test_missing_calendar_row_for_active_market_fails_closed`；
- 通过条件：写入任何 session evidence 前返回 `BACKTEST_CALENDAR_COVERAGE_MISSING`。

### P1-2：新目标停牌证券没有 carried mark

- 现象：过去有合法 bar、当前无仓位的新目标证券在停牌日返回 `BACKTEST_INITIAL_MARK_MISSING`；
- 根因：上一合法 mark 只存于已有 `_Position`，没有从过去 bar 取最近 close；
- 应遵循规则：显式停牌是可证明的交易阻断，应写 rejection 并继续；
- 最小复现：d1 close=9.5，d2 首次 BUY target 且 `suspended=True`、无 bar；
- 新增测试：`test_suspended_new_target_uses_prior_close_for_rejection`；
- 通过条件：现金不变、零成交、BUY/`SUSPENDED`，reference price 与 mark 均为 9.5。

### P2-1：T+1 evidence 等待所属市场再次开市

- 现象：d2 SH closed、SZ open 时，SH 未交收数量没有在第二个 global session 转 settled；
- 根因：交收条件错误绑定 `open_markets & seen_markets`；
- 应遵循规则：冻结合同中的“第二个模拟 session”是合并后的 global session；
- 最小复现：d1 两市场开市且两只股票 unsettled=100，d2 仅 SZ 开市；
- 新增测试：`test_all_positions_settle_on_second_global_session`；
- 通过条件：d2 两只证券 settled 均为 100；ETF evidence 同步推进但不参与卖出限制。

## 3. 双平台验证

Windows 原生 Miniforge：

- 冻结定向 pytest：`118 passed`；
- Ruff：通过；
- 5 个生产源码 mypy：通过。

WSL Miniforge `base`：

- 同组定向 pytest：`118 passed`；
- Ruff：通过；
- 同 5 个生产源码 mypy：通过。

Pandera/Polars deprecation warnings 为既有依赖提示，不影响本轮结论。

## 4. S0/S1 真实兼容回归

读取主工作区既有 clean M2 数据，只向隔离 worktree 的
`artifacts/m2-u1-compat-20260731/` 写入一次 S0 与 S1 walk-forward。与既有 M2 基线逐字节比较：

| 产物 | SHA-256 | 结果 |
|---|---|---|
| `s0/report.json` | `e7c3d09ba97abedabf4dd209ac4335dc6c3caf799fdc774f13bf4bc25390f883` | 相同 |
| `s0/nav.parquet` | `1efdc6b3a2936f8755303ea49c5a50e35b73534c8beebec1868117f038696553` | 相同 |
| `s0/trades.parquet` | `9bb0b218e2c4b62b41318d3ffd4892f5981538f49fb43323358bbee1cbffad31` | 相同 |
| `s1_walk_forward/report.json` | `cb1118e22bd230f6762c8763e8ede16fb500da6d0ac1cee3e69ed0705156038f` | 相同 |
| `s1_walk_forward/test_nav.parquet` | `6638b1351d067f2a50bed1259ba01f094118e861f529b720e493e527adc695e6` | 相同 |
| `s1_walk_forward/test_trades.parquet` | `98d8b0fa808e836c9bd581f3fbb5dca1eb0f70987dffa941518a89161e57fde5` | 相同 |

S0/S1 的收益、费用、交易数与 walk-forward 选择结果均无漂移。

## 5. 通过边界

本结论关闭 M2 的统一股票/ETF 日频模拟器工程项，不证明策略未来有效。以下限制继续披露：

- `ETF_POOL_M2_V1` 的历史回看存在候选池后见偏差；
- 成本参数仍是版本化研究假设，尚未用真实券商账单校准；
- 分钟撮合、部分成交、冲击成本和 M3 G7 公司行动 entitlement 属后续里程碑；
- M4 统一准入、Paper/Shadow 与四周稳定性 Gate 未据此关闭。
