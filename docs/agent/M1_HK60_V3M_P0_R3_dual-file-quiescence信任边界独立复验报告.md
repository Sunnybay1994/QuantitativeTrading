# M1-HK60-V3M-P0 R3 dual-file quiescence 信任边界独立复验报告

日期：2026-08-09  
角色：未参与 R3 实现的全新独立复验  
结论：**PASS；fixture-only V3M-P0 R3 在冻结信任模型下可进入主 Agent 最终验收**

## 1. 范围与隔离

本轮完整核对任务单 §12/§13、R2 FAIL 独立复验报告、R3 返工交付报告以及当前白名单
loader、CLI 和两个测试文件。生产代码与实现者测试全程只读；本报告是唯一写入。未联网，
未运行真实 plan/recovery/finalize，未读写正式 HK60 raw、clean、journal、候选目录或
`data/legacy`，未 add/commit。

结论只评价 fixture-only V3M-P0 R3 工程合同，不评价 02983/01065 provenance、formal V3M-P1、
HK60、HK 复权、WSL2/ext4 或 M1 Gate。

## 2. 合同映射

- 任务单已把上游 write-once/no-clobber retained materializer 和 caller quiescence 冻结为显式
  formal 前提；loader 只证明每个文件在各自最终 held-instance 观测点的 length/SHA、
  descriptor/handle、namespace 和物理身份未漂移。
- `load_verified_hkex_retained_bundle_for_finalize` 的公共 docstring 与 CLI 模块 docstring 均明示
  上述前提，并明示有限顺序检查不证明两个外部路径在同一共同时刻不可变。
- verifier 只接收两个 anchored open instance 的首读 exact bytes；loader 返回由这些 cached bytes
  验真的 exact bundle。CLI 只向 `finalize_hk_history` 传递 `hkex_retained_bundle`，不传 raw/
  metadata 参数，不重读外部路径。
- R2 的单文件 persistent raw/metadata drift 拒绝、held-instance 复读和 offset 恢复、物理
  identity/open-instance、hostile exception 脱敏及 legacy/no-clobber 回归均保留。
- 真 ABA 仅在 verifier 输入、held reread、返回 bundle 和最终路径 bytes 均 exact 相同时允许；
  测试和文档没有把该结果表述成“窗口内从未写入”。
- cross-file interleave 测试显式保留 R2 反例：违反 quiescence 时，最终 raw path 可与
  bundle 不同，而 bundle 仍严格是 verifier 首读内容。测试名、注释、任务和交付报告均
  把它记录为前提外的诚实边界，未声称 writer 已被技术阻止。
- 生产实现未增加锁、轮询、固定多轮 sweep、mtime/ctime、watcher、签名或 caller 自报
  boolean/capability，没有用不可满足的技术措施伪装双文件共同时刻证明。

## 3. 独立对抗增量

除实现者测试外，本轮新增一项只读的公共 API/文档反例审计：在 Windows 和 WSL 冷导入
后用 `inspect.getdoc` 检查 CLI 模块和 loader 公共 docstring，强制它们同时暴露：

1. `write-once/no-clobber` 与 caller `quiescence` 前提；
2. loader 不独立阻止外部 writer；
3. 有限检查不证明两路径在 `one common instant` 不可变。

该对抗在两平台均 PASS，同时将 `socket.create_connection` 替换为立即报错哨兵，冷导入未
触发网络。这项检查防止未来代码保留弱实现、却把公共合同重新写强。

## 4. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`（显式使当前 worktree `src` 优先）：

- 两个白名单测试文件：`132 passed, 2 skipped`；
- Ruff（2 source + 2 tests）：PASS；
- mypy（2 source）：PASS；
- cold import + 公共信任边界 docstring 独立断言：
  `WINDOWS_R3_COLD_IMPORT_AND_PUBLIC_BOUNDARY_DOC_PASS`；
- 白名单 `git diff --check`：PASS，仅有既有 LF/CRLF 提示。

WSL Miniforge `base`，同一 `/mnt/f` worktree：

- 两个白名单测试文件：`134 passed`；
- Ruff（2 source + 2 tests）：PASS；
- mypy（2 source）：PASS；
- cold import + 公共信任边界 docstring 独立断言：
  `WSL_R3_COLD_IMPORT_AND_PUBLIC_BOUNDARY_DOC_PASS`；
- 文件系统类型：`wslfs`，只构成 WSL/DrvFS 开发证据，不是 ext4 Gate。

WSL 中该 linked worktree 的 `.git` 保留 Windows 绝对指向，因此 WSL 侧 `git diff --check`本身
报“not a git repository”；同一字节工作树已由 Windows Git 完成白名单 diff 检查。该工具路径
边界不影响 WSL pytest/Ruff/mypy/cold-import 结果。pytest warning 为既有 Pandera deprecation，
不改变结论。

## 5. 最终状态

V3M-P0 R3 独立复验 PASS，可进入主 Agent 最终验收。该 PASS 只证明 fixture-only v3 CLI
在“上游 write-once/no-clobber + caller quiescence”的冻结信任模型下完成工程合同。

正式 V3M-P1 仍必须在 execution manifest 中绑定 write-once materializer 来源和执行期 quiescence。
本结论不解锁 02983 provenance materialize、01065 licensed source-freeze/verifier 或 formal V3M-P1，
也不表示 HK60、HK 复权、WSL2/ext4 或 M1 Gate 已通过。
