# M3 G7E R2：Float64 NAV 投影闭包独立复验报告

日期：2026-08-10  
角色：未参与 G7E R1、R1 初验或 R2 实现的全新独立复验 Agent  
结论：**PASS；仅解锁主 Agent 最终验收。**

## 1. 范围、只读边界与结论

本轮完整阅读 `AGENTS.md`、G7E 任务书 §14、R1 独立初验、R2 返工交付、G7E production/unit/golden，
并核对 G7E 直接消费的 F0、G7B、G7C、F1、F2 邻接。生产代码、实现测试和任务书始终只读；本报告是
本轮唯一写入。

R1 阻断已按冻结合同闭合。`_formal_nav_row` 仍先在私有 Decimal 域严格验证四分量守恒；随后只投影
`cash`、`market_value`、`cash_receivable`、`stock_receivable_value` 四个 Float64 分量，并按权威
Schema 相同的左结合顺序生成输出 `equity`。`unit_nav`、`daily_return` 与下一 session 的
`previous_equity` 仍由原 Decimal `equity` 驱动，未被出口 Float64 反向修改。

本 PASS 不等于主验、G7F、完整 G7、M3 或 Linux/ext4 Gate PASS。

## 2. R1 阻断的独立对抗复现

### 2.1 未使用的 Decimal/Float64 组合

独立探针复用任务书 §13 允许的模块化 fixture，但没有复用实现测试的 `0.1 + 0.2` 数值。实际五日
ex-date 首次买入回放在第二个 session 产生：

```text
cash                     = Decimal("41104.74")
market_value             = Decimal("58800.0")
cash_receivable          = Decimal("0")
stock_receivable_value   = Decimal("0")
Decimal equity           = Decimal("99904.74")
float(Decimal equity)    = 99904.74
Float64 component sum    = 99904.73999999999
```

这证明四项经济分量在 Decimal 域严格闭合，而独立 `float(equity)` 与 Schema 顺序的 Float64 分量和不
bit-exact 相等。public 返回的 `equity` 精确取 `99904.73999999999`，因此七表通过未修改的权威 Schema，
没有以 epsilon、跳过校验或放宽 Schema 掩盖问题。

### 2.2 Decimal 经济没有被输出投影反向驱动

独立探针只读包裹 `_formal_nav_row` 并记录它在五个 session 收到的原始 Decimal 参数，再调用原实现：

- 每日均严格满足 `equity == cash + market_value + cash_receivable + stock_receivable_value`；
- 每日输出 `equity` 均精确等于四个已投影 Float64 分量按 Schema 顺序的左结合和；
- 每日 `unit_nav` 精确等于 `float(Decimal equity / Decimal initial_cash)`；
- 每日 `daily_return` 精确等于 `float(Decimal equity / Decimal previous_equity - 1)`；
- 第 2 至第 5 日传入的 `previous_equity` 均精确等于前一日原始 Decimal `equity`，而不是前一日输出
  Float64 `equity`。

首日独立核对为 Decimal `99929.64`、`unit_nav == 0.9992964`。因此 Float64 仅是七表的单向展示投影，
没有进入账户决策、收益链或后续 session 状态。

### 2.3 ex-date 首次买入无追溯享权

独立场景令事件证券在 record date 权重为零、ex-date 权重首次变为正值。public API 成功返回全部七表：

- ex-date 对事件证券恰有一笔 `BUY`；
- 对该事件没有 entitlement 行；
- 对该事件没有 `CAPTURE` posting；
- 七张表分别再次交由现有七个 Schema 显式验证，全部通过。

这同时关闭了 R1 的业务最小复现，不改变 record/ex 权益时序。

## 3. 其余合同映射与对抗结果

- **hostile Decimal context**：独立使用实现测试未覆盖的
  `prec=17 + ROUND_FLOOR` 与 `prec=79 + ROUND_CEILING`；两组均启用 `Inexact`、`Overflow` traps，
  并预置 `Rounded` flag。调用前后的 precision、rounding、traps、flags 完全相同。
- **fresh authority**：正向 fresh verifier 在账户创建前 exact once；独立 hostile verifier 的私密异常被稳定
  `M3_A_SHARE_SIMULATION_INVALID` 截断，`cause/context` 均为空；返回不同 scheduled frame 的 nonexact
  verifier 同样稳定拒绝。
- **row order**：把 fresh plan 的 scheduled targets 完整 reverse 后重新回放，七张表均与 baseline
  `.equals`；逻辑内容和确定排序不受输入行序影响。
- **独立 mark book / G7C**：golden 继续证明原股卖至零后，stock receivable 仍从 `3590.909...` 更新为
  `4000.0`，FULL_DAY list-date 结算为 500 股后可卖；CAPTURED 阶段不计 NAV，RECOGNIZED 后才计应收。
  本轮正式 G7C 邻接也通过，G7E 仍调用 actual public G7C。
- **gross/2 / F2**：golden 对第三日不对称买卖明确断言 `one_way_turnover == gross_turnover / 2`，且不等于
  `max(39950 + 19767, 42042) / pre_trade_equity`；本轮正式 F1/F2 邻接通过，G7E 没有复制撮合。
- **来源边界**：测试继续遵守任务书 §13；F0 fixture 只提供已经由 F0 套件负责的窄 test capability，G7E
  只 mock 自己实际 import 的 public plan verifier，actual G7C/F2 不被 mock。本轮没有把该模块化 fixture
  表述为完整 G1 来源证明。
- **范围核对**：`src/quant/domain/schemas.py` 在当前工作树状态中无 diff；R2 生产变化只落在 G7E NAV
  投影路径。F0/G7C/F1/F2 文件在共享工作树中已有各自里程碑的既存修改，本轮没有编辑、清理、暂存或提交
  它们，也没有改变相应 public 调用路径。

## 4. 双平台验证证据

### Windows Miniforge

- G7E unit + golden：`8 passed`，224.46 秒；
- F0/G7B/G7C/F1/F2 + development simulator 邻接七文件：`90 passed`，412.21 秒；
- 定向 Ruff：`All checks passed!`；
- mypy（`--no-incremental`）：`Success: no issues found in 1 source file`；
- cold import：成功导入 `simulate_formal_a_share_scenario`；
- 独立 R2 探针：`INDEPENDENT_R2_PASS`，fresh calls `1`、NAV records `5`、BUY rows `1`、Schema count `7`。

### WSL Miniforge base（`/mnt/f` / DrvFS）

- G7E unit + golden：`8 passed`，174.90 秒；
- 同一正式上游与 development 邻接七文件：`90 passed`，318.71 秒；
- 定向 Ruff：`All checks passed!`；
- mypy（独立 `/tmp` cache、`--no-incremental`）：`Success: no issues found in 1 source file`；
- cold import：成功导入 `simulate_formal_a_share_scenario`。

两平台 pytest 只有 Pandera deprecation warning 与因共享目录权限导致的 pytest cache warning，无测试失败。
WSL 路径位于 DrvFS，以上只算双平台兼容证据，不是 Linux/ext4 Gate。

### Diff 与内容锚点

- G7E 白名单 `git diff --check` 通过，仅有既存 LF/CRLF 提示；
- `a_share_simulator.py` SHA-256：
  `2E123BC293137B468307BD64BD8EDE2F4BBBCED0BA48B487596461F235605406`；
- unit SHA-256：
  `16DBB11E3B22B6FBF2F638D8F54E0F453F74F4DCCBD8D4EB4784FAAEB31A4D88`；
- golden SHA-256：
  `6D39287929C5619577DE70CD89C7C81736158CEE7941316DDE2A69FCF1F790CD`。

共享工作树仍含其他里程碑既有改动和未跟踪报告；本轮没有联网、读取真实数据/账户、生成正式
artifact/receipt、触发 StageRunner、交易副作用、`git add` 或 commit。

## 5. 独立复验结论

G7E R2 **独立复验 PASS**。R1 的 Float64 NAV 自拒绝已被最小闭合：账户经济与时序仍以 Decimal 为唯一
计算域，七表出口按既有 Schema 的 Float64 顺序自洽，ex-date 首次买入不追溯享权；fresh、行序、mark book、
gross/2、hostile context 和直接上游邻接均未发现新阻断。

下一步仅允许进入主 Agent 最终验收；在主验通过前不得标记 G7E PASS 或启动 G7F，且本报告不关闭 ext4、
完整 G7 或 M3 Gate。
