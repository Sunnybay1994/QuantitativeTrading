# M4 P8 RUN-0B2C：Formal Broker Policy Binding 独立复验报告

日期：2026-08-09  
角色：未参与实现的独立初验者  
结论：**PASS（仅 development 工程前置）**

## 1. 复验边界

本轮只读核对任务单、交付报告、`paper_broker_binding.py`、实现测试以及 RUN-0A / RUN-0B2B 两个真实上游
existing verifier。生产代码和实现测试均未修改；本文件是唯一新增文件。未创建或打开 formal root、broker DB、
gateway、account、scheduler 或 soak，未联网，未暂存或提交。

该结论只证明 formal runtime capability 与 formal A 股 PAPER policy capability 的进程内 development 绑定合同成立，
不表示 formal PAPER broker 已装配或 M4 Gate 已关闭。

## 2. 契约核对

- RUN-0A `verify_existing_paper_runtime_preflight(...) -> None` 被按命令式 verifier 使用：成功后继续使用原 exact
  environment，没有虚构 capability 返回值。
- RUN-0B2B `verify_existing_paper_execution_policy(...) -> VerifiedPaperExecutionPolicy` 的返回值必须 exact type 且
  exact-equal 于调用方传入 policy；不同 capability 被拒绝。
- bind 顺序为 exact 输入/UTC、runtime fresh、policy fresh、时间下界、canonical payload、私有 closure mint；任何
  verifier 失败均无返回结果，公开异常链被 `from None` 清空。
- binding identity 与 process-local attestation 都覆盖 schema/classification、session、runtime/environment/config、
  policy/cost、五类 policy version、FX None 和 verified_at；existing 先验 exact type/token，再 fresh 两个上游，重建
  并 exact compare。
- exact type、不可 pickle、clone/subclass/dict/duck/object-new/reload old token、cross capability、session/nested drift、
  whole-file rehash 与 same-bytes inode replacement均有直接或上游合同覆盖。
- `__all__` exact 四项；closure 创建器已删除，模块无公开 generic mint/signer/key/builder/factory。
- 模块自身没有文件、SQLite、socket、日志、墙钟或网络 I/O；fresh verifier 所需的正式文件检查仍属于上游 verifier
  的明确职责。

## 3. 独立新增对抗（未落盘）

独立内存探针额外验证了实现测试未同时组合的适配边界：

1. runtime void verifier 被以原 exact environment、`environment.config.source_path` 和 exact `now` 调用；即使 hostile
   stub 返回另一个对象，返回值也不会成为绑定输入，binding 仍只读取原 fresh-checked environment。
2. runtime verifier 抛出带 `TOKEN hostile` 的异常时，policy verifier未被调用、零 result，稳定映射为
   `PAPER_BROKER_BINDING_ENVIRONMENT_INVALID`，cause/context均为空。
3. policy verifier返回另一 `VerifiedPaperExecutionPolicy` 时，即便类型正确也得到
   `PAPER_BROKER_BINDING_POLICY_INVALID`，没有生成 binding。

结果：`RUN0B2C_INDEPENDENT_ADVERSARIAL_PASS`。

## 4. 验证结果

Windows 原生 Miniforge，在隔离 worktree根目录运行：

```text
python -m pytest tests/unit/test_paper_broker_binding.py tests/unit/test_paper_policy.py -q
40 passed, 1 skipped in 7.94s

python -m pytest tests/unit/test_paper_runtime.py -q --basetemp=%TEMP%\quant-run0b2c-review-win2
19 passed, 30 skipped in 5.67s

python -m ruff check src/quant/execution/paper_broker_binding.py tests/unit/test_paper_broker_binding.py
All checks passed!

python -m mypy src/quant/execution/paper_broker_binding.py tests/unit/test_paper_broker_binding.py
Success: no issues found in 2 source files
```

第一次从仓库根目录以绝对测试路径调用时，测试内有意设置的相对 `PYTHONPATH=src` 指向了错误源码树，导致两个
cold-import用例 `ModuleNotFoundError`；从隔离 worktree根目录重跑后全部通过。这是复验调用目录错误，不是产品
失败，也未据此修改测试。

WSL Miniforge `base`，隔离 worktree位于 `/mnt/f`：

```text
python -m pytest tests/unit/test_paper_broker_binding.py tests/unit/test_paper_policy.py \
  tests/unit/test_paper_runtime.py -q --basetemp=/tmp/quant-run0b2c-review-wsl
90 passed in 8.35s

python -m ruff check src/quant/execution/paper_broker_binding.py tests/unit/test_paper_broker_binding.py
All checks passed!

python -m mypy src/quant/execution/paper_broker_binding.py tests/unit/test_paper_broker_binding.py
Success: no issues found in 2 source files

cold import probe
PASS

stat -f -c %T .
wslfs
```

## 5. 最终判断与剩余边界

RUN-0B2C 独立初验通过，可进入主 Agent 最终验收。当前 WSL 文件系统是 `wslfs`/DrvFS，不是 ext4；双平台绿测
只证明 development 工程合同和兼容性，不关闭 Linux/ext4 Gate。后续仍须按冻结顺序先建立 formal PAPER account
SSOT/loader，再做 formal store initializer/opener 与 durable gateway factory/snapshot port；本包没有提前创建这些
对象，也没有形成可运行的 formal broker。
