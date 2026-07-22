# M3 G1-P4C 主 Agent 最终验收报告

日期：2026-07-15  
结论：**P4C 子包通过主验；B4/G1/M3/Gate 均未关闭**

## 1. 验收链

- 冻结任务：[`M3_G1_P4C不可变发布外部闭环任务单.md`](M3_G1_P4C不可变发布外部闭环任务单.md)
- 首轮实现：[`M3_G1_P4C不可变发布交付报告.md`](M3_G1_P4C不可变发布交付报告.md)
- 首轮独立初验：[`M3_G1_P4C不可变发布独立初验报告.md`](M3_G1_P4C不可变发布独立初验报告.md)
- P0 返工：[`M3_G1_P4C独立初验一次返工任务单.md`](M3_G1_P4C独立初验一次返工任务单.md)
- 返工实现：[`M3_G1_P4C独立初验一次返工交付报告.md`](M3_G1_P4C独立初验一次返工交付报告.md)
- 全新独立复验：[`M3_G1_P4C独立初验一次返工独立复验报告.md`](M3_G1_P4C独立初验一次返工独立复验报告.md)

## 2. 阻塞问题与关闭

首轮独立初验发现 P0：`verify_g1_release` 只在入口检查祖先 symlink，结束只复核 release root 和 entry inode；
祖先在验证中途移动并以 symlink 重绑时，仍可成功返回 verified 对象。

返工后，verifier 在读 artifact 前对 `root.parent` 到文件系统根的每一级文本绝对路径记录
`(st_dev, st_ino)`，入口 symlink/非目录失败保持 `G1_RELEASE_PATH_INVALID`；成功返回前在 root/entry 终验
之后复核全部祖先，任何 symlink、真实目录 inode 漂移或缺失统一脱敏为 `G1_RELEASE_VERIFY_FAILED`。

独立复验用三个不同 hook 覆盖父目录 symlink、真实目录 inode 漂移和 grandparent 漂移，9 项均通过。

## 3. 主 Agent 验证

主 Agent 增加一支未进入正式测试的“最晚门禁”反例：在
`_assert_ancestor_identities_unchanged` 被调用前一刻移动 grandparent 并以 symlink 重绑。公开
`verify_g1_release` 稳定拒绝，错误码、`__cause__` 和路径脱敏均符合合同；临时测试随后删除。

验证结果：

```text
主 Agent 隐藏 grandparent/latest-gate 对抗     1 passed
全量 pytest                                  798 passed
Ruff src/tests                               All checks passed
mypy src                                     79 source files, 0 issues
```

代码审查同时确认生产路径无 `os.rename`、`os.replace` 或 syscall-number fallback；P4C 仍从原始输入重建
P4A/P4B、严格验真 17 artifact/18 entry、primary/release identity 和 quality/summary/detail 闭包。

## 4. 限制与非阻塞观察

- 当前宿主是 WSL1，目录 `renameat2(RENAME_NOREPLACE)` 返回 `EINVAL`；已验证 production fail-closed 和无
  fallback，**未**验证支持内核上的真实原子 commit 成功路径；
- 未做真实 BaoStock reference smoke，也未以完整 CSI300 PIT 数据发布真实 G1 release；
- 原初验记录的 `_O_NOFOLLOW` 缺失平台细化、更多 post-rename fsync/cleanup 正式用例属于 P2，暂不阻塞主链。

因此本报告只接受 P4C 代码合同子包，不能据此关闭 B4、G1、M3 或任何 Gate，也不能把测试注入的 no-clobber
实现当作真实生产 commit 证据。
