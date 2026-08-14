# M3 G7C R3：正式 Transition 完整性回归证据主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS；G7C formal Entitlement 状态机工程合同关闭，允许进入 G7D-F1。**  
边界：本结论不等于真实全 work、Linux/ext4、G7D-F2/G7E/G7F、M3 或实盘 Gate。

## 1. 验收范围与职责分离

主 Agent 复核了 R1 独立失败、R2 来源闭包返工、R2 独立测试证据失败、R3 tests-only 交付及全新独立 R3
复验。R3 实现者只补正式测试，未修改 production；全新独立复验明确 PASS，并增加了实现者未使用的 mixed
双事件八 posting 差分对照。

## 2. 合同闭包

- formal replay state/transition 仍由 exact runtime 类型与内容绑定证明约束；constructor、replace、new、clone
  和模块级 raw register 不能形成可消费对象。
- transition 证明绑定 input state、operation、date、facts、quantity inputs、完整 ordered postings、cash delta、
  settled stock 与 output state。
- R3 持久化回归逐项覆盖：mixed 单 posting 删除、extra、reorder、cash delta、settled stock、cross-operation、
  另一 exact facts identity、另一 quantity 输入；每项在 property/repr/public 消费边界 fail closed，未改合法对象
  保持可消费。
- 跨日逆序 event_id 与窗前零持仓证据继续按全局 canonical event_id 合并；RIGHTS、record/ex/due、税前 CNY、
  HALF_UP cent 与 integer stock 的 R2 经济语义未改变。

## 3. Production 零变化证明

R3 前后及主验当前 SHA256 一致：

- `corporate_actions.py`：`415D8E428E6D2019B92120E10A4B76C65CCEBEE42A5A4262D9E982A937BEE05E`
- `backtest/__init__.py`：`BA1BD0CB2AA55B264C47D33D0C7044C3ECCBE31343BEBDA625876BB64E7665D8`
- formal test 当前：`45829ACAFA8C23270F7485F0D313109C4BEDD1736B8F30A6F111D1D6C37004F1`

scoped `git diff --check` 退出 0；仅观察到既有 LF/CRLF 提示，无 whitespace 错误。

## 4. 验证证据

实现交付与全新独立复验在 Windows、WSL base 各取得 `28 + 46 = 74 passed`，两平台 Ruff、mypy、cold
import 均 PASS。独立临时差分对照覆盖全部 R3 漂移场景并 PASS。

主 Agent：

- Windows 五文件 formal/development/G7D-F0/G7E/M4-ledger 邻接：`74 passed`，158.75 秒；
- Windows Ruff、cold import PASS；首次组合 mypy 2.3.0 报内部工具错误，随后 standalone
  `--no-incremental --show-traceback`：`Success: no issues found in 1 source file`；
- WSL base 直接解释器运行 R3 新增核心节点：`1 passed`；Ruff、mypy、cold import PASS；
- WSL 完整 74、拆分 28 在本主会话分别遇 600 秒承载超时且无断言失败摘要，均未计 PASS、未留下测试进程；
  本结论的 WSL 完整矩阵采用实现交付和全新独立复验各自已完成的 `74 passed`，不伪造主 Agent 长组结果。

WSL `FS_TYPE=wslfs`，路径位于 `/mnt/f`，仅为 DrvFS/WSL1 兼容证据，不是 ext4 Gate。

## 5. 最终裁定与剩余风险

R1 三项运行时阻断与 R2 的强制测试证据缺口均已关闭，未发现新的产品缺陷。G7C 状态可更新为主验 PASS，
并解锁已冻结的 `M3_G7D_F1_R1正式A股开盘执行事实任务单.md`。

仍开放：G7D-F1/F2、G7E/G7F、真实全 work 性能、Linux/ext4 与 M3 Gate；不得把本报告解释为完整账户回测
或实盘能力。未联网、未 add/commit、未触碰正式 G1/artifact/journal。
