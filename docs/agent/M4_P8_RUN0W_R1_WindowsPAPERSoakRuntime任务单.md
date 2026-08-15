# M4 P8 RUN-0W R1：Windows PAPER Soak Runtime 任务单

状态：实现与 Windows 定向开发检查完成；待独立分支提交和统筹合流；未启动 PAPER
基线：`codex/m4-windows-soak-runtime@9fc08ba`
日期：2026-08-15（Asia/Shanghai）

## 1. 目标与依据

用户已在 `docs/用户待批示与参与事项.md` 的 UA-M4-002 中明确批准：本轮真实 PAPER soak 可在 Windows
执行，并暂不把 Linux/ext4 作为启动条件；但不得把 Windows 证据表述为 Linux/ext4 Gate。现有
`paper_runtime.py` 只允许 `Linux + WSL2 + ext4 + WSL base`，所以即使真实候选和 opening facts 齐备，
Windows 仍会在任何业务入口前返回 `PAPER_RUNTIME_PLATFORM_UNSUPPORTED`。

本任务新增一个身份独立的 Windows PAPER soak track，同时保持原 Linux formal track 的字节、语义和 Gate
不变。它只关闭 Windows runtime/profile 与 soak decision 的工程缺口，不注册任务、不创建订单、不启动 28 日
计时，也不提供 LIVE 权限。

## 2. 冻结公共语义

### 2.1 Runtime mode

- 保留 `PAPER_REAL_TIME`：只接受现有 Linux、WSL2、ext4、WSL Miniforge base；原 verifier 不得放宽。
- 新增 exact mode `PAPER_REAL_TIME_WINDOWS`。
- 两种正式 mode 均返回现有 exact `FormalPaperRuntimeConfig` 与
  `VerifiedPaperRuntimeEnvironment`，避免修改下游 formal capability 类型。
- `FormalPaperRuntimeConfig.mode` 精确收窄为上述二值 `Literal`；development 仍是独立
  `DevelopmentPaperRuntimeConfig`，不得 cast 或混配。
- mode 必须进入 config identity、environment identity 与 attestation；只改 mode 必然改变身份并使旧 capability
  失效。

### 2.2 Windows 平台证明

`PAPER_REAL_TIME_WINDOWS` 只能由 actual probe 证明以下事实：

1. `platform.system()` 为 exact `Windows`，WSL generation 为 `none`；
2. runtime 五根仍是同一物理 parent 下互不为祖先的 sibling，且 parent/root chain 无 symlink、junction 或
   reparse point；
3. parent 所在卷由 Win32 volume API 证明为 NTFS，不以字符串 `windows` 冒充文件系统类型；
4. 当前解释器为已批准的 Windows Miniforge base：resolved prefix 与 `CONDA_PREFIX` 均为
   `D:\Miniforge3`，`CONDA_DEFAULT_ENV=base`，executable 为该 prefix 下的 `python.exe`；解释器和 prefix
   实体身份均纳入现有 platform proof；
5. volume root、filesystem type、device、parent、prefix、executable 等仍进入稳定 platform projection；fresh
   verifier 每次重验。

任一事实不满足统一返回现有稳定错误 `PAPER_RUNTIME_PLATFORM_UNSUPPORTED`，公开 cause/context 均为空。
Windows profile 不接受 WSL1/DrvFS、FAT/exFAT、任意 Python、venv、其他 conda env 或 caller 自报 platform。

## 3. Windows soak evidence 与决策

- `SoakEvidenceKind` 新增 exact `PAPER_REAL_TIME_WINDOWS = "paper_real_time_windows"`。
- Windows real-time 与 Linux real-time 一样必须使用模块内 production UTC wall-clock 建立 manifest、session、fault、
  anchor 与 decision 的时间闭包；不得退化为 development 可注入时钟。
- Windows manifest 的 `formal_gate_eligible` 必须恒为 `False`；Linux `PAPER_REAL_TIME` 仍恒为 `True`。
- Windows evidence 继续使用 exact `VerifiedPaperSoakEvidence`，不得被归类为 development evidence。
- `SoakGateDecision.status` 新增 `PASS_WINDOWS_SCOPE`：只有 28 日、全部 expected sessions、全部冻结 fault drills、
  session/reconciliation/report 全部通过时才能返回；同时 stable codes 必须包含
  `SOAK_WINDOWS_NOT_FORMAL_GATE_ELIGIBLE`。
- Windows evidence 永远不得返回 exact `PASS`。缺 session/span/drill 时返回 `WAITING_FOR_SOAK_EVIDENCE`；有业务
  阻断时返回 `BLOCKED`。Linux 与 development 的既有 decision 逐字保持原语义。
- manifest、wire encoding、fresh verifier、anchor 与 decision identity 必须绑定新 kind/status；caller 使用
  `replace`、合法 whole-rehash、跨 mode/root 复用或旧 enum 值均不能把 Windows evidence 提升为 Linux Gate。

## 4. 配置示例

只修改既有 `configs/trading/paper_runtime.example.toml`：默认仍保持无副作用的 `development-example`，新增注释
说明两种正式 mode、Windows Miniforge/NTFS/五根要求，以及 deployment 必须另建 ignored 的实际配置。示例不写
用户账号、token、真实运行根或任何凭据。

## 5. 稳定错误与兼容

- runtime 继续只使用既有 `PaperRuntimeError` 稳定码；不暴露 path、volume 名称、prefix 内容或 hostile marker。
- soak 继续只使用既有 `SoakError` 稳定码；非法 kind/status/eligibility 组合为既有 invalid 类错误。
- 现有 Linux formal、development、cold/materialized 两态、B2D–D1 exact type、所有 wire schema 与 public exports
  不变。本任务暂不修改 `src/quant/execution/__init__.py`。

## 6. 文件白名单

仅允许修改：

- `src/quant/execution/paper_runtime.py`
- `src/quant/execution/soak.py`
- `configs/trading/paper_runtime.example.toml`
- `tests/unit/test_paper_runtime.py`
- `tests/unit/test_execution_soak.py`
- `docs/agent/M4_P8_RUN0W_R1_WindowsPAPERSoakRuntime任务单.md`
- `docs/agent/M4_P8_RUN0W_R1_WindowsPAPERSoakRuntime交付报告.md`
- 统筹明确要求的 `docs/roadmaps/M1_M3_M4_框架开发总路线图.md`

禁止修改 `execution/__init__.py`、runbook、根/共享 SSOT、M2/M3/M1 文件、scheduler、daily/operator、Gateway、
OMS、风控、账户、store 或真实 runtime roots。

现有依赖图已经存在 `execution.soak -> reporting -> execution` 循环；本任务不得再新增任何
`quant.execution` 到 `quant.reporting` 的 import，也不得把报告生成、读取或聚合逻辑塞入 runtime/soak。
循环依赖治理属于后续独立任务。

## 7. 必测合同

1. 原 `PAPER_REAL_TIME` 在 Windows 仍拒绝，Linux verifier 分支结构和约束未放宽。
2. `PAPER_REAL_TIME_WINDOWS` config exact 加载，mode/config/environment identity 与 Linux mode 不同。
3. Windows actual Miniforge base + NTFS + sibling roots 可签发；错误 OS、WSL、FS、prefix、executable、conda env、
   parent/device/reparse 任一拒绝。
4. cold 与 materialized fresh preflight、reload/旧 capability、config/volume/root replacement 继续 fail closed。
5. Windows soak manifest 为 real-time、`formal_gate_eligible=false`；完整证据只返回 `PASS_WINDOWS_SCOPE` 与稳定
   non-formal code，从不返回 `PASS`。
6. Windows incomplete / blocked / hostile clock / eligibility 或 kind whole-rehash 漂移分别按冻结语义拒绝或分类。
7. 原 development 与 Linux soak tests 不改变；wire readback、anchor、fresh evidence 和 idempotency 仍通过。

## 8. 开发检查与资源边界

- 只运行 `tests/unit/test_paper_runtime.py`、`tests/unit/test_execution_soak.py`、对应 Ruff 与两个生产文件 mypy；
  必要时补一次 cold import。
- Windows 测试进程使用 `BelowNormal`，CPU affinity 固定在 8–11，避免与 M3 的 0–7 重叠。
- 不启动外部 Agent；内部实现 subagent 只承担本独立 worktree 的真实并行实现，不另建“独立初验”。
- 完成后写唯一交付报告，回报精确 diff 与 commit；不 merge、不 push、不注册/运行 PAPER。
