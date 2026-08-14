# M4-P8-RUN-0A R3：formal 环境唯一签发路径返工交付报告

日期：2026-08-09  
角色：R3 实现 Agent  
结论：R2 generic environment mint 阻断已关闭，完成双平台定向自测，待全新上下文独立复验

## 1. 边界

本轮只修改 RUN-0A 原白名单内生产模块、测试和本 R3 报告。R1/R2 报告保留失败历史；example v2 无需再次
改变。未修改 RUN-0B、P4-P8、包根、CLI、soak 或 scheduler；未创建、注册或启动正式 root、journal、DB、
evidence、anchor 或任务；无网络、凭据、OMS、broker 访问；未执行 `git add`/`commit`。

## 2. 阻断闭环

### 2.1 删除 generic formal mint/signer

- 删除模块级 `_build_environment`、`_sign_environment` 及等价接受 caller config/layout/platform/time 后签发
  formal capability 的入口；
- 模块运行时不存在 formal signing key、sign arbitrary payload callable 或初始化 factory 名称；只保留
  verifier-only token 检查 closure；
- `PaperRuntimeComponent*`、业务 signer、role+hex 容器继续不存在。

### 2.2 public-only closure mint

- formal key 与 exact `VerifiedPaperRuntimeEnvironment` 构造位于模块初始化创建的私有 closure；
- 唯一 formal mint 是 public `verify_paper_runtime_environment(*, config, now)`；
- 该 closure 不接受 caller 预构造的 layout/platform proof。单次调用内按顺序完成：
  1. exact formal v2 config 与 fresh file/parent identity；
  2. actual platform probe；
  3. frozen WSL base、WSL2、ext4 验证；
  4. actual project/system-temp/五 absent sibling layout；
  5. platform-layout exact parent identity；
  6. 返回前 hook 后再次 fresh config、layout、parent/platform closure；
  7. 全部成功后才计算 outer identity、token 并构造 formal exact type。
- 任一异常都发生在 token/type mint 前，公开错误离开 active `except` 后稳定脱敏。

### 2.3 existing 与 development

- existing verifier 继续 nested-first 重算 retained platform/layout/文件身份和outer token，随后 fresh 调用同一个
  `verify_paper_runtime_environment` actual path；不存在第二个 caller-projection signer；
- development verifier只返回 exact different `DevelopmentPaperRuntimeEnvironment`，layout/platform helper 单独或
  组合不产生 formal token/type；formal→development、development→formal 双向 exact-type 拒绝；
- 普通 dict、object、`object.__new__`、手工 formal dataclass + caller token 均不能通过 existing verifier。

## 3. R2 最小复现关闭

在 actual Windows/system-temp 路径上仍可只读得到 formal config、development layout helper 结果和 actual
`RuntimePlatformProof`，但：

- 模块无 `_build_environment`/`_sign_environment` 可调用；
- public formal API 返回 `PAPER_RUNTIME_PLATFORM_UNSUPPORTED`，五 leaf 零写入；
- 手工 exact dataclass 的 caller token 被 verifier-only attestation 检查拒绝为
  `PAPER_RUNTIME_PREFLIGHT_INVALID`；
- module globals 中不存在 32-byte formal key。

因此 R2 报告的 `CALLER_MINTED_FORMAL_ENVIRONMENT_ON_UNSUPPORTED_WINDOWS_TEMP` 路径已不存在。

## 4. 新增反例

- runtime/static 检查不存在 generic builder/signer/module key，也不存在接受 config+layout+platform 后返回 formal
  type 的 callable；
- Windows/system-temp R2 复现、手工 token、dict/object/new；
- WSL frozen base 上仅 monkeypatch私有 actual probe 的 WSL generation/filesystem projection，并将纯合同测试的
  temp boundary隔离后，formal happy path只经 public API mint；existing 同样 fresh走 public；
- hostile formal closure 在返回前检查阶段抛出 TOKEN/PATH/SQL/payload marker，结果固定
  `PAPER_RUNTIME_VERIFY_FAILED`，`cause/context is None`，marker不回显、leaf零写入；
- R2 config ABA、project boundary、parent TOCTOU、base伪装、全部 nested字段、whole-rehash、actual双平台拒绝和
  cold import 回归继续覆盖。

## 5. 验证证据

Windows Miniforge：

```text
PYTHONPATH=src D:\Miniforge3\python.exe -m pytest tests/unit/test_paper_runtime.py -q
19 passed, 30 skipped

PYTHONPATH=src D:\Miniforge3\python.exe -m ruff check \
  src/quant/execution/paper_runtime.py tests/unit/test_paper_runtime.py
All checks passed!

PYTHONPATH=src D:\Miniforge3\python.exe -m mypy src/quant/execution/paper_runtime.py
Success: no issues found in 1 source file
```

Windows skips中，27项是 frozen WSL base 的 public 模拟-ext4 happy path或依赖其有效 formal token 的
nested/config/whole-rehash回归；其余为 file symlink权限、base纯平台和hostile closure用例。Windows actual
unsupported、system-temp复现、invalid token、dict/object/new和零写入均实际执行通过。

WSL Miniforge base、当前 `/mnt/f` DrvFS：

```text
PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_paper_runtime.py -q
49 passed

PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m ruff check \
  src/quant/execution/paper_runtime.py tests/unit/test_paper_runtime.py
All checks passed!

PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m mypy \
  src/quant/execution/paper_runtime.py
Success: no issues found in 1 source file
```

WSL 的 49 项包含 public-only模拟ext4 happy、existing fresh public、hostile closure及全部 R2 nested回归；actual
WSL1/DrvFS formal用例仍稳定 unsupported/零写入。模拟字段不是 actual ext4 Gate 证据。

## 6. 未关闭事项

- 尚无 actual WSL2/ext4 成功证据；
- RUN-0A 不产生业务五身份、runtime manifest、runner、scheduler 或 soak evidence；
- RUN-0B1/B2、RUN-0C/D、真实 WSL2/ext4 与 28 个自然日 soak 全部开放；
- R3 需由未参与返工的全新上下文独立复验和主 Agent 终验。M4 继续保持
  `WAITING_FOR_SOAK_EVIDENCE`。
