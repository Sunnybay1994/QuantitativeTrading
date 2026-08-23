# M4 P8 RUN-0W R1：Windows PAPER Soak Runtime 交付报告

状态：实现、Windows 定向开发检查与主 Agent 范围/合同检查完成；待独立分支提交；未合流、未启动 PAPER
分支：`codex/m4-windows-soak-runtime`
基线：`9fc08ba`
日期：2026-08-16（Asia/Shanghai）

## 1. 交付结论

已按
[`M4_P8_RUN0W_R1_WindowsPAPERSoakRuntime任务单.md`](M4_P8_RUN0W_R1_WindowsPAPERSoakRuntime任务单.md)
新增身份独立的 `PAPER_REAL_TIME_WINDOWS` runtime/soak track：

- 原 `PAPER_REAL_TIME` 的 Linux-only verifier 保留原签名和原条件，不接受 Windows；
- Windows formal runtime 由新 dispatcher 调用独立 verifier，实际查询 Win32 volume，要求本地 fixed NTFS、
  persistent ACL、`D:\Miniforge3` base、五根同 parent sibling，以及既有实体身份和 fresh preflight；
- mode 已进入既有 config、environment 和 attestation 身份闭包；
- Windows soak 使用 exact `VerifiedPaperSoakEvidence` 和 production UTC wall-clock，但
  `formal_gate_eligible` 恒为 `false`；
- 完整 Windows 28 日证据只返回 `PASS_WINDOWS_SCOPE`，并恒带
  `SOAK_WINDOWS_NOT_FORMAL_GATE_ELIGIBLE`，永不返回 Linux exact `PASS`；
- development 和 Linux 的既有 mode/kind/status/eligibility 语义未改。

本轮没有注册任务、创建订单、启动 PAPER 或 28 日计时，也没有提供 LIVE 权限。

## 2. 精确改动

- `src/quant/execution/paper_runtime.py`
  - 扩展 exact formal mode literal；
  - 新增 mode dispatcher，但保留原 Linux formal verifier；
  - 使用 `GetVolumePathNameW`、`GetVolumeInformationW`、`GetDriveTypeW` 形成实际 Windows volume proof；
  - volume root、NTFS、不可逆 volume/device identity、fixed-drive/ACL capability 进入既有 stable platform
    projection；
  - fresh layout 校验重新查询 Windows volume，阻止 volume/root 漂移；
  - Windows prefix、executable、conda env 和实体 identity 严格绑定 `D:\Miniforge3` base。
- `src/quant/execution/soak.py`
  - 新增 `SoakEvidenceKind.PAPER_REAL_TIME_WINDOWS`；
  - 两种 real-time kind 共用 production wall-clock 约束；
  - Windows eligibility 保持 false；
  - 新增 `PASS_WINDOWS_SCOPE` 与内部 status/kind 一致性 proof。
- `configs/trading/paper_runtime.example.toml`
  - 默认仍为无副作用 `development-example`；
  - 只增加两种 formal mode 及 Windows NTFS/Miniforge/五根要求的注释。
- `tests/unit/test_paper_runtime.py`
  - 覆盖 exact mode/config identity、actual Windows Miniforge base + Win32 NTFS mint/fresh preflight、
    OS/WSL/FS/prefix/executable/conda/device whole-rehash 漂移拒绝。
- `tests/unit/test_execution_soak.py`
  - 覆盖 Windows manifest/wire/eligibility、waiting/blocked/complete、禁止 exact PASS、eligibility 与 decision
    whole-rehash、real-time anti-backdating，并确认 Linux complete 仍 exact PASS。

未修改 `src/quant/execution/__init__.py`、runbook、根/共享 SSOT、其他 execution 模块或其他 worktree。

## 3. 开发检查

所有 Python 检查均在指定 worktree 中使用 `D:\Miniforge3\python.exe`，父 PowerShell 先设置
`PriorityClass=BelowNormal`、`ProcessorAffinity=0xF00`（CPU 8–11）；pytest 未使用并行插件。

1. 新增/关键合同聚焦：

   ```text
   python -m pytest tests/unit/test_paper_runtime.py tests/unit/test_execution_soak.py \
     -q --basetemp <workspace-artifacts-unique-temp> \
     -k "windows or formal_clock or linux_complete_decision"
   16 passed, 112 deselected in 8.19s
   ```

2. 两个获批测试文件完整定向回归：

   ```text
   python -m pytest tests/unit/test_paper_runtime.py tests/unit/test_execution_soak.py \
     -q --basetemp <workspace-artifacts-unique-temp>
   92 passed, 36 skipped in 50.81s
   ```

   36 个 skip 是既有平台条件分支；本轮 actual Windows happy path 已实际执行通过。

3. 静态检查：

   ```text
   python -m ruff check src/quant/execution/paper_runtime.py src/quant/execution/soak.py \
     tests/unit/test_paper_runtime.py tests/unit/test_execution_soak.py
   All checks passed!

   python -m mypy src/quant/execution/paper_runtime.py src/quant/execution/soak.py
   Success: no issues found in 2 source files
   ```

4. cold import 与 diff：

   ```text
   M4_RUN0W_COLD_IMPORT_PASS
   git diff --check
   PASS（仅 Git 的预存 LF→CRLF 提示，无 whitespace error）
   ```

首次 pytest 尝试使用用户级 `%TEMP%`，因沙箱无权枚举
`C:\Users\mbw\AppData\Local\Temp\pytest-of-mbw`，形成 `6 passed, 7 skipped, 114 setup errors`；该结果发生在
fixture setup 前，不作为代码结论。随后改用 workspace 内、worktree 外的唯一受控 `--basetemp` 得到上述有效
终态。四个本轮生成的 basetemp 已按精确路径校验后删除。

## 4. 边界与剩余风险

- 本报告只证明 Windows/NTFS/Windows Miniforge base 开发范围，不等于 Linux/ext4 Gate；本轮未运行 WSL
  平台终验。
- 当前没有真实 `PAPER_CANDIDATE`、opening facts 或 28 日自然证据，因此没有实际 soak Gate 结果。
- Win32 volume proof 使用不可逆摘要绑定 volume serial/root/`st_dev`，不在公开错误或报告中暴露卷序列号。
- 主 Agent 已核对精确白名单、公共 mode/decision 边界和 scoped diff，未发现需扩大范围的阻断；下一步只在
  当前独立分支形成精确提交并回报统筹，不 merge、不 push。
