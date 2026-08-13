# M4-P8-RUN-0A R3：环境工程合同主 Agent 最终验收报告

日期：2026-08-09  
角色：主 Agent 最终验收  
结论：**PASS（仅 RUN-0A 环境工程合同）**

## 1. 验收范围

本次主验依据 `M4_P8_RUN0A_平台路径与Runtime身份任务单.md` §13–§14、R3 实现交付报告和未参与实现的
R3 独立复验报告，验收 strict runtime config、actual platform/base/filesystem preflight、五根 layout 身份、
formal/development exact-type 隔离及 formal 环境 capability 的唯一签发路径。

本结论不表示已存在正式 PAPER runtime、runner、broker、schedule 或 soak 证据，也不关闭真实 WSL2/ext4
平台 Gate。

## 2. 主验结论

- RUN-0A 已收缩为纯环境能力，不签发账户、OMS store、gateway、source 或 runtime config 等业务身份；
- 模块普通调用面不存在 generic formal component signer、`_build_environment`、`_sign_environment`、等价
  factory 或模块级 formal signing key；
- `verify_paper_runtime_environment(*, config, now)` 是唯一 formal mint 入口；它在同一次私有 closure 中完成
  fresh config file/parent、actual project/layout、actual WSL generation/base/ext4、parent/root identity 和返回前
  fresh closure 后才构造 exact `VerifiedPaperRuntimeEnvironment`；
- existing verifier fresh 调用同一 public actual 路径，development 只返回 exact 不同类型；
- Windows 与当前 WSL1/DrvFS actual 环境均在任何正式 leaf 写入前稳定拒绝。模拟 WSL2/ext4 仅证明纯合同，
  未被计作真实平台证据；
- R1 的 generic signer、caller-controlled protected roots、config ABA、parent replacement、base spoof、nested
  drift，以及 R2 的 unsupported Windows/system-temp 自行 mint 路径均已由实现测试和独立反例关闭。

因此 RUN-0A 可作为后续 RUN-0B1/B2、RUN-0C/D 的环境前置接口继续开发。

## 3. 验证证据

主 Agent 在 Windows 原生 Miniforge 定向复核：

- `pytest tests/unit/test_paper_runtime.py -q`：`19 passed, 30 skipped`；
- `ruff check src/quant/execution/paper_runtime.py tests/unit/test_paper_runtime.py`：PASS；
- `mypy src/quant/execution/paper_runtime.py`：PASS。

独立 R3 复验补充：

- Windows：`19 passed, 30 skipped`，Ruff、mypy PASS；
- WSL base `/mnt/f`：`49 passed`，Ruff、mypy PASS；
- evidence/anchor/log、五类 root identity、完整 nested+outer rehash、config ABA、parent TOCTOU、hostile
  traceback 等独立反例均 fail closed；
- actual `/mnt/f` 被确认是 WSL1/DrvFS，formal unsupported 且五 leaf 零写入。

## 4. 尚未关闭

- actual WSL2/ext4 上公开 formal preflight 成功证据；
- RUN-0B1 独立 durable PAPER broker、RUN-0B2 生产 loaders/risk、RUN-0C verified schedule、RUN-0D runner；
- 正式 runtime roots、Task Scheduler 注册与启动；
- 真实不少于 28 个自然日的 PAPER soak、故障演练及项目 M4 Gate。

正式状态继续保持 `WAITING_FOR_SOAK_EVIDENCE`。在上述前置完成并独立验收前，不创建正式 P8 root、
不注册任务、不启动正式 soak。
