# M4-P8-RUN-0A R2：环境能力收缩与身份闭包独立复验报告

日期：2026-08-09  
角色：未参与 R2 实现的全新独立复验上下文  
结论：**FAIL（R1 六项缺陷已闭合，但发现新的 formal environment 来源边界阻断）**

## 1. 独立性、范围与证据边界

- 复验前阅读了 `M4_P8_RUN0A_平台路径与Runtime身份任务单.md` §13、R1 FAIL 报告及 R2 返工交付报告。
- 只读检查 `src/quant/execution/paper_runtime.py`、`tests/unit/test_paper_runtime.py`、
  `configs/trading/paper_runtime.example.toml`；未修改生产代码、实现者测试或配置，未执行 `git add`/`commit`。
- 本报告只裁定 RUN-0A 环境工程合同。RUN-0B1/B2/C/D、正式 runner、真实 WSL2/ext4 和 soak 均不在本结论内。
- actual 证据仅有 Windows 与 WSL1/DrvFS；实现者的 ext4 字段替换测试和本轮复跑仍只是纯平台合同测试，
  不构成真实 WSL2/ext4 证据。

## 2. 标准—独立证据—结论

| §13 标准 | 独立证据 | 结论 |
| --- | --- | --- |
| public formal API 不再接收 component/hex，模块无通用业务 signer | `verify_paper_runtime_preflight` 只有 `config`、`now`；`PaperRuntimeComponentProof`、`PaperRuntimeComponentRole`、`_attest_runtime_component`、`_COMPONENT_KEY` 均不存在；全模块未发现等价 role+hex 业务 signer | 通过 |
| R1 config v1 拒绝；v2 绑定 file/parent/bytes，ABA、symlink/reparse、rename 拒绝 | 双平台定向测试覆盖 v1、同 bytes 不同文件对象、parent rename；Windows 实际临时 junction parent 独立探针输出 `WINDOWS_REPARSE_PARENT_REJECT_PASS`；loader 使用 no-follow（平台支持时）并比较 `lstat/open/fstat`、单链接、file identity 与 parent identity | 通过 |
| project root 不可伪报，caller 不能少报 protected roots | `project_root` 必须等于由当前源码 resolved 位置推导的 checkout root；v2 exact keys 拒绝 `protected_roots`；layout 无条件拒绝 actual project tree，formal 另拒绝 system temp | 通过 |
| platform/layout 及返回前 parent replacement 拒绝 | platform proof 保存 `parent_identity`；layout 构造后及返回前均与 fresh parent identity 闭合；双平台用例中的 probe→layout 与 return 前 replacement 均按预期拒绝、五 leaf 未创建 | 通过 |
| py312 prefix/executable 即使配 `CONDA_DEFAULT_ENV=base` 仍拒绝 | formal verifier exact 绑定 `/home/mabw/miniforge3`、其 resolved `bin/python`、两者物理 identity、`CONDA_PREFIX` 与环境名；定向反例通过 | 通过 |
| nested layout/platform 每字段及 whole-rehash 保留旧 outer token 均 fresh 拒绝 | 实现者参数化用例覆盖全部 platform 字段及 layout 主体；本轮另逐项补测遗漏的 `evidence_root`、`anchor_root`、`log_root` 和五个单独 root identity，全部得到 `PAPER_RUNTIME_PREFLIGHT_INVALID`；whole-rehash 旧 token 同样拒绝 | 通过 |
| formal/development exact type | formal 与 development config/result 为不同 exact dataclass；本轮补测 formal→development 与 development→formal 两个方向均得到 `PAPER_RUNTIME_MODE_INVALID` | 通过 |
| hostile reader/probe/path 异常脱敏、零写入；cold import | 本轮新增 in-memory hostile reader/path 探针，检查公开异常的 `cause/context` 及完整 formatted traceback 均不含 `TOKEN/PATH/SQL/payload` marker，leaf 零写入；现有 hostile probe 与 cold-import 用例双平台通过 | 通过 |
| actual Windows 与 WSL1/DrvFS 零写入 unsupported | Windows actual formal 用例得到 `PAPER_RUNTIME_PLATFORM_UNSUPPORTED`；`wsl.exe -l -v` 显示 Ubuntu VERSION 1，actual probe 输出 `WSL_GENERATION=1 FILESYSTEM=drvfs MOUNT=/mnt/f ROOT=/`，WSL 定向用例同样在 leaf 写入前拒绝 | 通过 |
| formal environment 只能由执行 actual checks 的 fresh verifier 证明，caller 不能自报 | 独立反例证明普通 caller 可直接调用模块级 `_build_environment` / `_sign_environment`，绕过 public formal verifier 构造并签发 exact formal capability | **不通过，阻断** |

## 3. 阻断问题：模块级通用 formal environment mint 绕过 actual verifier

### 3.1 现象

`paper_runtime.py:229` 将 `_sign_environment` 暴露为模块级 callable；`paper_runtime.py:991-1009` 的
`_build_environment(...)` 接受 caller 提供的 formal config、layout、platform projection 和时间，直接生成
`VerifiedPaperRuntimeEnvironment` 并使用该 signer 签发 outer token。它没有自行执行 formal WSL2/ext4、system
temp、platform-layout 同对象及返回前 fresh closure。

本轮在 actual Windows 上独立执行以下最小路径：

1. 加载一个 `PAPER_REAL_TIME` v2 config；
2. 调用 `_build_layout(config, allow_system_temp=True)`，五根位于 system temp；
3. 调用 `_probe_actual_runtime_platform(...)`，所得 proof 的 `os_name == "Windows"`；
4. 将上述 caller projection 直接传给 `_build_environment(...)`；
5. 得到 exact `VerifiedPaperRuntimeEnvironment`，且 `_verify_environment_attestation(...)` 成功。

探针输出：

```text
CALLER_MINTED_FORMAL_ENVIRONMENT_ON_UNSUPPORTED_WINDOWS_TEMP
```

因此，虽然 public verifier 会正确拒绝同一 actual Windows/system-temp 环境，普通模块调用者仍能得到带有效 package
token 的 exact formal environment。现有 `verify_existing_paper_runtime_preflight(...)` 若被显式调用会再次拒绝该对象，
但这不能修复“formal capability 本身已被通用入口签发”的来源边界；未来 consumer 仅按 exact type/token 接收时会
把绕过 actual verifier 的对象当成正式能力。

### 3.2 根因

R2 删除了通用业务 component signer，却保留了一个等价形态的“接受 caller projection 后通用 mint formal
environment”入口。下划线私有命名不是来源能力边界；这一点与 R1 对 `_attest_runtime_component` 的裁定相同。

### 3.3 违反的不变量

- 任务书 §13.1：actual 环境、路径、身份只能由 fresh verifier 证明，调用者不能自报。
- 任务书 §13.2：RUN-0A 唯一 formal capability 应是 public verifier 对 strict config、actual platform、五根 absent
  layout 和 fresh time 完成闭包后的输出。
- exact type 与有效 outer token 必须证明该对象走过 formal actual verifier，不能只证明 caller projection 被同模块 HMAC
  封装。

### 3.4 必须新增的回归测试

1. 模块不再提供接受 caller config/layout/platform/time 后可普通调用并 mint exact
   `VerifiedPaperRuntimeEnvironment` 的 `_build_environment`、`_sign_environment` 或改名等价入口。
2. 在 actual Windows 和 WSL1/DrvFS 上，普通 caller 即使持有 exact formal config、自洽 layout/platform projection，
   也不能获得带有效 attestation 的 exact formal environment；public verifier 仍必须零写入 unsupported。
3. valid environment 的签发测试必须从 public actual formal verification path 获得对象；不得再由测试辅助函数直接调用
   production generic mint。模拟 ext4 仍须明确标为纯合同，不能写成 actual 成功。
4. existing verifier 只能 fresh 调用同一 actual public path并比较稳定投影，不得用另一个 caller-projection signer重签旧对象。

### 3.5 通过条件与最小返工方向

- attestation key 保持 closure-local；formal 对象构造/签发只发生在已经完成 actual formal platform、layout、返回前
  identity 和 fresh config 检查的内部闭包中。
- 删除模块级普通可调用的 generic formal mint/signer，不以改名或另一个接受 caller projection 的 helper 保留同一能力。
- existing verifier 重新走同一 actual formal path；上述 Windows/system-temp 最小复现无法再获得有效 formal capability。
- 本裁定不要求抵抗任意 Python 内省、调试器或 monkeypatch；只要求生产模块没有普通可调用的 generic mint 入口。

## 4. 独立验证结果

### Windows Miniforge

```text
PYTHONPATH=src D:\Miniforge3\python.exe -m pytest -p no:cacheprovider tests/unit/test_paper_runtime.py -q
42 passed, 2 skipped

PYTHONPATH=src D:\Miniforge3\python.exe -m ruff check --no-cache \
  src/quant/execution/paper_runtime.py tests/unit/test_paper_runtime.py
All checks passed!

PYTHONPATH=src D:\Miniforge3\python.exe -m mypy \
  --cache-dir $env:TEMP\m4_run0a_r2_review_mypy src/quant/execution/paper_runtime.py
Success: no issues found in 1 source file
```

两个 skip 分别是当前 Windows 权限下 file symlink 不可创建，以及 frozen WSL base 纯平台合同仅在 WSL 执行。
Windows junction/reparse parent 已由本轮独立临时探针实际覆盖并拒绝。

### WSL Miniforge base，actual `/mnt/f` DrvFS

```text
PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  -p no:cacheprovider tests/unit/test_paper_runtime.py -q
44 passed

PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m ruff check --no-cache \
  src/quant/execution/paper_runtime.py tests/unit/test_paper_runtime.py
All checks passed!

PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m mypy \
  --cache-dir /tmp/m4_run0a_r2_review_mypy src/quant/execution/paper_runtime.py
Success: no issues found in 1 source file
```

### 新增对抗性探针摘要

```text
ADVERSARIAL_MISSING_ROOTS_EXACT_TYPES_HOSTILE_TRACEBACK_PASS
WINDOWS_REPARSE_PARENT_REJECT_PASS
CALLER_MINTED_FORMAL_ENVIRONMENT_ON_UNSUPPORTED_WINDOWS_TEMP
WSL_GENERATION=1 FILESYSTEM=drvfs MOUNT=/mnt/f ROOT=/
```

前两项证明补充反例通过；第三项是本轮新阻断的成功复现，不是 Gate 通过证据。

## 5. 结论

R1 的六项明确失败——万能业务 component signer、protected roots 少报、config ABA、parent TOCTOU、base 环境
伪装、nested drift——均已有与 §13 对齐的实现和双平台定向证据。代码质量 Gate 也全部绿色。

但 exact `VerifiedPaperRuntimeEnvironment` 仍可由模块级 generic builder/signer 在 actual Windows 与 system temp
条件下直接 mint 并通过 outer attestation。该问题破坏 formal capability 的来源不变量，因此本轮结论为
**FAIL，返回最小返工并再次由全新独立上下文复验**。RUN-0A 不能关闭；M4 继续保持
`WAITING_FOR_SOAK_EVIDENCE`。
