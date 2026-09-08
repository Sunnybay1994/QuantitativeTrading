# M3 G7F-P0 R1：共享 Nested ArtifactPublication 主 Agent 最终验收报告

日期：2026-08-10  
结论：**PASS；允许实施 G7F；不等于 G7F、ext4 或 M3 Gate。**

## 验收结论

P0 将共享 `ArtifactPublication` 从 flat basename 最小扩展为最多两个 canonical path component，同时保持类名
和五个 public 方法签名不变。实现闭合 root/child/file 物理身份、exclusive/no-clobber、writer 前后复验、
whole-root exact-tree commit、每层同步与 owned-only 逆序 rollback；Windows 使用可写 no-share-delete 目录句柄并
真实调用 `FlushFileBuffers`，POSIX 使用 dir-fd、`O_NOFOLLOW` 与 directory fsync。

全新独立初验补测 canonical/257 长度、Windows device、same-bytes replacement、root no-share-delete、file
fsync failure、foreign directory、递归 hostile exception graph，以及 POSIX root/child dir-fd、replacement
blocked-or-detected、leaf symlink；均 PASS。Windows nested `45 passed` + flat `54 passed`，WSL base 合并
`99 passed`；双平台 Ruff、mypy、cold import、diff-check 均 PASS。

主 Agent 对最终 revision 重跑 nested 核心：Windows `45 passed`，WSL base `45 passed`；双平台 Ruff、mypy
PASS。flat 兼容不机械重复独立初验中耗时约14分钟的54项，但结合实现与独立复验两轮99项终态，已充分覆盖
G5A/G5B/G6A/G6B/G7A/G7B既有客户端。当前 SHA-256：

- `_artifact_publication.py`：`1F3F6904C12BCA9FB3CF1B776B1C3C3C9477666E169356D6C98049FFCFBC508B`
- `test_m3_nested_artifact_publication.py`：`38778718A827A3D45EB1AECCDB639ED6A3D326BD6D84818797DEB2B743686B53`

WSL路径仍为`/mnt/f`/DrvFS，未验证真实ext4 durability。未联网、未add/commit、未触正式artifact。
