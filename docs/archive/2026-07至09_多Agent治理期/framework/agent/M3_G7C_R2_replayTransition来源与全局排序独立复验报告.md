# M3 G7C R2 replay/transition 来源与全局排序独立复验报告

日期：2026-08-09  
角色：未参与 R1/R2 实现的独立复验 Agent  
结论：**FAIL；R2 强制回归测试矩阵未闭合，返回返工，不得进入主 Agent 最终验收**

## 1. 独立性、范围与边界

- 本 Agent 未参与 R1/R2 实现，使用全新独立上下文。
- 已阅读 `AGENTS.md`、`.ai/README.md`、`.ai/philosophy.md`、`.ai/coding_rules.md`、
  `.ai/workflows/multi_agent_delivery.md`、R1 任务单最终 §12、R1 独立初验报告、R2 返工交付报告、
  `corporate_actions.py`、安全导出和 formal/development/邻接测试。
- 生产代码与实现者测试全程只读；本报告是唯一新增仓库文件。未联网、未执行 `git add/commit`、未读取正式
  G1 数据或 journal。
- 独立业务状态样例仅使用内存 facts 和系统临时目录，退出即清理，未写入正式测试文件。

## 2. §12 标准—独立证据—结论

| R2 冻结标准 | 独立证据 | 结论 |
| --- | --- | --- |
| state/transition 是一次性 closure 产生的 exact runtime type；constructor、`replace`、`object.__new__`/clone 不可签发可消费对象 | `corporate_actions.py:516-736,1001-1021`；正式测试 `:259-300,405-485` 验证 constructor、replace、slots clone、字段漂移及 registry+clone 攻击 | 通过 |
| state attestation 绑定 identity/index/phase/positions/processed IDs/quantities，且 property/repr 每次消费前复验 | `corporate_actions.py:524-624` 将 payload、nonce、exact instance id 和 HMAC 绑定，并在所有 property/repr 中调用 verifier | 通过 |
| transition attestation 绑定输入 state 证明、operation/date/facts/quantity、输出 state、完整 postings/delta/stock | `corporate_actions.py:626-736,852-876,971-995` 的 payload 与 HMAC 覆盖冻结字段；对已签发对象删全部 posting 的现有测试会拒绝 | **实现证据通过；强制测试矩阵不通过** |
| module/public callable graph 不存在 raw register/sign/mint/key/factory issuer；纯 expected helper 不接触签发闭包 | 初始化器装载后在 `corporate_actions.py:1013-1021` 删除；`_expected_positions` 位于 closure 外；正式测试 `:405-481` 遍历 module/callable graph 并攻击 closure WeakSet | 通过 |
| processed IDs、record quantities、positions 全局按 event_id canonical；日期可达性仍独立复算 | capture 在 `corporate_actions.py:909-936` 合并后排序；`_validate_formal_replay_values` 在 `:1218-1272` 按日期 cutoff 复算可达集合；现有跨日与同日测试 `:302-378` 通过 | 通过 |
| reload 旧 formal value 必须在 fresh subprocess 失败，且 development/邻接类型不被污染 | stable development 类型保留见 `corporate_actions.py:42-51,217-230`；fresh subprocess 测试 `:488-532` 通过；development、G7D-F0、G7E、M4 ledger 组合回归双平台通过 | 通过 |
| R2 新增测试至少覆盖删全部/单个/多出/换序 posting、全字段重签、delta/stock 漂移、cross-operation、旧 state 换 facts/date/quantity 等冻结反例 | 全仓测试搜索仅发现 `test_m3_formal_corporate_actions.py:294,482` 把 postings 改为空；旧 date 仅 `:252-256`；未找到单个 mixed posting 删除、extra/reorder、`cash_delta`/`settled_stock` 漂移、cross-operation、facts/quantity 输入漂移的测试 | **不通过** |

## 3. 返工问题

### P1-1：R2 强制 transition/输入漂移回归矩阵没有落成正式测试

- **现象**：实现使用 exact-instance HMAC，独立静态审查未发现对应运行时旁路；但任务书 §12 明确要求的多项
  regression case 不存在。当前正式测试只删除全部 postings，未删除单个 mixed posting，也未验证 extra/reorder、
  `cash_delta`、`settled_stock`、cross-operation、facts/quantity 输入证明漂移。
- **根因**：R2 测试集中验证了 constructor/clone/registry 和全删 postings，却把“同一 attestation 机制理论上会
  覆盖其余字段”当成了其余必测反例的替代。
- **应遵循规则**：任务单 §12 的“R2 新增测试至少覆盖”是显式完成条件；`AGENTS.md` §7/§11 要求高风险状态来源
  和跨 Gate 不变量由行为测试证明，不能只依赖实现者自报或静态推断。
- **最小复现**：在仓库 `tests/` 全局搜索 `_postings|_cash_delta|_settled_stock|quantity_inputs`；只有
  `test_m3_formal_corporate_actions.py:294,482` 的全删 postings 攻击，无上述其余行为节点。
- **必须新增的测试**：对真实同日 mixed ADVANCE transition 分别删除一个 recognize、删除一个 settle、增加或重排
  posting；分别漂移 cash delta、settled stock、operation/date/facts identity/quantity inputs/input-state proof；复制全部
  字段与 nonce/attestation 到新 exact slots instance；每项在 property/repr 或公开消费前必须得到唯一稳定错误且无
  cause/context。测试还应明确区分“旧 date”与“旧 state 换 facts/quantity”。
- **通过条件**：以上节点进入正式测试并在 Windows 与 WSL Miniforge base 的相同定向组合中全部通过；随后由新的
  未参与返工者再次独立复验。

## 4. 实现者未使用的临时业务状态样例

独立样例把三个事件 ID 与时间顺序刻意交错：窗前 record 事件为 `c…`，窗内首日 record 为 `b…`，较晚 record
为 `a…`。窗前事件的 caller mapping 即使给 `999`，初始化仍固定记录零账户持仓，不建立 position；窗内两次
record-close 分别使用 `b=100`、`a=50`。

实际输出：

```text
TEMP_BUSINESS_STATE_PASS
INITIAL= (('c', 0),)
AFTER_DAY0= (('b', 100), ('c', 0))
AFTER_DAY2= (('a', 50), ('b', 100), ('c', 0))
```

最终 positions 仅为 `a…, b…`。该样例证明当前实现没有把全局 event-id 排序误当跨日处理时间，也没有把窗前
未知持仓伪造成 entitlement；它不消除 §3 的正式测试缺口。

## 5. 独立验证结果

所有命令均显式使用本 worktree `src`；pytest 禁用仓库 cache，并把临时目录放在系统临时区。

Windows 原生 `D:\Miniforge3\python.exe`：

- formal + development + G7D-F0 + G7E + M4 ledger 组合：`74 passed`（177.29s）；
- 定向 Ruff：`All checks passed!`；
- 定向 mypy：`Success: no issues found in 1 source file`；
- cold import：`WINDOWS_COLD_IMPORT_PASS`，未加载 Qlib；
- 临时业务状态样例：`TEMP_BUSINESS_STATE_PASS`。

WSL Miniforge `base`，绝对 `/mnt/f/.../m3-g4-formal/src`：

- 相同组合：`74 passed`（131.25s）；
- 定向 Ruff：`All checks passed!`；
- 定向 mypy：`Success: no issues found in 1 source file`；
- cold import：`WSL_COLD_IMPORT_PASS`，未加载 Qlib；
- `stat -f`：`FS_TYPE=wslfs`。当前路径在 `/mnt/f`，**不是 ext4**。

一条首次 WSL pytest 承载命令因 PowerShell 提前展开路径而在 5.7s 空输出，另一次 WSL cold-import 子命令因
引号拆分明确报 SyntaxError；两者均未计入通过证据，之后都用绝对 WSL 路径/独立单引号承载重跑成功。pytest
只有既有 Pandera/Polars deprecation warnings。

## 6. 结论与边界

R1 的三项运行时缺陷在当前 R2 实现中已有可信修复证据；独立临时业务状态样例和双平台组合回归也均通过。
但任务书 §12 把完整对抗性测试矩阵冻结为 R2 必须项，当前测试没有覆盖其中多项，所以本轮独立复验只能判定
**FAIL，返回最小测试返工**。本结论不声称发现了新的运行时经济语义缺陷，也不等于 Linux/ext4、真实 full-work、
完整账户回测或 M3 Gate 关闭。
