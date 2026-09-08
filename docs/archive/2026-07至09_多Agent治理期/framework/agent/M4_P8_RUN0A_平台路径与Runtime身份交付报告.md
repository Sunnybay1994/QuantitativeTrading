# M4-P8-RUN-0A：平台、路径与 Runtime 身份交付报告

日期：2026-08-09  
角色：实现 Agent  
结论：实现与自测完成，待独立初验和主 Agent 终验

## 1. 交付边界

本轮只修改任务单白名单内四个文件：

- `src/quant/execution/paper_runtime.py`
- `tests/unit/test_paper_runtime.py`
- `configs/trading/paper_runtime.example.toml`
- 本报告

没有修改 P4-P8 已验收模块或包根导出；没有注册/启动 scheduler 或 soak；没有创建正式 runtime、broker、
evidence、anchor、log root；没有读写正式 artifacts、journal、OMS/broker DB；没有网络或凭据访问。

## 2. 实现摘要

### 2.1 Strict config 与 formal/development 隔离

- strict TOML exact-key loader，保留 raw bytes SHA-256 并纳入 canonical config identity；
- `FormalPaperRuntimeConfig` 与 `DevelopmentPaperRuntimeConfig` 为 exact different types；
- 五个绝对 sibling roots、两个相对 SQLite filename、四类 selector、project/protected roots 全部必填；
- formal selector 拒绝 development/example/fixture/unknown，未知键、URL/credential 键和路径语义 fail closed；
- example 固定为 `development-example`，不具备进入 formal verifier 的类型。

### 2.2 实际平台与只读布局

- formal public builder 不接收 caller-supplied platform boolean/Protocol，固定调用包内
  `_probe_actual_runtime_platform`；
- actual probe 绑定 OS/kernel、WSL generation、Python/Conda base、mount point/root、filesystem、device 和
  mount options；Linux 从 `/proc/self/mountinfo` 选择目标 parent 的最长匹配 mount；
- formal 只接受 Linux + WSL2 + Miniforge base + ext4 + mount root `/`；Windows、WSL1、DrvFS、未知文件系统、
  非 base 和伪 executable 均拒绝；
- layout 要求五个 leaf 不存在、同一真实 parent 下互异 sibling，拒绝 symlink/reparse、已有 leaf、不同 parent、
  protected/project/system-temp 边界和 parent identity 漂移；全过程只读。

### 2.3 五类 component 与 ephemeral preflight

- 冻结 ACCOUNT/STORE/GATEWAY/SOURCE/CONFIG exact role；
- `_attest_runtime_component` 仅接受 exact formal config，使用进程本地随机 HMAC key 对 role、identity、
  verification identity、source descriptor digest、适用 root identity 和 runtime config identity 做 content-bound
  attestation；
- proof/token 不进入 repr/equality/artifact，component/preflight 均不可 pickle；reload、复制 token、字段替换、
  whole-rehash、普通 64hex/重复或缺失 role 均 fail closed；
- STORE/GATEWAY root identity 分别绑定 runtime/broker absent-root identity；五类齐备后才可形成
  `VerifiedPaperRuntimePreflight`；development 只形成独立的 `DevelopmentPaperRuntimePreflight`；
- existing preflight 复验会 fresh 重读 config、重跑 actual platform/layout、重验五类 attestation 和闭包。

### 2.4 失败语义

公开路径使用任务单冻结的七个固定错误码。hostile reader/probe/path/component 异常均在离开 active `except`
后转换，`cause/context is None`，不回显路径、selector、TOKEN、SQL、payload 或 marker。

## 3. 对抗覆盖

定向测试覆盖：strict mode/key/credential/URL、raw bytes identity、formal/dev exact-type、五 root 零写入、不同
parent、已有 leaf、symlink（平台允许时）、parent replacement、config/layout复制、actual Windows/DrvFS formal
拒绝、hostile probe 脱敏、component exact set/root/config/content attestation、复制 token、pickle/reload、preflight
whole-rehash，以及 fresh process import 不加载 soak/reporting/backtest。

## 4. 验证证据

Windows 原生 Miniforge：

```text
PYTHONPATH=src D:\Miniforge3\python.exe -m pytest tests/unit/test_paper_runtime.py -q
16 passed, 1 skipped

PYTHONPATH=src D:\Miniforge3\python.exe -m ruff check \
  src/quant/execution/paper_runtime.py tests/unit/test_paper_runtime.py
All checks passed!

PYTHONPATH=src D:\Miniforge3\python.exe -m mypy src/quant/execution/paper_runtime.py
Success: no issues found in 1 source file
```

Windows 的 1 个 skip 是当前权限下无法创建目录 symlink；reparse fail-closed 仍由实现的 `lstat`、
`st_file_attributes` 检查覆盖。actual probe 非敏感摘要为：

```text
Windows none windows base
```

WSL Miniforge base、当前 `/mnt/f` DrvFS：

```text
PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_paper_runtime.py -q
17 passed

PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m ruff check \
  src/quant/execution/paper_runtime.py tests/unit/test_paper_runtime.py
All checks passed!

PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m mypy \
  src/quant/execution/paper_runtime.py
Success: no issues found in 1 source file
```

WSL actual probe 非敏感摘要为：

```text
Linux 1 drvfs base
```

两平台的 actual formal 测试都得到 `PAPER_RUNTIME_PLATFORM_UNSUPPORTED`，且五个配置 leaf 在调用前后均不存在。

首轮静态检查仅发现 `__reduce_ex__` 和动态 dataclass 构造的 mypy 签名问题；已以精确签名和显式构造修复，
后续双平台批次无失败。

## 5. 未关闭事项

- 当前 Windows 与 WSL1/DrvFS 只证明拒绝和开发合同；尚无 actual WSL2/ext4 成功证据；
- 本包没有 semantic component verifier、durable broker、生产装配、runner 或 scheduler；这些仍属于 RUN-0B+
  后续任务；
- 未开始 28 个自然日正式 soak，M4 状态保持 `WAITING_FOR_SOAK_EVIDENCE`；
- 本交付待全新上下文独立初验与主 Agent 最终验收，不能表述为 RUN-0A 或 M4 Gate 已通过。
