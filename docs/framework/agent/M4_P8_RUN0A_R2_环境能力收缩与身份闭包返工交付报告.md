# M4-P8-RUN-0A R2：环境能力收缩与身份闭包返工交付报告

日期：2026-08-09  
角色：R2 实现 Agent  
结论：六项独立初验失败已返工并完成双平台定向自测，待全新上下文独立复验

## 1. 返工边界

本轮只修改 RUN-0A 白名单：

- `src/quant/execution/paper_runtime.py`
- `tests/unit/test_paper_runtime.py`
- `configs/trading/paper_runtime.example.toml`
- 本 R2 报告

R1 交付报告作为失败历史保留，不再描述当前实现。未修改 RUN-0B、P4-P8、包根、CLI、soak 或 scheduler；
未创建/注册/启动正式 runtime root、journal、DB、evidence、anchor 或任务；未访问网络、凭据、OMS 或 broker。

## 2. 六项失败闭环

### 2.1 删除万能业务 signer

- 删除 `PaperRuntimeComponentProof`、role+hex 通用容器、`_attest_runtime_component`、component key 和 formal API
  的 `components` 参数；没有改名保留等价 signer；
- RUN-0A 唯一 formal 输出收缩为 `VerifiedPaperRuntimeEnvironment`，只绑定 v2 config、actual platform、五个
  absent roots 和 fresh time；
- development 输出为 exact different `DevelopmentPaperRuntimeEnvironment`；
- ACCOUNT/STORE/GATEWAY/SOURCE/CONFIG 五类业务身份不在 RUN-0A 构造，留给 RUN-0B/C 各自 exact semantic
  verifier。

### 2.2 删除可少报 protected roots

- config v2 删除 caller-controlled `protected_roots`；该键现在属于未知键并拒绝；
- `project_root` 必须 exact 等于从当前 `paper_runtime.py` resolved 位置推导出的 actual checkout root；
- layout 无条件拒绝 actual project root 全部后代；formal 另无条件拒绝系统 temp；
- G1/M1/P8/store 外部边界不再接受 RUN-0A 字符串自报，留给后续 exact capability overlap verifier。

### 2.3 config file/parent identity 与 ABA

- schema 升级为 `paper-runtime-config-v2`，R1 v1 exact 拒绝；
- loader 使用 `O_NOFOLLOW`（平台提供时）regular file descriptor 读取；`lstat/open/fstat` 闭合 object identity，
  同时核对 size/mtime、单硬链接、symlink/reparse 和父目录 physical identity；
- 冻结 config 保留 source file identity、source parent identity、raw bytes SHA-256，并全部纳入 config identity；
- initial→preflight、initial→existing、read→return 窗口的同内容同长度不同 inode/file-id 替换均拒绝；父目录
  rename+replacement 同样拒绝。

### 2.4 platform/layout 同 parent 对象

- `RuntimePlatformProof` 新增 probe 时的 `parent_identity`；
- platform→layout、environment 返回前、existing fresh 三处均要求 platform parent identity、layout parent
  identity 和当前 parent identity 完全相同，而不只比较 device；
- 测试 hook 在两个冻结窗口实施同 device parent replacement，均 fail closed 且五 leaf 零写入。

### 2.5 frozen WSL base 闭包

- actual probe 绑定 resolved `sys.prefix`、`sys.executable` 及其 physical identities；Conda 环境变量只做附加
  一致性检查；
- formal exact 要求 `/home/mabw/miniforge3` base prefix、该 base 的 resolved `bin/python`、
  `CONDA_PREFIX` 同一 base、环境名 `base`；
- `.../envs/py312` 即使伪报 `CONDA_DEFAULT_ENV=base` 仍拒绝，executable/prefix 错配也拒绝；
- WSL base 上只 monkeypatch/private replacement ext4/WSL generation 字段的纯平台合同通过，但不构成 actual
  ext4 证据。

### 2.6 nested-first existing verifier

- environment outer attestation 直接绑定 config、layout 和 platform 的完整 canonical nested projection，不只绑定
  retained digest；
- existing verifier 顺序固定为：重算 platform nested digest与文件身份 → 重算 layout roots/parent/root identities
  并 fresh stat → 验 outer environment token → fresh 重读 config → 重跑 actual public preflight → 比较完整稳定投影；
- 对 layout parent/root/root identities/digest 和 platform OS/kernel/WSL/prefix/executable/Conda/parent/mount/fs/
  device/options/time/digest 的逐字段替换均拒绝；whole-rehash outer identity 仍缺 package environment token而拒绝；
- formal environment 与 attestation 不可 pickle，token 不进入 repr/equality/artifact。

## 3. 稳定失败与零写入

公开错误继续使用任务单冻结码。hostile reader/probe/path异常在离开 active `except` 后转换，公开
`cause/context is None`，不回显 path、selector、TOKEN、SQL、payload 或 marker。formal verifier 的所有 actual
platform/config/layout检查均为只读，Windows和WSL1/DrvFS拒绝前后五个 leaf 均不存在。

## 4. 验证证据

Windows Miniforge：

```text
PYTHONPATH=src D:\Miniforge3\python.exe -m pytest tests/unit/test_paper_runtime.py -q
42 passed, 2 skipped

PYTHONPATH=src D:\Miniforge3\python.exe -m ruff check \
  src/quant/execution/paper_runtime.py tests/unit/test_paper_runtime.py
All checks passed!

PYTHONPATH=src D:\Miniforge3\python.exe -m mypy src/quant/execution/paper_runtime.py
Success: no issues found in 1 source file
```

两个 Windows skip 仅为当前权限不允许创建 file symlink，以及 frozen WSL base 纯平台用例只在 WSL 运行。

WSL Miniforge base、当前 `/mnt/f` DrvFS：

```text
PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_paper_runtime.py -q
44 passed

PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m ruff check \
  src/quant/execution/paper_runtime.py tests/unit/test_paper_runtime.py
All checks passed!

PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m mypy \
  src/quant/execution/paper_runtime.py
Success: no issues found in 1 source file
```

首轮 R2 Windows 定向结果为 21 passed、1 skipped、1 failed；唯一失败是返回前 parent replacement 已正确
拒绝为 `PAPER_RUNTIME_LAYOUT_INVALID`，测试误期望 `PAPER_RUNTIME_PREFLIGHT_INVALID`。修正测试码后，后续
扩充批次均全绿。

## 5. 仍开放事项

- 当前 actual Windows 和 WSL1/DrvFS 继续返回 `PAPER_RUNTIME_PLATFORM_UNSUPPORTED`；尚无 actual WSL2/ext4
  成功证据；
- RUN-0A 不产生五类业务身份、runtime manifest、runner、scheduler 或 soak evidence；
- RUN-0B1 durable broker、RUN-0B2 production loader/risk、RUN-0C schedule、RUN-0D runner、真实 WSL2/ext4
  与 28 个自然日 soak 全部开放；
- R2 需由未参与返工的全新上下文独立复验和主 Agent 终验。M4 仍为
  `WAITING_FOR_SOAK_EVIDENCE`。
