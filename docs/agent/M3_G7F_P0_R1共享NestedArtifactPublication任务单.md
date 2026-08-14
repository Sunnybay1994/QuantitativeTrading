# M3 G7F-P0 R1：共享 Nested ArtifactPublication 任务单

日期：2026-08-10
状态：**R1 实现、全新独立初验与主 Agent 最终验收 PASS；允许实施 G7F**
环境：Windows 原生 Miniforge 定向反馈；WSL Miniforge `base` 双平台验证；默认不联网、不读取真实数据

## 1. 根因、目标与前置

G7F 的固定布局是一个 root 下三个 scenario 子目录，每个子目录九个文件，root 另有两个文件。现有共享
`ArtifactPublication` 只允许单层 basename：`Path(name).name == name`；它不能创建/锚定子目录，也不能把
`scenario/file` 纳入一次 exact-tree commit。分别提交三个子目录会在后续失败时留下已提交 partial tree，改成
flat layout 又违反 G7 SSOT。

本包只对已主验的共享 publication primitive 做最小、向后兼容扩展：允许一个事务拥有 root 文件以及受限的
一层子目录/二层文件，并在整个 root 上保持 anchored、exclusive、no-clobber、exact commit 和 owned-only
rollback。它不实现 G7F 业务、指标、Parquet、manifest、receipt 或 StageRunner。

权威来源：

- [`_artifact_publication.py`](../../src/quant/research/m3/_artifact_publication.py) 当前 anchored transaction；
- [G6A R2 shared publication 主验](M3_G6A_R2共享Publication首写前Root复验主Agent最终验收报告.md)；
- [G7 分包骨架 §9/§9.1](M3_G7目标到账户回测分包骨架与外部闭环任务单.md)；
- 根目录 `AGENTS.md` 的职责分离、双平台和不可变发布规则。

## 2. Public surface 与兼容边界

保持现有类与方法名不变：

```python
class ArtifactPublication:
    def write_bytes(self, name: str, raw: bytes) -> None: ...
    def write_stream(
        self, name: str, writer: Callable[[BinaryIO], object]
    ) -> None: ...
    def read_bytes(self, name: str) -> bytes: ...
    def sha256(self, name: str) -> str: ...
    def commit(self, expected_names: Collection[str]) -> None: ...
```

`name` 从“仅 basename”扩展为受限 canonical POSIX relative path。最大深度冻结为 **2 个 component**：

- `file`：现有 flat client；
- `directory/file`：G7F nested client；
- 不公开 `mkdir`；子目录只能由第一次写入 `directory/file` 时事务内部创建并拥有；
- 禁止深度 0、深度 >2、目录作为 expected output、空目录或目录下再嵌套目录。

所有既有 flat 调用的字节、异常类型、root lease、commit 与 rollback 行为必须不变。不得新增依赖，不改变所有
上游 stage 的 public API。

## 3. Canonical relative-path 合同

`name` 必须是 exact `str`，使用 `/` 分隔，原字符串即 canonical 表示。每个 component：

- 非空，长度 `1..128`，整条路径长度不超过 257；
- 只允许 ASCII `[A-Za-z0-9][A-Za-z0-9._-]*`；
- 不得是 `.`、`..`、root lease 名或 Windows 保留设备名（大小写不敏感，含带扩展形式）；
- 不得含 `\\`、`:`、NUL、drive、UNC、绝对路径、前后空格、尾点、重复 `/`、空段或编码/规范化别名；
- 用 `casefold()` 后的 path key 与 sibling directory key 必须唯一，跨 Windows/Linux 均拒绝大小写 alias；
- file 与 directory 不能同名碰撞；同一事务中 root `x` 与 nested parent `x/...` 冲突必须拒绝。

`expected_names` 中每个值执行同一 strict parser；集合迭代顺序不影响结果。任何 invalid/duplicate/case alias 在创建
新输出前失败。

## 4. Anchored root 与 owned child directory

进入事务继续要求 caller 已创建的 exact empty real directory：root/祖先不得 symlink、junction/reparse；同进程
registry 与 root lease 防止并发 publication；POSIX 保持 root dir-fd + `O_NOFOLLOW`，Windows 保持无 share-delete
directory handle 与 file-index/reparse identity。

首次写 `directory/file` 时：

1. 在任何 mkdir/open 前复验 current root identity；
2. exclusive 创建 child directory；预存目录、文件、link、junction/reparse 均不得接管；
3. 立即记录 child 的物理 identity；POSIX 打开 `O_DIRECTORY|O_NOFOLLOW` child dir-fd，Windows 打开对应
   no-share-delete directory handle 并拒绝 reparse；
4. 将 child 记为本事务 owned directory；创建后 fsync root；
5. 每次 child file open 前、exclusive open 后/writer 前、writer 后、readback 与 commit 前均重验 root 与 child
   identity；child 被 rename/replaced/aliased 时 fail-closed。

不得用字符串 `resolve()` 后再无锚写入，不得从 root 枚举名称后交给另一 shell/进程操作。所有 path traversal 均由
已锚定 root/child handle 或等价的受控 Windows handle 身份完成。

## 5. Exclusive write、readback 与 no-clobber

- root file 与 child file 都使用 exclusive create；预存同名、并发抢占、hard-link/symlink/reparse leaf 均拒绝；
- open 成功后立即记录 file identity，再复验 root/parent identity，之后才允许调用 writer；
- writer 写入后 flush + file fsync；child file 还要 fsync child directory；root file fsync root directory；
- `read_bytes/sha256` 只允许读取本事务已拥有且 identity 未漂移的文件；nested read 必须复验 child identity；
- writer/flush/fsync/readback 任一步失败进入事务 rollback；不得覆盖、续写或把竞争文件计为 owned；
- nested 和 flat 写入顺序不影响最终 exact tree。

## 6. Whole-root exact commit

`commit(expected_names)` 必须先 strict parse 全集合，并精确满足：

- expected file paths == owned file paths；
- derived expected child directories == owned child directories；
- root entries 精确等于 root files + child directories + lease；
- 每个 child entries 精确等于其 expected files；
- root、child、file、lease 全部物理 identity 与记录一致，无 link/reparse/alias/foreign entry；
- 所有 child directory 先 fsync，再移除 root lease、fsync root，再做一次无 lease 的 exact-tree/identity 复验；
- 关闭 child/root anchors 后才将事务标记 committed。

commit 不接受 manifest 自报树作为 authority；expected set 必须来自 caller 的冻结文件集合。未知 root/child 文件、
未知目录、空 child、额外层级、missing empty table 文件均失败。

## 7. Owned-only 逆序 rollback

任何未 commit 的退出必须按严格逆序回滚：

1. 关闭仍打开的 file descriptor；
2. 对 owned files 逐个复验 parent 与 file identity，只删除仍是原 owned inode/file-index 的文件；每次删除后 fsync
   对应 child/root；
3. 关闭 child anchors；
4. 对 owned child directories 逐个复验 identity，仅在 exact empty 时 rmdir，随后 fsync root；
5. 最后按既有规则删除 owned lease、fsync root、关闭 root anchor/registry。

若 owned file/directory 被替换、出现 foreign entry、unlink/rmdir/fsync 失败或无法证明 exact rollback，必须抛
`ArtifactRollbackError`；竞争者/预存/未知对象必须保留，绝不递归删除或“清空目录”。禁止 `rmtree`、glob delete、
按名称盲删和删除 caller 创建的 root。

## 8. Hostile、并发与异常脱敏

新增 nested hostile tests 至少覆盖：

1. absolute、drive、UNC、`..`、`.`、空段、重复 slash、backslash、colon、NUL、深度 3、保留设备名；
2. 大小写 alias、file/dir alias、root file 与 nested parent 冲突；
3. 预存 child、child symlink/junction/reparse、leaf symlink/hard-link、foreign child entry；
4. mkdir 前、child 创建后、file open 前、open 后/writer 前、writer 后、readback、commit 各窗口 root 或 child
   rename/replacement；writer 调用次数按首字节前语义精确；
5. 两线程/两进程同 root、同 child、同 leaf、不同 leaf 竞争；只能一个拥有，绝不覆盖；
6. nested writer `ValueError/RuntimeError`、嵌套 hostile exception graph、flush/fsync/dir-fsync/readback failure；
7. rollback 时 file 被替换、child 被替换、unknown file 注入、unlink/rmdir/fsync failure：保留非 owned 对象并报告
   rollback failure；
8. root+三个 child+29 file 的 exact commit，少/多/错任一 file 或 empty table file 均失败；
9. 所有既有 flat hostile tests原样绿色，flat root 不创建额外目录。

共享 helper 只抛无敏感 message/cause/context 的 `ArtifactPublicationError` 或 `ArtifactRollbackError`。正式 client
继续在自己的 boundary 映射 stage-specific stable error；path、TOKEN、SQL、PID、writer 私有 marker 与嵌套异常
不得穿透。

## 9. 文件白名单

实现 Agent 只允许修改/新增：

1. `src/quant/research/m3/_artifact_publication.py`；
2. `tests/unit/test_m3_nested_artifact_publication.py`；
3. `docs/agent/M3_G7F_P0_R1共享NestedArtifactPublication交付报告.md`。

独立初验 Agent 只可新增：

- `docs/agent/M3_G7F_P0_R1共享NestedArtifactPublication独立初验报告.md`。

主 Agent 只可新增最终验收报告。不得修改任一 G5A/G5B/G6A/G6B/G7A/G7B production/client/test 来迁就
共享 helper；这些现有测试只运行回归。不得修改 G7E/G7F、contracts、schemas、config、StageRunner 或 receipt。

## 10. 双平台验证

Windows 定向：

```powershell
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_nested_artifact_publication.py tests/unit/test_m3_formal_model_artifact.py tests/unit/test_m3_formal_prediction_artifact.py tests/unit/test_m3_formal_evaluation_artifact.py tests/unit/test_m3_formal_research_summary_artifact.py tests/unit/test_m3_formal_target_artifact.py tests/unit/test_m3_formal_backtest_plan_artifact.py -q
D:\Miniforge3\python.exe -m ruff check src/quant/research/m3/_artifact_publication.py tests/unit/test_m3_nested_artifact_publication.py
D:\Miniforge3\python.exe -m mypy src/quant/research/m3/_artifact_publication.py
```

WSL base 使用对应 worktree 运行同一 pytest/Ruff/mypy 集。若路径位于 `/mnt/f`/DrvFS，绿色只算兼容证据，
不冒充 Linux/ext4 Gate。主验按共享 primitive 风险追加全量：

```bash
/home/mabw/miniforge3/bin/conda run -n base sh -lc 'ruff check src tests && mypy src && pytest -q'
```

Windows 与 POSIX 的 no-follow、directory handle、fsync 实现允许平台分支，但外部合同、hostile 结果与 rollback
所有权必须一致；不得从 WSL 调 Windows conda。

## 11. 停止条件与闭环

以下任一出现立即停止：需要支持深度 >2/任意路径；需放宽 canonical path；无法锚定 child identity；Windows 无法
拒绝 reparse 或 POSIX 缺 `O_NOFOLLOW`；rollback 只能递归删除；需修改 flat client；共享 worktree 有重叠写入；
需要联网、真实数据、凭据或破坏性操作。

固定闭环：全新外部实现 Agent → 未参与实现的全新外部独立初验 Agent（增加 hostile 反例）→ 失败返工并重新
独立复验 → 主 Agent 双平台/flat 回归/whole-root hostile 最终验收。只有主 Agent 明确 PASS 后才能实施 G7F；
P0 PASS 不等于 G7F、G7 或 M3 PASS。
