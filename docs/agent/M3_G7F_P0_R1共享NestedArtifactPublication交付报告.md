# M3 G7F-P0 R1 共享 Nested ArtifactPublication 交付报告

日期：2026-08-10
角色：实现 Agent
状态：**实现与双平台自测完成；待全新独立初验。P0 主验 PASS 前 G7F 禁止实现。**

## 1. 交付结论

按冻结任务书把共享 `ArtifactPublication` 从 flat basename 扩展为最大两个 component 的 canonical POSIX
relative path，同时保留原类名、五个 public 方法签名和既有 flat client 调用方式。事务现在可在一个 caller-created
empty root 内共同拥有 root files 与一层 child directories/files，并对 whole root 执行 exact-tree commit 与
identity-aware owned-only rollback。

本轮只实现共享 publication primitive，不实现 G7F 三场景业务、指标、Parquet、manifest、receipt 或
StageRunner，也未修改任何 G5A-G7B flat client、G7E simulator/test、G7F production、正式 artifact 或配置。

## 2. 实现内容

### 2.1 Canonical path 与兼容边界

- `file` 与 `directory/file` 是唯一允许形态；不公开 `mkdir`，不接受空目录或第三层；
- component 与总长度、ASCII 字符集、`.`/`..`、lease、Windows device name、absolute/drive/UNC、反斜杠、
  colon、NUL、重复 slash、尾点和非 canonical 表示均 fail-closed；
- write 与 `expected_names` 使用同一 parser；exact duplicate、casefold alias、file/directory alias、root file 与
  nested parent 冲突均在新输出创建前拒绝；
- flat basename 仍走原 root `_open_output/_stat_entry/_unlink_entry` 路径，既有私有 monkeypatch 签名保持兼容。

### 2.2 Root/child/file 锚与 no-clobber

- 进入事务和每次 root 复验都检查 ancestor/root 无 symlink、junction 或 reparse；
- POSIX 保留 root dir-fd，并为 child 使用 `O_DIRECTORY|O_NOFOLLOW` dir-fd；nested leaf 通过 child dir-fd
  exclusive open/read；
- Windows root/child 均使用 no-share-delete、open-reparse-point directory handle，按 volume/file-index 与 reparse
  attribute 复验；leaf 保持 exclusive create；
- child 只能由第一次 nested write exclusive `mkdir` 后成为 owned；预存/竞争/link/reparse child 不接管；
- file open 后立即记录 identity，在 writer 前、writer 后、readback 与 commit 重验 root/child/file；regular file
  且 link count 必须为 1，新增 hard-link 会使读取、commit 和 rollback fail-closed；
- `read_bytes/sha256` 只读取本事务 owned identity，POSIX read 额外使用 `O_NOFOLLOW`。

### 2.3 每层同步与 whole-root commit

- writer 后执行 flush + file fsync；root file 同步 root directory，nested file 同步 child directory；
- POSIX directory sync 使用 dir-fd `fsync`；
- Windows 初始探针确认仅 `FILE_LIST_DIRECTORY` 的 handle 调 `FlushFileBuffers` 返回 error 5；加入
  `GENERIC_WRITE` 后 root/child 临时目录均实际 flush 成功，因此最终实现使用
  `GENERIC_WRITE|FILE_LIST_DIRECTORY` handle，并在每个目录同步点调用 `FlushFileBuffers`，没有保留 no-op；
- commit 先验证 expected paths、owned files/children、root entries、各 child entries 与全部物理 identity；所有
  child 先同步，再 identity-aware 移除 lease、同步 root，并做无 lease 的第二次 exact-tree/identity 复验；关闭
  child/root anchors 后才标记 committed。

### 2.4 Owned-only rollback 与脱敏

- files 按写入逆序复验 parent 与 inode/file-index，仅删除仍为原 owned identity 且 link count 为 1 的 leaf；
- 每次 leaf 删除后同步对应 parent；随后逆序关闭 child anchors，只对仍为原 identity 且 exact empty 的 owned
  child 执行 `rmdir`，再同步 root；lease 最后删除；
- replacement、foreign entry、hard-link、unlink/rmdir/fsync 或 anchor close 失败均保留无法证明 owned 的对象并
  返回 `ArtifactRollbackError`；未使用 `rmtree`、glob delete、名称盲删或 root 删除；
- public helper 的 publication/rollback errors 均为空 message，显式清空 cause/context；hostile exception graph、
  path、token、SQL 与 writer marker 不透出。

## 3. 新增测试

`test_m3_nested_artifact_publication.py` 当前 45 项，覆盖：

- root + 三个 child + 29 files 的乱序写入、readback、sha256 与 exact commit；
- 全部冻结 invalid path 类别、duplicate/case alias、file/dir collision 与 wrong expected tree；
- 预存 child/leaf、child symlink 或 junction、hard-link、foreign child entry；
- open 后/writer 前 root 复验与 writer 零调用；nested writer、fsync、readback failure；
- owned file/child replacement，unlink/rmdir failure 与 foreign-object preservation；
- 同 root 两线程、两进程竞争，第二事务不能进入或覆盖；
- nested hostile 异常脱敏以及 flat+nested 顺序无关。

## 4. 验证证据

最终源码快照，Windows Miniforge：

- nested + G5A/G5B/G6A/G6B/G7A/G7B flat 指定回归：`99 passed`；
- 其中 nested 定向：`45 passed`，既有 flat：54 项；
- Ruff：PASS；mypy：`Success: no issues found in 1 source file`；cold import：PASS；
- Windows mypy 一次使用工作树默认 SQLite cache 时出现工具自身 `sqlite3.OperationalError: disk I/O error`，未
  记作通过；改用一次性系统临时 cache 后明确 PASS。

最终源码快照，WSL Miniforge `base`：

- 同一 nested + flat 指定回归：`99 passed`；
- Ruff：PASS；mypy：`Success: no issues found in 1 source file`；cold import：PASS。

两平台仅有既有 Pandera deprecation 和受限 `.pytest_cache` warning。scoped trailing-whitespace 检查通过。
工作树位于 `/mnt/f` DrvFS，WSL 绿色只证明该映射路径上的 base 环境兼容，不声明 Linux/ext4 Gate。

## 5. 修改范围

- `src/quant/research/m3/_artifact_publication.py`：受限 nested path、child anchors、whole-tree commit、rollback；
- `tests/unit/test_m3_nested_artifact_publication.py`：P0 定向与 hostile 测试；
- 本交付报告；
- `M3_G7F_P0_R1共享NestedArtifactPublication任务单.md` 仅按主 Agent 明确要求同步状态行至“待全新独立初验”。

共享工作树已有大量其他里程碑未提交改动；本轮未清理、覆盖或声明拥有这些改动。未联网、未读取真实数据或
凭据、未 add/commit/push。

## 6. 剩余边界

- 当前是实现者自测，不替代全新独立初验或主 Agent 最终验收；
- P0 主验明确 PASS 前不得实现 G7F；
- 未在真实 Linux ext4 上验证 directory durability、rename/replacement 和 process concurrency；DrvFS 结果不能
  替代该 Gate；
- P0 只证明共享 primitive，不能表述为 G7F、G7、M3 或正式发布 Gate PASS。
