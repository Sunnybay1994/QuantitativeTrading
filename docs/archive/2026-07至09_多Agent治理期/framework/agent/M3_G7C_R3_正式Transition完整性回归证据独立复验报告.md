# M3 G7C R3 正式 Transition 完整性回归证据独立复验报告

日期：2026-08-09

角色：未参与 R3 tests-only 返工的全新独立复验上下文

结论：**PASS；R3 已闭合 §13 强制持久化回归证据，可进入主 Agent 最终验收**

## 1. 独立性、范围与边界

- 已完整阅读 `AGENTS.md`、`.ai` 通用规则、G7C 任务书最终 §13、R2 独立 FAIL 报告、R3 交付报告、
  `src/quant/backtest/corporate_actions.py`、`src/quant/backtest/__init__.py` 与
  `tests/unit/test_m3_formal_corporate_actions.py`，并核对 development、G7D-F0、G7E simulator、M4 ledger
  的实际邻接测试集合。
- 生产代码、实现者测试和既有文档全程只读；本报告是本轮唯一新增仓库文件。未联网，未执行
  `git add/commit`，未触碰正式 G1 数据、artifact、journal 或真实 I/O。
- 独立对照只使用内存构造的 exact facts 与系统临时目录，退出后自动清理；没有把临时代码写入仓库。

## 2. §13 标准—正式证据—独立证据—结论

| §13 强制节点 | R3 正式测试证据 | 本轮实现者未使用的独立对照 | 结论 |
| --- | --- | --- | --- |
| mixed transition 仅删除一个合法 posting | `test_m3_formal_corporate_actions.py:537-589` 签发现金+送股同日四 posting 的 ADVANCE，并删除最后一条 | 两个 mixed event 形成八条 posting，删除索引 1 的中间 recognize posting | 通过 |
| extra posting 与合法 posting 换序 | `:591-596` 分别追加重复 posting、交换前两条 posting | 追加另一条合法 CAPTURE posting；把最后一条 posting 轮转到首位 | 通过 |
| 单独漂移 `cash_delta` 与 `settled_stock` | `:598-602` 分别改为 `0` 与空 tuple | `cash_delta + 0.01`；把一只股票的 settled quantity 从 10 改为 11 | 通过 |
| cross-operation | `:604-605` 把 ADVANCE 改作 CAPTURE | 把合法 ADVANCE 改作 INITIALIZE | 通过 |
| facts identity 漂移 | `:607-623` 既改 transition facts identity，也把旧 state 交给另一份 exact facts 的 public advance | 使用第二份 exact facts；transition property/repr 与旧 state+新 facts 的 public advance 均拒绝，同时新 facts 自身 state 可推进 | 通过 |
| quantity 输入漂移 | `:625-628` 把合法 CAPTURE 的 quantity proof 从 100 改为 99 | 分别签发 100/50 与 90/50 两个合法 CAPTURE，把后者的完整 canonical quantity proof 交换到前者 | 通过 |
| fail closed 且原合法对象仍可消费 | `reject_drift` 在攻击前消费 property，攻击后同时验证 property/repr；`:630-642` 重签 clean CAPTURE/ADVANCE 并消费 | 每项攻击同时检查稳定错误、无 cause/context；独立保留的 untouched transition 及攻击后的 fresh transition 仍可消费 | 通过 |

所有攻击均得到唯一稳定错误 `M3_A_SHARE_ENTITLEMENT_INVALID`，没有泄漏内部 cause/context。正式节点不是只做
静态字段搜索：它真实签发 exact runtime state/transition 后通过 `object.__setattr__` 漂移已签发字段，再在公开
property、`repr` 或 public advance 边界消费，因此能复现 R2 报告指出的证据缺口。

## 3. 独立临时差分对照

独立样例刻意不同于实现者的一只 mixed event：同一 record/ex/due 日放入两只现金+送股事件，合法 ADVANCE
产生八条 ordered posting、`cash_delta=2.01`、`settled_stock=((600000.SH, 10), (000001.SZ, 10))`。逐项执行：

1. 删除中间 recognize posting；
2. 追加 CAPTURE posting；
3. 把最后一条 posting 轮转到首位；
4. 漂移 cash delta、settled stock 与 operation；
5. 换用第二份 exact facts identity，并在 public advance 混用旧 state/新 facts；
6. 把另一份合法 CAPTURE 的完整 canonical quantity proof 交换到旧 transition。

结果：`WINDOWS_G7C_R3_INDEPENDENT_DIFFERENTIAL_PASS`。全部攻击在 property+repr 或 public 边界 fail closed；
untouched 控制、另一份 facts 的自身合法 state、另一份 quantity transition 和攻击后 fresh transition 均仍可消费。

首次试探把 100 股改成 99 股，但 `stock_ratio=0.1` 会产生 9.9 股，系统在签发 alternate control 前按“送股必须为
整数”合同拒绝；该次不计通过证据。随后改用同样发生真实输入变化且仍合法的 90 股，完整差分对照通过。这是
对照输入修正，不是 production 缺陷。

## 4. R2 → R3 production 零变化

当前独立计算 SHA256：

- `src/quant/backtest/corporate_actions.py`：
  `415D8E428E6D2019B92120E10A4B76C65CCEBEE42A5A4262D9E982A937BEE05E`
- `src/quant/backtest/__init__.py`：
  `BA1BD0CB2AA55B264C47D33D0C7044C3ECCBE31343BEBDA625876BB64E7665D8`

二者精确等于 R3 交付报告锁定的 R3 开始前（R2 完成态）和完成后 hash；当前 worktree diff numstat 也仍分别为
`891 2` 与 `30 0`。文件 UTC mtime 分别为 05:32:47、04:31:43，均早于 R2 独立报告 06:03:06、R3 测试
06:09:43 与 R3 交付报告 06:21:17。scoped `git diff --check` 通过。

边界说明：R2/R3 尚未形成独立 Git commit，所以不能用 commit-to-commit diff 证明历史；本结论基于任务要求允许的
等价证据——实现者冻结的前后 hash/numstat、当前独立重算完全一致，以及文件时间顺序。未发现 R3 增加 production
diff、parallel capability、signer、测试旁路或宽松 exact-type 行为。

## 5. 双平台独立验证

所有测试都显式使用本 worktree `src`，禁用 pytest 仓库 cache。

Windows 原生 `D:\Miniforge3\python.exe`：

- formal + development：`28 passed`（95.46s）；
- G7D-F0 formal facts + G7E simulator + M4 ledger：`46 passed`（50.30s）；
- 定向 Ruff：`All checks passed!`；
- 定向 mypy：`Success: no issues found in 1 source file`；
- cold import/public surface：`WINDOWS_G7C_R3_COLD_IMPORT_PASS`，包导出与模块 exact type/callable 同一，
  initializer 已删除，未加载 Qlib。

WSL Miniforge `base`（Python 3.13.13，绝对 `PYTHONPATH=/mnt/f/.../m3-g4-formal/src`）：

- 相同 formal + development：`28 passed`（89.60s）；
- 相同 G7D-F0 + G7E + M4 ledger：`46 passed`（32.81s）；
- 定向 Ruff：`All checks passed!`；
- 定向 mypy：`Success: no issues found in 1 source file`；
- cold import/public surface：`WSL_G7C_R3_COLD_IMPORT_PASS`。

两平台 pytest 只有既有 Pandera/Polars deprecation warnings，无断言失败。WSL `stat -f` 返回
`FS_TYPE=wslfs`；当前 worktree 位于 `/mnt/f` 的 DrvFS/wslfs，**不是 ext4**。因此这里只证明 Windows 与 WSL
base 工程兼容，不把结果表述为 Linux/ext4 Gate。

## 6. 结论与剩余边界

R2 FAIL 指出的唯一问题是强制 transition/input 漂移矩阵未持久化。R3 已以一个最小正式节点覆盖 §13 全部场景，
生产两文件保持 R2 完成态，独立的新差分对照及 Windows/WSL base 各 74 项组合回归均通过。因此本轮结论为
**PASS，可进入主 Agent 最终验收**。

本 PASS 不等于主 Agent 最终验收、Linux/ext4、真实 full-work、完整账户回测或 M3 Gate 关闭；这些边界仍按
任务书与 `AGENTS.md` 保持待后续 Gate 判断。
