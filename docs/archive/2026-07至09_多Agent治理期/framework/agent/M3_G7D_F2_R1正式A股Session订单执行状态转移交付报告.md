# M3 G7D-F2 R1：正式 A 股 Session 订单执行状态转移交付报告

日期：2026-08-09  
角色：实现 Agent  
结论：**R1 实现与自测完成，等待全新独立初验；本报告不宣布主验或 Gate PASS。**

## 1. 实现范围

严格在任务白名单内完成：

- `src/quant/backtest/a_share_execution.py`
  - 新增 `AShareSessionExecutionTransition` 与 keyword-only
    `execute_formal_a_share_session`；
  - formal 入口先做 exact 浅类型检查，再读取 facts identity；
  - 每次调用 exact 一次 public F1 builder，证券域为 target 与正持仓并集；
  - 每个 symbol 通过 formal rule resolver 取得数量规则；
  - 实现完整目标差量、先卖后买、T+1、板块 lot、现金离散分配、费用、滑点和 post book；
  - 使用固定私有 Decimal context 与有界内存 Fraction breakpoint 搜索；
  - 返回前校验成本、排序、fill/rejection、现金和持仓局部守恒；
  - formal 失败统一翻译为无 cause/context 的 `M3_A_SHARE_EXECUTION_INVALID`。
- `src/quant/backtest/__init__.py`
  - 仅安全导出新增 transition 与 formal session 入口。
- `tests/unit/test_m3_formal_a_share_session_execution.py`
  - 新增 20 项 formal 合同与反例测试。
- 本任务单
  - 状态更新为实现与自测完成、待独立初验和主验。

未修改 G7C、F0/F1 API、development public primitives、simulator、costs、Schema、enum、config、正式
artifact/journal；未联网、add 或 commit。

## 2. 关键设计与返工闭环

### 2.1 §14 极小正目标交叉语义

实现前发现“同 symbol 一条 intent、极小正目标必须 BUY、已有持仓又必须 SELL”不能同时表达，按停止条件回报
主 Agent。任务单新增 §14 后实现唯一语义：

- current=0：唯一 BUY intent，加 target-notional `LOT_CONSTRAINT`；raw=0 也保留诊断；
- current>0：唯一 SELL intent；另有唯一允许的无 BUY intent target-attainability BUY LOT 诊断；
- SELL execution shares 与 theoretical raw target shares 分开校验，不相加冒充同一守恒域；
- SELL 全成、跌停阻断或 T+1 部分残差均保留 target-attainability 诊断。

主板与科创板均覆盖 raw=0 和正但低于 minimum；已有持仓覆盖全成、对应方向 limit 阻断和 T+1。

### 2.2 development 兼容与 formal 私有核心

现有 development primitives 会排序 target、只遍历 target symbol、允许 caller 裸 open-state，并在线性 tuple 中
物化 STAR 合法数量。为保持其 public 行为和现有测试，未破坏性收紧这些入口；formal wrapper 使用同文件私有
核心复用既有值对象、规则和 F1 public API。

### 2.3 exact 现金分配与 Decimal

- formal 成本只缩放 commission rate/min 与 slippage；stamp/transfer 原值保持；
- tick/cent rounding 明确，slippage 只通过 execution notional 进入 cash；
- 私有 Decimal context 固定 precision、rounding、Emax/Emin、traps 和 flags，不修改 ambient context；
- 首轮 hostile context 暴露 buy allocation 的 `cash - spent` 仍使用 ambient context，已把剩余加减乘路径统一
  收入私有 context，并新增回归；
- buy breakpoint 不调用 development `_valid_buy_quantities`，使用 exact Fraction 二分边界和下一合法量函数，
  避免与 STAR desired 线性增长的 tuple；首个不可付 breakpoint 可立即停止。

## 3. 验证证据

所有命令均在 `artifacts/dev_worktrees/m3-g4-formal` 使用工作树自身 `src`。

### 3.1 最终 revision 的 Windows 证据

- F2 formal：**20 passed**；
- Ruff：**PASS**；
- mypy：**PASS**；
- cold import/public signature：**PASS**；public signature 无 `open_states`，未加载 qlib/lightgbm/mlflow；
- 白名单 `git diff --check`：**PASS**；仅有既有 LF/CRLF 提示，无 whitespace error。

### 3.2 邻接回归

在最终局部完整性收紧前的同一 R1 实现上运行；之后的改动只增加 formal transition 校验、固定 Decimal
Emax/Emin、极小目标 rejection 优先级和对应测试，未修改 development/F0/F1/G7C 路径：

- Windows F2+F1+development execution/allocation：**110 passed**；
- Windows F0+G7C+development simulator：**37 passed**；
- WSL base F2+F1+development execution/allocation：**110 passed**；
- WSL base F0+G7C+development simulator：**37 passed**。

### 3.3 最终 revision 的 WSL 静态与 cold evidence

- Ruff：**PASS**；
- mypy：**PASS**；
- cold import/public signature：**PASS**。

WSL 输出确认工作树实际位于 `/mnt/f`/DrvFS；只计双平台兼容证据，不声称 Linux/ext4 Gate。最初一次 WSL
命令因 PowerShell 展开 `$PWD` 仅返回空输出，未计入证据；确认该调用已经退出后改用绝对 WSL
`PYTHONPATH`，取得上述可计终态。

## 4. 已知边界与待验事项

- F2 接受 caller 显式 `AShareCostPeriod`，只证明成本数学；cost provenance 仍由后续 G7E fresh plan 验证。
- transition 是普通不可变审计值，不是上游 capability 或密码学 authority；后续 G7E 必须内部调用 F2，不能接受
  caller transition 旁路。
- 本轮未运行最终 revision 的第二次全邻接测试；最终 formal 20 项、双平台静态/cold 已通过，独立初验和主验
  应按任务书重新运行所需命令并增加未公开反例。
- 未验证 Linux/ext4、真实 plan cost provenance、完整 G7E、artifact 发布或 M3 Gate。

## 5. 交付结论

R1 已达到进入全新独立初验的条件。实现者自测不能代替独立初验或主 Agent 最终验收；任务状态保持待验。
