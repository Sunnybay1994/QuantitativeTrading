# M4 P8 RUN-0B2B：Formal A股 PAPER Policy/Config Loader 独立复验报告

日期：2026-08-09  
角色：未参与实现的独立初验 Agent  
基线：`354a211a3a66e2771dd52e05bbf874b369233c1d`  
结论：**PASS（development 工程合同）**

## 1. 结论与边界

本轮逐项核对任务书、交付报告、`paper_policy.py`、formal/example 两份 TOML 和完整定向测试，未发现阻断项。
实现满足 RUN-0B2B 冻结的只读 formal A股 PAPER policy/config loader 合同，可以进入主 Agent 终验。

该结论只证明 Windows 原生与 WSL base/DrvFS 上的 development 工程合同。当前 WSL 文件系统实测为
`wslfs`，没有创建或签发真实 `VerifiedPaperRuntimeEnvironment`、runtime root、DB、journal 或正式 PAPER
运行产物；WSL2/ext4、真实 formal runtime、scheduler、soak 与 M4 Gate 均未关闭。

## 2. 合同映射

- 唯一 formal mint 位于模块私有 closure，创建函数随后删除；existing verifier 先核对 process-local
  attestation，再 fresh 调同一公开 loader 并 exact compare。模块 `__all__` exact 只有错误、capability、load、
  verify 四项；`from ... import *` 不暴露依赖 builder，也没有可供 caller 通用签名或 formal mint 的 key、signer、
  builder、factory。
- 输入要求 exact `VerifiedPaperRuntimeEnvironment` 与其 retained `FormalPaperRuntimeConfig`；签发前后均调用
  runtime 的 existing fresh verifier。selector 唯一 allowlist 为 `paper_a_share_v1`，路径只能从 verified
  project root 和 selector 派生；example/development/unknown/path selector 在读取业务文件前拒绝。
- policy 使用 anchored open-instance 读取，冻结 project/parent/file identity、单链接 regular file、长度与 SHA；
  签发前 held descriptor 复读并重验路径、父目录和 project root。symlink/reparse/hardlink、persistent drift、
  同 bytes 换 inode与旧 capability whole-rehash 均 fail closed。
- formal TOML exact 为 canonical UTF-8，classification、notice、schema/version、2026-01-01 open-ended window、
  `(SH,SZ)`、CNY、SH/SZ各一条费用、minimum notional、TradingConfig、risk、store URI 及所有版本 selector 与
  任务书一致；example 使用 `development-example` 和独立 example version，不能签 formal capability。
- 嵌套 TradingConfig、ExecutionCostSchedule 与 MoneyAmount 复用公共类型/构造器；policy identity 绑定 raw、
  environment verification identity、session、TradingConfig identity、cost identity、minimum notional、market 与
  rule/fill/fault/finality/clock 版本。失败统一为五类稳定公开错误，公开异常链和表示不泄露 hostile 内容。
- loader 无网络路径，失败不创建 runtime leaf、DB、journal、receipt、日志或缓存；冷导入未加载 broker、soak、
  LightGBM 或 Qlib。

## 3. 独立新增对抗

在 WSL base/DrvFS 中，于首次 anchored 读取后、签发前把 policy 路径原子替换为 **相同 bytes、不同 inode**：

- 旧/新 inode 实测不同；
- loader 稳定拒绝为 `PAPER_POLICY_SOURCE_INVALID`；
- runtime/broker/evidence/anchor/log leaf 均未生成；
- 同一脚本还验证 from-star 公共表面 exact 为冻结四项。

结果：`WSL_NOVEL_SAME_BYTES_INODE_AND_PUBLIC_SURFACE_PASS`。

另在 Windows 构造带环的 hostile `cause/context` 异常图并从 TradingConfig 构造点抛出；公开结果固定为
`PAPER_POLICY_SEMANTICS_INVALID`，`cause/context` 均为空，repr 无 TOKEN、路径、SQL 或 hostile marker，且零状态
写入。结果：`WINDOWS_HOSTILE_RECURSIVE_EXCEPTION_ZERO_WRITE_PASS`。

Windows 对“持有只读 descriptor 时原子替换同一路径”的直接探针由操作系统拒绝替换；这是 held-open-instance
在该平台上的额外保护，不作为 Windows Gate 或跨平台等价声明。

## 4. 独立验证证据

Windows 原生 Miniforge 3.13.13，worktree `PYTHONPATH=src`：

```text
python -m pytest tests/unit/test_paper_policy.py -q
27 passed, 1 skipped in 4.31s

python -m ruff check src/quant/execution/paper_policy.py tests/unit/test_paper_policy.py
All checks passed!

python -m mypy src/quant/execution/paper_policy.py tests/unit/test_paper_policy.py
Success: no issues found in 2 source files

cold import / forbidden module check
WINDOWS_COLD_IMPORT_PASS
```

唯一 skip 是 Windows 当前权限下 symlink 创建不可用；hardlink 与其他路径/身份对抗均已执行。首次未设置
worktree `PYTHONPATH` 的 pytest 被根工作区已安装包抢先解析而 collection error；按交付声明补充
`PYTHONPATH=src` 后得到上述有效结果，不属于实现失败。

WSL Miniforge base 3.13.13，DrvFS，worktree `PYTHONPATH=src`：

```text
python -m pytest tests/unit/test_paper_policy.py -q
28 passed in 2.57s

python -m ruff check src/quant/execution/paper_policy.py tests/unit/test_paper_policy.py
All checks passed!

python -m mypy src/quant/execution/paper_policy.py tests/unit/test_paper_policy.py
Success: no issues found in 2 source files

cold import / forbidden module check
WSL_BASE_COLD_IMPORT_PASS
```

白名单 `git diff --check` 通过。worktree 仍含大量前序既有修改、未跟踪文件及历史 pytest 临时目录；本轮只新增
本报告，未清理、暂存或提交任何文件。

## 5. 仍开放事项

- 主 Agent 尚需执行最终契约与合流验收。
- B2B 只解锁下一包 formal gateway/store/service factory 的 policy 输入；TargetLoader 仍等待 M3 G7A，
  LedgerContextProvider 仍等待 verified calendar/settlement 来源。
- 不得据此注册 scheduler、启动 soak、宣称 WSL2/ext4 或 M4 Gate 通过。
