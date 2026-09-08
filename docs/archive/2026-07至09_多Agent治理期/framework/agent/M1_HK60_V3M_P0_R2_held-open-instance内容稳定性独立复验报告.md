# M1-HK60-V3M-P0 R2 held open-instance 内容稳定性独立复验报告

日期：2026-08-09  
角色：未参与 R2 实现的全新独立复验  
结论：**FAIL；单文件 held-instance 复读已闭合，但 dual-file 顺序复验仍存在可观察的交错内容漂移窗口**

## 1. 范围与隔离

本轮完整核对任务单 §11、R1 FAIL 报告、R2 返工交付报告、当前 loader/anchor 实现与两个白名单测试文件。
生产代码和实现者测试保持只读，本报告是唯一新增文件。全部对抗仅在系统临时目录执行；未读取或写入正式
HK60 plan、journal、raw、clean、`data/legacy` 或正式 artifacts，未构造 connector，未发起网络请求，未
add/commit。

本结论只评价 fixture-only V3M-P0 R2 工程合同，不评价 02983/01065 provenance、formal V3M-P1、HK60、
HK 复权、ext4 或 M1 Gate。

## 2. 已通过项

- raw/metadata 首读后冻结 exact length 与 SHA-256；verifier 后从仍持有的同一 fd/handle 从 offset 0 复读到
  EOF，而非 path reopen、`Path.read_bytes()`、新 fd/handle、mtime 或 size-only 检查。
- POSIX `lseek/read` 与 Windows `SetFilePointerEx/ReadFile` 均保存并恢复原文件指针；复读前后继续证明
  original/private duplicate 属于同一 open instance，复读后继续执行 namespace 与 path physical identity
  检查。
- 实现回归中的 raw/metadata same-inode 可观察 drift 均拒绝；seek/read/restore hostile failure 被清洗为
  `HK_HISTORY_REFERENCE_INVALID`，cause/context 均为空。
- 独立大于 1 MiB 的 raw 与 metadata 对抗在 Windows 和 WSL 均通过，证明两平台 held-read 会循环读取到 EOF，
  并对 exact length/SHA 作比较，而不是只读首块。
- 独立 close 对抗先真实关闭锚内资源再抛 hostile marker；两平台均由 close 失败覆盖待返回 result，公开错误码
  固定，异常图与 traceback 不保留 marker。
- 独立真 ABA 对照同时临时改写 raw 与 metadata 后恢复 exact original bytes；两平台均确认 verifier 输入、
  held reread 摘要、返回 bundle 与最终路径字节完全相同并允许成功。该结果仅说明当前观测集合一致，**不表示
  证明窗口内从未写入**，也未被本报告当作缺陷。

## 3. 阻断问题：dual-file 顺序复验的交错漂移可逃逸

### 3.1 现象

`load_verified_hkex_retained_bundle_for_finalize` 在 verifier 返回后按 raw、metadata 顺序执行：

1. `raw_anchor.assert_live()`；
2. raw held-instance 复读并比较 length/SHA；
3. raw namespace/path identity；
4. metadata 的同一组检查。

独立对抗让 raw 的第一次 held reread 正常通过；当 loader 开始 metadata held reread 时，再通过原 raw 路径对
同一 inode/file-id 原地改写 raw，并把新字节保留到 loader 返回。Windows 与 WSL 均得到：

```text
CROSS_FILE_INTERLEAVE_ESCAPED=True
```

loader 返回 verifier 基于旧 raw 构造的 bundle，但最终 raw 路径保留新字节；即
`bundle.retained_raw != raw_path.read_bytes()`。物理 identity 没有变化，因此 raw 已完成的 namespace/path
identity 检查和随后只针对 metadata 的检查均不会拒绝。

### 3.2 根因与被破坏规则

R2 为每个文件各建立了一次正确的 held-instance 内容观测点，但把“内容摘要 + namespace/path identity”整体
放在单个循环项内。第一文件检查完成后，在第二文件检查期间不再复验第一文件内容，因此没有形成 dual-file
返回边界的闭包。

这不是 §11 明确允许的真 ABA：对抗退出时 raw 仍是新字节，返回 bundle 与最终路径存在可观察差异。它破坏
§11.1“返回时内容与传给 verifier 的 bytes 相同”和 §11.2“result 逃逸前两个文件完成内容摘要/identity”的
目标，也重现了任务单要求独立增加的 dual-file TOCTOU 反例。

### 3.3 返工要求与可满足性边界

不得用增加一次固定顺序 sweep 就宣称强闭包：任意有限次、无锁的顺序检查之后，外部 writer 仍可在最后一个
观测点之后写入另一文件。主 Agent 应先重冻一个可实现合同，明确二选一：

1. 引入跨平台、覆盖 raw+metadata 整个验证窗口的可信写入排他/世代或事件日志合同；或
2. 明确把能力定义为“各文件在其 held-instance 最终观测点与 verifier 输入一致”，并把观测点之后的外部并发写
   纳入 caller 提供的 retained-input quiescence 信任前提，不再表述为 loader 独立证明返回瞬间两路径均一致。

任务单 §11 当前禁止新增锁、写入世代和事件日志，却同时要求无外部排他条件下证明 dual-file 返回瞬间一致；
对任意并发 writer，这个强表述不可由有限次顺序 read/hash 完成。返工不能用 mtime、path reopen、固定轮数重复
hash 或调整 raw/metadata 顺序掩盖该边界。

若主 Agent 选择保留当前“verifier 内同步 mutation 后的最终复读”工程边界，则必须在 SSOT/任务合同与接口
docstring 中显式写出 caller quiescence 前提，并把本反例从实现失败改判为合同外并发；当前 §11 原文尚未这样
冻结，因此本轮按现有合同判 FAIL。

## 4. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`：

- 两个白名单测试文件：`130 passed, 2 skipped`；
- Ruff（2 source + 2 tests）：PASS；
- mypy（2 source）：PASS；
- 冷导入 audit：`R2_COLD_IMPORT_NO_NETWORK_PASS`；
- 独立大文件分块 held-read + 双文件真 ABA：PASS；
- 独立 close 失败清洗：PASS；
- 独立 dual-file 交错 raw drift：`CROSS_FILE_INTERLEAVE_ESCAPED=True`。

WSL Miniforge `base`，同一 `/mnt/f` worktree：

- 两个白名单测试文件：`132 passed`；
- Ruff（2 source + 2 tests）：PASS；
- mypy（2 source）：PASS；
- 冷导入 audit：`R2_COLD_IMPORT_NO_NETWORK_PASS`；
- 独立大文件分块 held-read + 双文件真 ABA：PASS；
- 独立 close 失败清洗：PASS；
- 独立 dual-file 交错 raw drift：`CROSS_FILE_INTERLEAVE_ESCAPED=True`；
- 文件系统类型：`wslfs`，仅是 WSL/DrvFS 开发证据，不是 ext4 Gate。

白名单 `git diff --check` PASS，仅有既有 LF/CRLF 提示。pytest warning 为既有 Pandera deprecation 与
`.pytest_cache` 权限提示，不改变结论。

## 5. 最终状态

V3M-P0 R2 不进入主 Agent 最终通过。应由主 Agent先重冻上述并发/信任边界，再进入实现—全新独立复验闭环。
在此之前，不解锁 02983 provenance materialize、01065 source-freeze/verifier 或 formal V3M-P1；本报告亦不表示
HK60、HK 复权、ext4 或 M1 Gate 已完成。
