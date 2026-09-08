# M3 G7D-F2 R2：referenceOpen 与 RejectionNotional 闭包独立复验报告

日期：2026-08-09  
角色：未参与 R2 实现的全新独立初验 Agent  
结论：**PASS；R2 达到进入主 Agent 最终验收的前置条件，但本报告不宣布主验、G7E、Linux/ext4 或 M3 Gate PASS。**

## 1. 审查边界与输入

本轮完整核对：

- `M3_G7D_F2_R1正式A股Session订单执行状态转移任务单.md` §15-§16；
- R1 独立初验 FAIL 报告；
- R2 实现交付报告；
- 当前最终 revision 的 production、public export 与 formal F2 测试。

生产代码和实现者测试全程只读。本 Agent 唯一写入本独立复验报告；未联网、未 add、未 commit、未触碰正式
G1。WSL 验证路径实际位于 `/mnt/f`/DrvFS，只计 Windows/WSL 双平台兼容，不计 Linux/ext4 证据。

## 2. R1 阻断复验

R1 的核心失败是普通 non-null rejection 的 `rejected_notional` 可被单独伪造。本轮从 public F2 重新构造五类
合法 transition，使用实现者正式测试未采用的 `+ Decimal("0.007")` 单字段扰动：

| reason | side | R2 结果 |
|---|---|---|
| `T_PLUS_ONE` | SELL | 构造时拒绝 |
| `LOT_CONSTRAINT` | SELL | 构造时拒绝 |
| ordinary `LOT_CONSTRAINT` | BUY | 构造时拒绝 |
| `CASH_CONSTRAINT` | BUY | 构造时拒绝 |
| `SELL_AT_LOWER_LIMIT` | SELL | 构造时拒绝 |

代码核对确认：普通 non-null rejection 逐项要求
`rejected_notional == reference_open * rejected_quantity`；该经济校验没有被 digest 替代。R1 阻断已关闭。

## 3. 独立新增对抗

### 3.1 special-only reference 与 self-digest

独立覆盖 current=0 的 raw=0 与 raw<min 两种可达 special-only transition：

- 仅将 reference open 增加 `0.0001`、保留旧 digest：拒绝；
- 仅修改一位 lowercase digest：拒绝；
- 同步修改 reference entry 并 fresh 重算 digest：可构造。

第三项是任务单明确承认的 plain-value `whole-rehash` 边界，只说明对象内部自洽，不是签名、capability、首次来源
或防篡改锚。本轮没有把它误报为来源闭包。

另构造 current>0、SELL 因 lower limit 被阻断且仍保留独立 BUY target-attainability LOT 的 transition；单改
reference 或单改 digest 均拒绝。SELL 拒单仍按 open×quantity 守恒，§14 BUY LOT 仍按 target notional 守恒，
两个数量/金额域未混算。

### 3.2 reference 集合、fill 与 null intent

独立结果：

- 从双 symbol special-only transition 删除 entry、增加 extra entry、逆序 entries：全部拒绝；
- fill 的 `reference_open` 单独增加 `0.0001`：拒绝；
- FULL_DAY/missing-target null intent 的 `reference_opens == ()`，加入伪 reference：拒绝；
- null rejection notional 继续按 target 与 pre-position mark gap 复算，不查询 reference open。

### 3.3 hostile Decimal 与异常图

在低 precision、`ROUND_UP`、收紧 Emax/Emin 且 `Inexact` trap 开启的 ambient context 中，提交非法 target：

- public API 只抛 exact `M3_A_SHARE_EXECUTION_INVALID`；
- `__cause__ is None` 且 `__context__ is None`；
- 调用前后 ambient Decimal context 与 flags 不变。

未观察到敏感输入、路径或内部异常图泄漏。

## 4. 静态合同核对

- `reference_opens` 要求 exact outer/inner tuple、strict symbol 升序唯一、exact str、finite positive Decimal；
- canonical digest payload 为
  `["m3-formal-reference-opens-v1", [[symbol, decimal_plain_text], ...]]`，JSON 使用紧凑 separators 与 UTF-8；
- Decimal 使用无指数 plain text；digest 为 bare lowercase 64hex，并 fresh 重算后比较；
- reference symbol set exact 等于 non-null intent symbol set，null intent 不得持有 reference；
- fill reference exact 等于对应 entry；普通 rejection、§14 special 与 null gap 保持三个独立守恒域；
- public builder 从同次 F1 states 在 intents 完成后生成 reference entries 和 digest；未新增 caller open-state 或 caller
  transition 入口；
- 未引入 key、HMAC authority、registry、seal、pickle token 或 I/O 来源旁路。

## 5. 当前最终 revision 验证

所有命令均在 `artifacts/dev_worktrees/m3-g4-formal` 使用该工作树自身 `src`。

### 5.1 Windows 原生 Miniforge

- F2/F1/development execution/allocation：**111 passed**，346.40s；
- F0/G7C/development simulator：**37 passed**，317.80s；
- Ruff（production/export/formal F2 test）：**PASS**；
- mypy `--no-incremental --show-traceback`：**PASS**，1 source file；
- cold import/public signature：**PASS**，无 `open_states`，未加载 qlib/lightgbm/mlflow。

### 5.2 WSL Miniforge base

- F2/F1/development execution/allocation：**111 passed**，422.60s；
- F0/G7C/development simulator：**37 passed**，382.71s；
- Ruff：**PASS**；
- mypy `--no-incremental --show-traceback`：**PASS**，1 source file；
- cold import/public signature：**PASS**。

两平台 pytest 仅有既有 pandera deprecation warnings 与工作树 `.pytest_cache` 写权限 warning；没有测试失败。
指定白名单 `git diff --check` **PASS**，只有既有 LF/CRLF 提示，无 whitespace error。

第一次并行静态批次出现 mypy 2.3.0 internal error，另一次 WSL cold 命令被 PowerShell 引号误解析；二者均不计
验收证据。随后按平台单独以 `--no-incremental --show-traceback` 重跑 mypy，并修正 WSL argv 后取得上述可计
PASS。

## 6. 结论与剩余边界

R2 已关闭 R1 普通 rejection notional 单漂移漏洞，也覆盖 special-only reference 无其他数值锚时的 exact 内容
绑定。任务单 §15-§16、独立对抗、双平台最终回归、静态和冷导入均通过，因此本轮独立复验结论为 **PASS**。

剩余边界必须继续保留：

1. self-digest 允许同步 whole-rehash，不证明可信来源或防篡改；
2. G7E 必须内部调用 public F2 并立即消费，不得接收 caller transition；
3. `/mnt/f`/DrvFS 结果不替代 Linux/ext4 Gate；
4. 本报告只解锁主 Agent 对 F2 R2 的最终验收，不解锁正式 G1、artifact 发布或 M3 Gate。
