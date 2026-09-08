# M3 G7D-F2 R1：正式 A 股 Session 订单执行状态转移独立初验报告

日期：2026-08-09  
角色：未参与实现的全新独立初验 Agent  
结论：**FAIL；不得进入主验 PASS，不得解锁 formal G7E。**

## 1. 初验范围与边界

本轮完整读取并核对：

- 根目录 `AGENTS.md` 及其引用的 `.ai/README.md`、`philosophy.md`、`coding_rules.md`、
  `review_checklist.md`、多 Agent 与高风险工作流；
- F2 R1 任务单（含 §14 重冻）与实现交付报告；
- `src/quant/backtest/a_share_execution.py` 中 F0 verified facts、F1 public open-state/rule API、F2
  production 与 transition validator；
- `src/quant/backtest/corporate_actions.py` 中 G7C replay/transition public API 与来源闭包；
- `src/quant/backtest/__init__.py` 导出及新增 F2 测试；
- F2/F1/development execution/allocation 与 F0/G7C/simulator 邻接测试。

生产代码与实现者测试全程只读；未联网、未 add、未 commit，未修改其他文档。本报告是本轮唯一新增文件。

## 2. 阻塞问题：普通非空 rejection 的名义金额可被伪造

### 2.1 现象

从当前最终 production 生成合法 `AShareSessionExecutionTransition` 后，仅把一条普通非空
`ExecutionRejection.rejected_notional` 增加 `Decimal("0.01")`，再通过 `dataclasses.replace` 重构 transition，
`__post_init__` 对下列全部情况均错误接受：

| rejection reason | 合法值 | 漂移值 | 重构结果 |
|---|---:|---:|---|
| `T_PLUS_ONE` | `370.0` | `370.01` | ACCEPTED |
| SELL `LOT_CONSTRAINT` | `200.0` | `200.01` | ACCEPTED |
| 普通 BUY `LOT_CONSTRAINT` | `200.0` | `200.01` | ACCEPTED |
| BUY `CASH_CONSTRAINT` | `4800.0` | `4800.01` | ACCEPTED |
| `SELL_AT_LOWER_LIMIT` | `1000.0` | `1000.01` | ACCEPTED |

这不是构造器单项字段合法性问题：漂移后的金额仍为 finite/non-negative Decimal，但不再等于相应 open 与拒绝
数量的唯一乘积，违反 F2 transition 局部完整性。

### 2.2 根因

`_validate_formal_session_transition` 在 `a_share_execution.py:3721-3774` 遍历 rejection 时：

- 会重算 null-quantity rejection 的 mark gap；
- 会 exact 校验 §14 target-attainability BUY LOT 特例的 `target_notional`；
- 对其余有数量 rejection 只检查 intent 归属、非空数量并把 `rejected_quantity` 累计进 residual；
- **没有按 reason/side/open/quantity 重算 `rejected_notional`。**

因此数量守恒可以成立，但名义金额审计字段已失真。现有测试只漂移 post cash 或删除整组 rejection，没有覆盖
“数量不变、仅普通 rejection notional 漂移”。

### 2.3 应遵循规则

- F2 任务单 §9：intents/fills/rejections 的 open、notional、fee、slippage 与 reason 必须可由本次输入唯一复算，
  伪造局部不守恒值对象不得通过 `__post_init__`。
- F2 任务单 §14：无对应 BUY intent 的目标可达性 LOT 是唯一孤儿例外；该例外不能放宽普通 rejection 的字段完整性。
- `AGENTS.md` §5、§7、§11：交易金额语义须精确，独立初验发现问题必须回到“实现 → 独立复验”闭环。

### 2.4 最小复现

1. 调用 public F2 取得含任一上述普通 rejection 的合法 transition；
2. `bad_rejection = replace(rejection, rejected_notional=rejection.rejected_notional + Decimal("0.01"))`；
3. `replace(transition, rejections=(..., bad_rejection, ...))`；
4. 当前代码返回新 transition，而不是抛出 `ValueError`。

本轮对五类 reason 的实际输出见 §2.1；它们由当前最终代码即时生成，不复用交付报告旧计数。

### 2.5 必须新增的测试

至少新增参数化 transition anti-forgery 回归，覆盖：

1. `T_PLUS_ONE`；
2. SELL `LOT_CONSTRAINT`；
3. 普通 BUY `LOT_CONSTRAINT`（明确不是 §14 special）；
4. BUY `CASH_CONSTRAINT`；
5. 至少一个 market-block reason（本轮复现为 `SELL_AT_LOWER_LIMIT`）。

每例从 public F2 的合法 transition 出发，只漂移 `rejected_notional`，必须在 transition 构造时失败；同时保留
null gap 与 §14 target-attainability 的合法正例，防止错误地把两个守恒域混算。

### 2.6 通过条件

1. production 按冻结语义重算所有普通 rejection notional；不能只检查 Decimal 类型或非负；
2. 上述五类漂移全部稳定失败，合法 null gap 与 §14 special 仍通过；
3. 实现 Agent 提交返工报告；
4. 由未参与返工的另一全新独立初验 Agent 重新运行反例和双平台聚焦/邻接验证并明确 PASS；
5. 之后才可进入主 Agent 最终验收。

## 3. 独立新增反例

### 3.1 blocked SELL + 最低佣金现金 + §14 target-attainability LOT

构造同一 session：

- `000001.SZ` 持仓 100、极小正 target raw=79/target position=0，卖出在 lower limit 被阻断；
- `600000.SH` BUY desired=200；现金仅 `1005`；成本为 100 股名义 `1000` 加最低佣金 `5.00`；
- blocked SELL 的预期卖款不得进入 BUY 现金。

实际结果：

- fills：仅 `600000.SH BUY 100`，notional `1000.0`、commission `5.00`；
- rejections canonical：
  1. `000001.SZ SELL SELL_AT_LOWER_LIMIT 100 / 1000.0`；
  2. `000001.SZ BUY LOT_CONSTRAINT 79 / 790.000`（§14 target-attainability）；
  3. `600000.SH BUY CASH_CONSTRAINT 100 / 1000.0`；
- post cash exact `0.00`；blocked position 原样保留，新买 100 全部 unsettled。

结论：**PASS**。SELL 执行域与 BUY 目标可达性域未混算，blocked sell 未虚增可用现金，最低佣金进入离散现金约束。

### 3.2 现金受限大科创板 desired 的 exact oracle 与有界路径

构造 `688001.SH` desired=50,000、open=10、cash=123,455、最低佣金=5，其余费用/滑点为 0；将 development
`_valid_buy_quantities` 替换为一旦调用即失败的 sentinel。独立 oracle 穷举合法集合 `{0} ∪ [200, 50000]`，得到
最大可付数量 12,345。

实际 F2：fill=12,345、`buy_allocation_lambda=2469/10000`、cash residual=37,655、post cash=`0.00`，且未调用
development 线性物化器。结论：**PASS**，与 exact oracle 一致。

## 4. 其他合同核对

- F1 public builder：实现路径在每次 F2 public 调用中只有一次显式调用；spy 测试纳入本轮 111 项并通过。
- no-open gap：null quantity rejection 按 `abs(target_notional-current_mark_value)` 重算；既有 full-day/缺 target
  反例通过，删除 rejection 会被 transition 拒绝。
- ambient Decimal：hostile precision/rounding/Emax/Emin/trap 测试通过，调用前后 ambient context 相同。
- target 物理顺序：逆序 canonical target 在计算前失败，未用 `.sort()` 修复 caller 输入；对应测试通过。
- §14 孤儿例外：validator 只在 BUY + LOT、正 target、target position=0、raw/requested/notional exact 匹配时放行；
  其余 rejection 无同 symbol/side intent 时进入 `intent is None` 失败路径。该静态边界正确，但普通 rejection 的
  notional 漏检仍破坏 transition 防伪。
- 异常脱敏：public F2 在 active except 外统一抛 `M3_A_SHARE_EXECUTION_INVALID from None`；fake facts/F1/Schema
  邻接测试通过，未观察到 cause/context 或敏感输入泄漏。
- G7C/F0/F1 API 与职责未被 F2 反向修改；F2 不消费 entitlement transition、不接受 caller open-state、无 G7E
  caller-transition 入口。

## 5. 当前最终代码的验证终态

所有命令均在 `artifacts/dev_worktrees/m3-g4-formal` 使用该工作树自身 `src`。

### 5.1 Windows 原生 Miniforge

- F2 + F1 + development execution/allocation：**111 passed**；
- F0 + G7C + development simulator：**37 passed**；
- Ruff（production/export/new test）：**PASS**；
- mypy `src/quant/backtest/a_share_execution.py`：**PASS**；
- cold import/public signature：**PASS**，无 `open_states`，未加载 qlib/lightgbm/mlflow。

### 5.2 WSL Miniforge base

- F2 + F1 + development execution/allocation：**111 passed**；
- F0 + G7C + development simulator：**37 passed**；
- Ruff：**PASS**；
- mypy：**PASS**；
- cold import/public signature：**PASS**。

WSL 工作树实际落在 `/mnt/f`/DrvFS；以上只计双平台兼容证据，不声称 Linux/ext4 Gate。

### 5.3 diff 与不可计尝试

- 指定白名单 `git diff --check`：**PASS**，只有既有 LF/CRLF 提示，无 whitespace error；
- Windows 首次 1 秒承载层超时后确认无残留 pytest，再执行的 111 passed 才计终态；
- 一次 WSL `$PWD` 被 PowerShell 提前展开而无输出、一次 cold 命令引号导致 PowerShell ParserError，均不计证据；
  之后均以绝对 WSL worktree 路径/修正引号取得上述可计终态。

## 6. 最终结论

尽管当前最终 revision 的双平台聚焦、邻接、静态和 cold checks 全绿，transition validator 可接受普通 rejection
的伪造名义金额，直接违反任务单 §9 的局部完整性与审计合同。因此本轮独立初验结论为 **FAIL**。

必须按 §2.5–§2.6 返回外部实现 Agent 返工，并由未参与返工的全新独立初验 Agent 复验；在该闭环明确 PASS 前，
不得将 F2 标记主验通过，也不得解锁 formal G7E。
