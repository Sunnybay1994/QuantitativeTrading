# M4-P8-RUN-0A R3：formal 环境唯一签发路径独立复验报告

日期：2026-08-09  
角色：未参与 R3 实现的全新独立复验上下文  
结论：**PASS（关闭 R2 generic formal environment mint 阻断）**

## 1. 独立性、范围与证据边界

- 复验前阅读了 `M4_P8_RUN0A_平台路径与Runtime身份任务单.md` §14、R2 FAIL 报告与 R3 返工交付报告，并按
  “标准—独立证据—结论”重新检查实现；实现者自测只作为待核证据。
- 只读检查 `src/quant/execution/paper_runtime.py`、`src/quant/execution/__init__.py`、
  `tests/unit/test_paper_runtime.py` 与 `configs/trading/paper_runtime.example.toml`；未修改生产代码、实现者测试或
  配置，未执行 `git add`/`commit`。本报告是本轮唯一仓库写入。
- 本结论只关闭 RUN-0A 的 formal 环境工程合同。RUN-0B1/B2、RUN-0C/D、正式 runtime/runner、真实
  WSL2/ext4 成功和 soak 均不在本轮范围内。
- 当前 actual 平台证据只有 Windows 与 WSL1/DrvFS；模拟 `wsl_generation=2/filesystem_type=ext4` 仅是纯合同
  测试，不是 actual WSL2/ext4 Gate 证据。

## 2. 标准—独立证据—结论

| §14 标准 | 独立证据 | 结论 |
| --- | --- | --- |
| 模块普通调用面无 generic formal builder/signer/factory/key | 运行时不存在 `_build_environment`、`_sign_environment`、`_create_formal_environment_api`、环境 attestor 容器或 32-byte 模块值；源码中一次性 initializer 创建 public mint 与 verifier-only closure 后立即删除 initializer 名称。运行时逐个函数取源码，仅 public `verify_paper_runtime_environment` 含 exact formal dataclass 构造 | 通过 |
| key 与构造仅在初始化 closure，public formal 函数是唯一 mint | `paper_runtime.py:216-281` 的 key 只由两个 closure 捕获；`verify_paper_runtime_environment(*, config, now)` 不接收 layout/platform proof；另一个 closure 只比较 token，不能签任意 payload | 通过 |
| 同一次 public 调用完成 fresh config → actual platform/frozen base/WSL2/ext4 → layout/parent closure → 返回前 fresh 检查 → mint | `paper_runtime.py:229-246` 先 exact formal config 与 fresh reload，再 actual probe/formal platform verifier、formal layout、platform-layout parent identity、return hook 后 fresh config/layout/parent；`paper_runtime.py:247-257` 只在这些检查后计算 payload/token 并构造 exact formal type | 通过 |
| helper、Windows/system-temp、伪 proof、手工 token、dict/object/`object.__new__` 不能形成有效 capability | 独立 Windows/system-temp 探针可取得 development layout 与 actual Windows platform projection，但 public formal API 稳定 `PAPER_RUNTIME_PLATFORM_UNSUPPORTED`；手工 exact dataclass + 完整 outer digest + caller token、dict、object 与 `object.__new__` 均被 existing verifier 以 `PAPER_RUNTIME_PREFLIGHT_INVALID` 拒绝，五 leaf 未创建 | 通过 |
| existing 只能 fresh 走同一 public actual path | `paper_runtime.py:349-376` 先 fresh 重算 retained platform/layout 与 token，再 reload exact config并调用模块 public `verify_paper_runtime_environment`；独立计数 wrapper 证明一次 existing 调用恰好调用一次该 public 路径，没有第二 signer | 通过 |
| development 与 formal exact 隔离 | 两类 config/result 是互不继承的 exact dataclass；双向错误类型进入对应 verifier 均稳定 `PAPER_RUNTIME_MODE_INVALID`，development 结果无 attestation 字段和 formal token | 通过 |
| R2 回归：config ABA、parent TOCTOU、伪 base、nested/whole-rehash | 双平台定向测试通过；本轮另在 public-only 模拟 ext4 路径补测返回前同 bytes config replacement、parent replacement、实现者参数化表未逐项列出的 `evidence_root`/`anchor_root`/`log_root` 与五个单独 root identity 漂移，并构造“nested platform digest + outer identity 全部重算但保留旧 token”反例，全部 fresh fail closed、零 leaf | 通过 |
| actual Windows 与 WSL1/DrvFS unsupported、零写入 | Windows 独立探针输出 `WINDOWS_RUNTIME_SURFACE_R2_REPRO_FORGERY_ZERO_WRITE_PASS`；`wsl.exe -l -v` 显示 Ubuntu VERSION 1，actual `/mnt/f` projection 为 `WSL_GENERATION=1 FILESYSTEM=drvfs MOUNT=/mnt/f ROOT=/`，public formal 探针输出 `ACTUAL_FORMAL_UNSUPPORTED_ZERO_WRITE_PASS` | 通过 |
| hostile 异常脱敏与 cold import | WSL 独立 hostile return-boundary 探针检查 `str/repr`、`cause/context` 与完整 formatted traceback，TOKEN/PATH/SQL/payload marker 均不回显且五 leaf 未创建；双平台定向 cold-import 用例通过 | 通过 |

## 3. R2 阻断关闭复核

R2 的绕过依赖普通调用方依次组合 formal config、`_build_layout(..., allow_system_temp=True)`、actual platform
projection、模块级 `_build_environment` 和 `_sign_environment`。R3 后：

1. 前两个只读 helper 仍可供 development 与测试使用，但不产生 formal token/type；
2. generic builder/signer 与初始化 factory 名称在模块运行时均不存在；
3. public formal closure 不接受 caller layout/platform，必须自行执行 actual formal 全链；
4. 手工调用公开 dataclass 构造器只能得到无有效 closure attestation 的普通对象，不能通过 existing；
5. verifier-only `_verify_environment_token` 只能比较给定 payload/token，不能生成 token。

因此 R2 的 `CALLER_MINTED_FORMAL_ENVIRONMENT_ON_UNSUPPORTED_WINDOWS_TEMP` 路径已不可复现。这里按任务书
§14.2 的边界裁定普通模块调用面，不声称抵抗任意 Python 内省、调试器、内存读取或恶意 monkeypatch。

## 4. 独立对抗性反例

### 4.1 Windows actual/system-temp

独立内存探针重新构造 R2 路径并额外使用正确 outer payload hash 的手工 formal dataclass。结果：

```text
WINDOWS_RUNTIME_SURFACE_R2_REPRO_FORGERY_ZERO_WRITE_PASS
```

这同时证明：运行时 surface 无 generic mint、actual Windows public formal unsupported、caller token 不被接受、
dict/object/未初始化 exact object 不被接受，且五 leaf 零写入。

### 4.2 WSL simulated ext4：fresh existing 与未覆盖 nested 字段

只 monkeypatch 私有 actual platform projection 与 system-temp boundary，使冻结 WSL base 执行纯合同模拟；valid
environment 仍只由 public formal API 取得。独立探针覆盖：

- existing 恰好 fresh 调用一次同一 public formal API；
- `evidence_root`、`anchor_root`、`log_root` 单字段漂移；
- 五个 `root_identities` 元素分别漂移；
- platform nested digest 与 outer verification identity 全部重算，但保留旧 attestation token；
- formal 返回前 config ABA、parent TOCTOU；
- return-boundary hostile marker 的完整 traceback 脱敏。

终态：

```text
WSL_SIM_EXT4_EXISTING_NESTED_WHOLE_REHASH_ABA_PARENT_HOSTILE_PASS
```

这只是纯合同证据，不构成 actual ext4 成功。

### 4.3 actual WSL1/DrvFS

formal config 写在 `/tmp`，五个候选 leaf 使用 `/mnt/f` 下随机且事前不存在的名称；探针只读 actual
projection，public verifier 在 layout 创建前拒绝，事后再次确认五 leaf 不存在：

```text
WSL_GENERATION=1 FILESYSTEM=drvfs ACTUAL_FORMAL_UNSUPPORTED_ZERO_WRITE_PASS
```

## 5. 双平台定向验证

### 5.1 Windows Miniforge

```text
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 D:\Miniforge3\python.exe -m pytest \
  -p no:cacheprovider tests/unit/test_paper_runtime.py -q
19 passed, 30 skipped

PYTHONPATH=src D:\Miniforge3\python.exe -m ruff check --no-cache \
  src/quant/execution/paper_runtime.py tests/unit/test_paper_runtime.py
All checks passed!

PYTHONPATH=src D:\Miniforge3\python.exe -m mypy \
  --cache-dir %TEMP%\m4_run0a_r3_independent_mypy src/quant/execution/paper_runtime.py
Success: no issues found in 1 source file
```

Windows skips 与用例平台标注一致：冻结 WSL base 的模拟 formal/nested 路径、WSL-only平台合同及 Windows
symlink 权限用例；actual Windows、R2 reproduction、caller token/dict/object/new 与零写入均实际运行。

### 5.2 WSL Miniforge base，actual `/mnt/f` DrvFS

```text
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  /home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  -p no:cacheprovider tests/unit/test_paper_runtime.py -q
49 passed

PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m ruff check --no-cache \
  src/quant/execution/paper_runtime.py tests/unit/test_paper_runtime.py
All checks passed!

PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m mypy \
  --cache-dir /tmp/m4_run0a_r3_independent_mypy src/quant/execution/paper_runtime.py
Success: no issues found in 1 source file
```

## 6. 结论与剩余边界

R3 满足任务书 §14：formal capability 的普通模块调用面只有 public actual verifier closure 能签发；generic
builder/signer 阻断已关闭；existing、development 隔离、config/layout/platform/attestation fresh closure、稳定失败
语义和双平台非 ext4 零写入均有独立证据。因此本轮结论为 **PASS，可进入主 Agent 最终验收**。

仍未关闭：actual WSL2/ext4 成功、RUN-0B1/B2、RUN-0C/D、正式 runtime root/runner/scheduler 与 28 个自然日
soak。RUN-0A 通过不创建或注册任何正式资源，M4 仍保持 `WAITING_FOR_SOAK_EVIDENCE`。
