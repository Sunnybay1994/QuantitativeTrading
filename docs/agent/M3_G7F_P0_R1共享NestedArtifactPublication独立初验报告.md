# M3 G7F-P0 R1 共享 Nested ArtifactPublication 独立初验报告

日期：2026-08-10
角色：未参与设计与实现的全新独立初验 Agent
结论：**PASS；仅解锁主 Agent 最终验收。P0 主验 PASS 前仍不得实施 G7F。**

## 1. 审查范围与边界

本轮完整核对了项目规则、冻结任务书、实现交付报告、
`src/quant/research/m3/_artifact_publication.py`、新增 nested 测试，以及 G5A、G5B、G6A、G6B、G7A、G7B
既有 flat 客户端及其正式 artifact 回归。生产代码、实现者测试、任务书与既有报告均保持只读；本报告是唯一
写入文件。未联网，未读取真实数据或凭据，未执行 `git add/commit/push`，未清理工作树已有文件。

受验快照 SHA256：

- `_artifact_publication.py`：`1F3F6904C12BCA9FB3CF1B776B1C3C3C9477666E169356D6C98049FFCFBC508B`；
- `test_m3_nested_artifact_publication.py`：`38778718A827A3D45EB1AECCDB639ED6A3D326BD6D84818797DEB2B743686B53`。

## 2. 契约映射结论

### 2.1 canonical path 与 flat 兼容

- public 类名及 `write_bytes`、`write_stream`、`read_bytes`、`sha256`、`commit` 签名未改变；既有 flat 客户端
  继续只传 basename，没有修改上游 client 来迁就 helper；
- parser 只接受 exact `str` 的一层 file 或两层 `directory/file`，组件长度、总长度、ASCII 字符集、`.`、`..`、
  空段、重复 slash、绝对/drive/UNC、反斜杠、colon、NUL、尾点、lease 名和 Windows device name 均
  fail-closed；
- write 与 expected set 使用同一 parser；exact duplicate、全路径 casefold alias、sibling child alias、root file 与
  nested parent 冲突均在新输出产生前拒绝；
- 独立补测了 Unicode component、`a/./b`、`a/../b`、三层路径、设备名扩展以及恰好 257 字符的合法上界；
  非法项均留下 exact empty root，合法上界可写、读并 exact commit。

### 2.2 root、child、file 锚定和 no-clobber

- 进入事务先验证 caller-created exact empty real root 及全部祖先；同进程 registry 与 exclusive lease 共同阻止
  第二 owner；
- POSIX 分支要求并实际持有 root/child dir-fd，child 使用 `O_DIRECTORY|O_NOFOLLOW`，leaf read 使用
  `O_NOFOLLOW`；Windows root/child handle 使用不共享 delete 的目录句柄并核对 volume/file-index/reparse
  identity；
- child 仅能由 exclusive mkdir 成为本事务 owned directory；root、child 与 leaf 在 open、writer、readback、
  commit 相关窗口重复复验，leaf 要求 regular、非 link/reparse、link count 为 1 且物理 identity 不漂移；
- Windows 独立探针确认持有 root handle 时真实 rename 被操作系统拒绝，nested 正向写入实际经过 root/child
  `FlushFileBuffers`；WSL/DrvFS 探针确认 root/child dir-fd 存在，root rename 同样被底层拒绝；另以 leaf
  symlink replacement 验证 `O_NOFOLLOW`/identity fail-closed。

### 2.3 同步、whole-root commit 与 rollback 所有权

- writer 后执行 flush + file fsync，root file 同步 root，nested file 同步 child；commit 先验证 owned set、derived
  child set、root exact entries、每个 child exact entries 与全部 identity，再同步全部 child、identity-aware 删除
  lease、同步 root，并进行无 lease 的第二次 exact-tree/identity 复验；
- 独立补测额外 root directory：commit 拒绝，rollback 删除自身 leaf/child 但保留 foreign directory，并以
  `ArtifactRollbackError` 如实报告不能证明 root exact empty；
- 独立补测同字节 leaf replacement：`read_bytes` 拒绝 replacement，rollback 不删除竞争者 replacement 或被移走
  的原 owned inode，并返回脱敏 `ArtifactRollbackError`；
- 代码不存在 `rmtree`、glob delete、递归清空或删除 caller root；回滚严格按 owned file 逆序、child anchor 逆序、
  owned child、lease、root anchor 顺序进行，并在 identity、空目录或同步无法证明时保留对象并报错；
- 实现测试已覆盖同 root 两线程/两进程 lease 竞争、预存 child/leaf、child link/junction、hard link、foreign child
  entry、child replacement、unlink/rmdir/fsync/readback failure，以及 3 child + 29 file whole-root exact commit。
  同 child/同 leaf/不同 leaf 的跨事务竞争都先受同一 root owner 契约阻断，不存在第二事务覆盖窗口。

### 2.4 失败窗口与脱敏

- open 后、writer 前的 root/child 复验失败时 writer 调用次数为零；writer、file fsync、child/root directory sync、
  readback、commit 和 rollback primitive 失败都由既有测试或独立注入覆盖；
- 独立注入 file fsync 失败后确认事务可 exact rollback 至空 root；
- 独立构造三层 `KeyError -> ValueError -> RuntimeError` hostile graph，public exception 的 message、cause、context
  均为空，私有 marker 不出现在 `repr`；rollback error 同样无 message/cause/context；
- partial mkdir/open 后若还不能取得或证明 identity，代码不会按名称盲删，而是保留无法证明 owned 的对象并把
  exact rollback 失败升级为 `ArtifactRollbackError`，符合 fail-closed 所有权原则。

## 3. 独立验证结果

Windows Miniforge：

- nested 定向：`45 passed`，12.17 秒；
- G5A-G7B flat 六组回归：`54 passed`，831.72 秒；
- 合计明确终态：`99 passed`；首次合并运行仅因命令承载层 600 秒超时丢失输出，确认唯一 pytest 进程仍活且
  自然退出后才拆分取证，没有并发重启；
- Ruff：PASS；mypy：`Success: no issues found in 1 source file`；cold import：PASS；
- 独立 canonical、257 长度、root no-share-delete、同字节 replacement、file fsync failure、foreign directory、
  recursive exception graph 探针：`INDEPENDENT_WINDOWS_ATTACKS_PASS`。

WSL Miniforge base（同一 `/mnt/f` DrvFS 工作树）：

- nested + flat：`99 passed`，382.12 秒；
- Ruff：PASS；mypy：`Success: no issues found in 1 source file`；cold import：PASS；
- 独立 root/child dir-fd、root replacement blocked-or-detected、leaf symlink replacement 与 owned-only preservation
  探针：`INDEPENDENT_POSIX_ATTACKS_PASS`。

补充说明：第一次 WSL 独立探针未进入 Python，原因是 Windows 到 WSL 的 `-c` 引号传递失败；第二次进入
代码后发现 WSL1/底层挂载在持有目录 fd 时直接拒绝 root rename，原探针错误地只接受 rename 成功后的身份
拒绝。修正探针使“操作系统直接阻止 rename”和“rename 成功但 helper 检测 replacement”均为合格分支后通过。
这两次均不是产品缺陷，且没有改动仓库文件。两平台仅出现既有 Pandera deprecation 与无法创建
`.pytest_cache` warning。scoped trailing-whitespace 检查通过。

## 4. 独立初验结论与剩余风险

未发现需要返工的契约、所有权、并发、脱敏或 flat 兼容缺陷。G7F-P0 R1 独立初验 **PASS**，可进入主
Agent 最终验收。

剩余边界必须保持：

- 工作树和 WSL `/tmp` 均由 WSL1/Windows 文件系统语义承载；本轮没有真实 Linux ext4 证据，不能把
  DrvFS/POSIX 分支绿测表述为 ext4 Gate；
- 本报告只验收共享 nested publication primitive，不验收 G7F 三场景业务、正式 artifact、receipt、
  StageRunner、G7、M3 或 M4；
- 初验 PASS 只解锁主验。只有主 Agent 明确 P0 最终 PASS 后，才能开始 G7F 实现。
