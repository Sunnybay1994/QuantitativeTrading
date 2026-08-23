# M3 G7E R1 正式 A 股单场景账户回放独立初验报告

日期：2026-08-10  
角色：未参与实现的全新独立初验 Agent  
结论：**FAIL；不得进入主 Agent 最终验收，必须返工后由新的独立上下文复验。**

## 1. 初验范围与边界

本轮完整阅读项目规则、G7E R1 任务书、实现交付报告、G7E production/unit/golden，以及 G7E 直接消费的
F0 market-facts capability、G7B fresh plan verifier、G7C entitlement transition、F1/F2 formal execution 与七表
Schema。生产代码、实现者测试和任务书保持只读；本报告是本轮唯一写入。

测试继续遵守任务书 §13 的模块化信任边界：G7E fixture 复用 F0 已签发的窄 test capability，并只 mock G7E
实际 import 的 public plan verifier；它不重新证明完整 G1 来源。实际 G7C/F2 未被 mock。F0 facts capability 只
签 canonical frames，因此本轮没有伪造反序 capability；行序对抗仅作用于 fresh scheduled targets。

## 2. 阻断问题

### [P1] 合法账户结果可能在 Float64 出口被自身 Schema 错误拒绝

**现象**

新增“record-date 空仓、ex-date 当日首次买入”合法场景后，public
`simulate_formal_a_share_scenario` 返回稳定的 `M3_A_SHARE_SIMULATION_INVALID`，无法返回七表。只读定位显示
实际账户回放已经完成，失败发生在最终 `AShareSimulationNavSchema.validate`。首日内部 Decimal 账为：

```text
cash = 60129.64
market_value = 39800.0
cash_receivable = 0
stock_receivable_value = 0
equity = 99929.64
```

Decimal 恒等式严格成立，但分别投影为 Float64 后，`float(equity)` 与四个 Float64 分量再次相加不保证 bit-exact
相等。当前具体值会触发 Schema 的 exact equality，因而一个合法普通数值组合被误判为账户无效。

**根因**

- `src/quant/backtest/a_share_simulator.py:1018-1043` 先在 Decimal 域正确校验恒等式，随后把 `cash`、
  `market_value`、两类 receivable 与 `equity` 分别独立转换为 float；
- `src/quant/domain/schemas.py:1250-1279` 又在 Float64 域要求 `equity == cash + market_value + ...` exact；
- 二进制浮点加法与各 Decimal 的独立舍入不具备该 exact 闭包。现有 unit 的 `pytest.approx` 复算和 golden
  数值恰好没有触发 Schema 失败，未覆盖此类合法组合。

**被破坏的规则/不变量**

- 任务书 §6：账户可行性、守恒和验收在 Decimal 域完成，Float64 只允许作为七表出口的单向投影；
- 任务书 §7：每个合法 formal replay 必须返回通过既有七表 Schema 的确定性普通内存表；
- record-date/ex-date 时间语义的合法变体不能因与业务无关的二进制表示误差而 fail closed。

**最小复现**

沿用现有 `_case` 的 exact F0 test capability、actual G7C/F2 与五个 session，只把 `600000.SH` 权重改为：

```text
record-date session: 0.0
ex-date session:     0.2
后续 session:        0.2
```

fresh plan verifier exact once 返回与 outer plan 完全相同的 plan。该证券在 ex-date 产生一笔 BUY；预期无
entitlement/posting（不追溯享权），实际在最终 NAV Schema 前被上述 Float64 exact balance 拒绝。独立探针退出码
1；public 失败消息保持脱敏。只读调用私有实现仅用于定位，Pandera failure case 明确给出上述首日值。

**必须新增的回归测试**

1. 将上述场景固化为 G7E formal unit/golden 回归；断言 ex-date BUY 存在，且对应事件无 entitlement/CAPTURE；
2. 断言 public API 成功返回七表，而不是只测试私有 `_formal_nav_row`；
3. 选取至少一个 Float64 独立投影不能 exact 闭合的现金/市值组合，证明输出仍满足最终权威 Schema；
4. 继续在 Decimal 域严格复算经济恒等式，禁止用 float epsilon 反向参与账户计算；
5. 修复不得修改现有 Schema SSOT，除非主 Agent 先重新冻结契约；不得靠删除 Schema validation、跳过七表验证
   或放宽 formal 错误处理通过。

**通过条件**

- 上述 public 反例在 Windows 与 WSL base 均返回七表；ex-date 买入不追溯享权；
- 七表通过现有 Schema，Decimal 账户恒等式仍严格成立，caller Decimal context 不变；
- 原 6 个 G7E tests、F0/G7B/G7C/F1/F2/development 邻接、Ruff、mypy、cold import 均通过；
- 返工交付后必须由未参与返工的全新独立上下文复验。

## 3. 其余合同映射结果

除上述阻断外，静态审查与已完成探针未发现第二个确定缺陷：

- fresh plan verifier 在账户/replay 创建前 exact once 调用；fresh/outer root、manifest、receipt、scheduled frame
  exact，运行只消费 fresh clone；stale/nonexact/hostile verifier 均 fail closed；
- facts 使用 exact runtime type，并先访问 `identity` 触发 capability 重验；API 无 caller F2/G7C transition、replay、
  open state 或裸 frame 入口；fake/development/subclass 由 exact type 边界在 property 访问前拒绝；
- 每日顺序为 rollover → actual G7C pre-open → settlement → 独立 mark/NAV → actual F2 → close mark/NAV →
  actual G7C record-close；record-date 当日买入的现有 golden 捕获 5000 股；CAPTURE posting 金额为 0，CAPTURED
  不进 NAV，cash/stock 分日 settle；
- 独立 mark book 不随 position 清零：golden 中原股卖到 0 后，RECOGNIZED stock receivable 仍估值 4000，随后
  FULL_DAY list-date 结算为 500 股 sellable 并卖出；普通 carry、factor mark、缺失/重复/非正事实由代码 fail closed；
- realized gross turnover 为所有 fill notional 绝对值之和除 pre-trade equity，one-way 固定 gross/2；现有 asymmetric
  golden 明确证明其不等于 max-side 口径；
- 无 open 的 nullable quantity、terminal pending exit、不强平、T+1、lot、最低佣金与 rejection notional 均由 actual
  F2 消费；G7E 未复制撮合；
- 合法 scheduled rows reverse 的七表逻辑内容和排序保持一致；报告未把该测试冒充 F0 capability canonical 来源证明；
- hostile verifier 的普通异常已验证稳定消息、无 cause/context；递归异常图从 wrapper 结构上同样被 `from None`
  截断，但本轮因确定阻断未再重复构造长 fixture 专测。

## 4. 独立对抗与验证证据

### Windows Miniforge

- G7E unit + golden：`6 passed`，约 239 秒；
- 独立 Decimal 对抗：precision `3/17/50/79`，`ROUND_CEILING/ROUND_FLOOR/ROUND_HALF_EVEN`，
  `Inexact/Overflow` traps 与预置 `Inexact` flag；四组七表均与 baseline exact `.equals`，调用前后 context/traps/flags
  完全相同；fresh verifier 共 5 次调用，每次 replay exact once；
- 独立 ex-date 无追溯反例：**FAIL**，public 稳定错误；定位为本报告 §2 的 Float64 NAV balance；
- Ruff：`All checks passed!`；
- mypy：`Success: no issues found in 1 source file`；
- cold import：`WINDOWS_COLD_IMPORT_PASS`。

### WSL Miniforge base（DrvFS）

- G7E + F0/G7B/G7C/F1/F2 + development 九文件合并组在 600 秒工具上限被终止，未获得 pytest 终态；随后
  单次进程检查确认无残留。该结果必须记为 **timeout/not verified**，不能引用实现者的 `94 passed` 代替独立证据，
  也未重复启动长测；
- Ruff：`All checks passed!`；
- mypy：`Success: no issues found in 1 source file`；
- 首次 cold import 命令因 PowerShell/WSL 嵌套引号失败；改用无嵌套 shell 的 direct argv 后成功输出
  `simulate_formal_a_share_scenario`；
- 路径位于 `/mnt/f`/DrvFS，以上即使绿色也只算兼容证据，不是 Linux/ext4 Gate。

### 范围与 diff

- `git diff --check` 对 G7E 白名单文件通过，仅有既存 LF/CRLF 提示；
- shared worktree 存在大量其他里程碑既有修改和未跟踪报告，本轮未修改、清理、暂存或提交它们；
- 未联网、未读取真实数据/账户、未生成正式 artifact/receipt、未触发 StageRunner 或任何交易副作用。

## 5. 初验结论

G7E R1 **独立初验 FAIL**。现有实现的核心 fresh、状态机、mark book 与 Decimal 隔离设计总体符合冻结合同，
但七表出口存在可由合法权重路径触发的稳定自拒绝，违反“合法 formal replay 必须返回通过 Schema 的七表”这一
关键不变量。必须先按 §2 返工并新增 public 回归测试，再交由新的独立上下文复验；当前不得进入主验，不解锁
G7F，也不代表 G7、M3 或 Linux/ext4 Gate 通过。
