# M3 G6A R2 共享 Publication 首写前 Root 复验主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS；正式 EvaluationArtifact 的 G6A 工程合同通过主验**

## 1. 范围与失败闭环

G6A R1 的 fresh G1→G5B、独立 label、五层/四分母/八状态、IC/ICIR重算、17-input/3-output receipt、
formal/development exact-type隔离与三文件事务均已通过独立初验。唯一阻断是 POSIX 在 fresh/math 后替换
`output_root` 时，公共 `ArtifactPublication.write_stream()` 仍先调用 writer，直到 commit 才发现漂移；虽然最终
回滚双空，但违反“首个输出前同一 root实体不成立则0 bytes/0 writer”。

R2 在共享 publication 中增加两个 current-root proof：每个 exclusive open前一次；open、fstat并记录 owned
identity后、调用 writer前再一次。第二次失败关闭 descriptor，identity-aware rollback只删除本次拥有的空inode；
既有 dir-fd/Windows handle、flush/fsync/readback、commit/no-clobber合同保持不变。

## 2. 主验复核

- pre-open proof关闭 fresh/math 后、首个open前的root replacement；
- post-open/pre-writer proof关闭open后、writer前的替换；writer调用数为0；
- Windows由持有目录handle/no-share-delete阻止rename；POSIX允许rename时仍在内容写入前拒绝；
- G5A/G5B/G6A三个公共builder共用同一修复，旧R4测试已同步为write时立即失败，而非commit晚失败；
- rollback只清本次owned inode，竞争/预存/未知文件不删；错误码与cause/context脱敏不回退。

## 3. 验证证据

实现者：Windows R2定向 `5 passed`、G5A/G5B/G6A合组 `38 passed`；WSL base对应定向 `5 passed`、合组
`38 passed`；两平台 Ruff与mypy 4 source files PASS。

全新独立复验：两平台合组均 `38 passed`；额外在pre-open检查成功后、实际anchored open前替换root，WSL
G5A/G5B/G6A均 `replaced=True, writer_calls=0` 且新旧目录零retained；Windows三个builder rename均被handle
阻止；open后/writer前单项真实执行 `1 passed`，无skip。两平台 Ruff/mypy PASS。

主 Agent精选验证：

- Windows三个R2核心：`3 passed`；Ruff PASS；mypy 4 source files PASS；
- WSL base同三个核心：`3 passed`；
- diff/白名单审查：R2生产变更只在共享 `_artifact_publication.py` 两个 proof点。

warning为既有Pandera/Polars deprecation与worktree pytest cache权限提示。

## 4. 状态边界与下一步

本报告关闭G6A工程合同并解锁已冻结的G6B `ResearchSummaryArtifact` 实现。它不表示正式全work训练/评估、
真实数据性能、WSL2/ext4、G6/M3 Gate通过；当前WSL证据来自`/mnt/f` DrvFS。G6B仍须按完整fold/horizon、
fresh每折G6A、拼接后重算coverage/八状态/IC/ICIR、exact receipt与独立初验合同推进。
