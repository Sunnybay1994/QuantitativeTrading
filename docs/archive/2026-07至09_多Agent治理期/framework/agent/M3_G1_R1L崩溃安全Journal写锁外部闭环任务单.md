# M3 G1-R1L 崩溃安全 Journal 写锁外部闭环任务单

日期：2026-07-15  
状态：**外部实现—独立初验闭环完成，主 Agent 最终验收通过**  
执行/独立初验模型：两个全新非 fast `cursor-grok-4.5-high` 会话  
环境：WSL Miniforge `base`；Linux `fcntl.flock`，不兼容 Windows 原生运行

## 1. 根因与目标

现有 B2A/P4B 写锁使用 `.writer.lock` 的 `O_CREAT|O_EXCL` 空文件，创建后立即关闭 fd，结束时 unlink。该方案
只能阻止正常进程同时进入；进程 `SIGKILL`/掉电后会遗留无法判断 owner 的文件，后续运行永久报 active，
与 R1B/R1C 的 hard-crash 可恢复目标冲突。

R1L 把两处锁统一改为**持有整个写阶段的 Linux advisory flock**：锁文件持久存在，进程退出/崩溃时内核
自动释放锁；后续进程打开同一 inode 后即可安全取得。不得用 PID 探活、mtime lease、盲删 lock、sleep 重试或
Windows lock API。

R1L 只改变 writer exclusion，不改变 request ID、raw/receipt bytes、网络重试、candidate/release identity。
通过不关闭 G1/Gate。

## 2. 文件白名单

```text
src/quant/data/_journal_lock.py
src/quant/data/m3_backfill.py
src/quant/data/m3_reference.py
tests/unit/test_m3_journal_lock.py
tests/unit/test_m3_backfill_requests.py       # 只更新锁相关断言/故障注入
tests/unit/test_m3_reference.py               # 同上
docs/M3_G1_R1L崩溃安全Journal写锁交付报告.md
docs/M3_G1_R1L崩溃安全Journal写锁独立初验报告.md
```

不得修改 RawStore、connector、request/receipt schema、R1A/R1B/R1C、配置、路线图或真实 data。

## 3. 冻结 helper

```python
class M3JournalLockError(ValueError):
    code: Literal[
        "JOURNAL_LOCK_INPUT_INVALID",
        "JOURNAL_LOCK_ROOT_INVALID",
        "JOURNAL_LOCK_FILE_INVALID",
        "JOURNAL_WRITER_ACTIVE",
        "JOURNAL_LOCK_IO_FAILED",
        "JOURNAL_LOCK_RELEASE_FAILED",
    ]

@contextmanager
def hold_journal_writer_lock(*, journal_root: Path) -> Iterator[None]: ...
```

`str(error)==code`；`repr/cause/traceback` 不泄露绝对路径、inode、本机信息或底层异常文本，边界 `from None`。
helper 不公开 fd/Path，不产生 receipt，不写 owner/PID/time/host。

## 4. 获取协议

1. `journal_root` 必须是已存在的绝对真实目录。调用者仍负责创建 root；helper 不 `mkdir`。
2. 从 root.parent 到文件系统根拒绝 symlink；记录祖先与 root 的 `(st_dev, st_ino)`。
3. 以 `O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW` 打开 root directory fd，`fstat` 与入口 identity 一致。
4. 相对 directory fd 打开固定 `.writer.lock`：

   ```text
   O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW, mode=0o600
   ```

5. `fstat` 要求普通文件、`st_nlink==1`；再用 `os.stat(..., dir_fd=dir_fd, follow_symlinks=False)` 证明目录项和 fd
   是同一物理文件。拒绝 symlink、目录、FIFO/socket/device、hardlink。
6. `fcntl.flock(lock_fd, LOCK_EX | LOCK_NB)`：`EACCES/EAGAIN` 唯一映射 `JOURNAL_WRITER_ACTIVE`；其他 errno
   映射 IO，不按 message 猜测。
7. flock 成功后再次验证 root/祖先/lock 物理 identity，再 yield。不得关闭 fd，不得 unlink lock 文件。

持久 lock 文件的普通存在是合法静态状态；“文件存在”不再表示 active，只有 flock 结果表示 active。

## 5. 释放协议

正常和异常退出都执行：

1. 在持锁状态下复核祖先、root 和 lock directory entry identity；漂移记为 release failure；
2. `flock(LOCK_UN)`；
3. close lock fd；
4. close directory fd。

优先级固定：with-body 已有主异常时，释放/close 错误不得覆盖主异常，但必须尽最大努力关闭；无主异常时，
第一个释放错误稳定抛 `JOURNAL_LOCK_RELEASE_FAILED`。禁止 unlink lock 文件，因此不存在 unlink-after-acquire
导致另一个 inode 被并发创建的 split-brain。

## 6. 两个 executor 接入

`execute_tushare_batch` 和 `execute_baostock_reference_plan` 的范围必须是：

```python
journal_root.mkdir(...)
preflight(...)
with hold_journal_writer_lock(journal_root=journal_root):
    # 当前从第一项 preflight 到最后 receipt verify 的完整原 body
```

不得只锁网络部分或单个 request。删除旧 `os.open(O_EXCL)`/close/unlink 逻辑。

错误映射：

| helper code | Tushare executor | BaoStock executor |
|---|---|---|
| `JOURNAL_WRITER_ACTIVE` | 原 `M3BackfillError("JOURNAL_WRITER_ACTIVE")` | `M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")` |
| input/root/file | 对应现有 journal/root invalid 稳定码 | `G1_REFERENCE_JOURNAL_INVALID` |
| IO/release | 对应现有 lock/cleanup IO 稳定码；不得加入 message | `G1_REFERENCE_IO_FAILED` |

现有 committed receipt bytes、raw bytes 和 stable hashes必须逐字节不变。正常完成后 `.writer.lock` 仍存在为
普通单链接文件；重复运行必须忽略其静态存在并重新 flock。

## 7. 测试

至少覆盖：

1. 同一进程嵌套第二次获取 → ACTIVE；首个释放后可获取；
2. 独立子进程持锁时父进程 ACTIVE；子进程正常退出和 `SIGKILL` 后父进程均可立即获取；
3. 预先存在的普通 stale lock 文件可获取，内容即使非空也不得读取/信任；
4. symlink、hardlink、directory、FIFO lock 拒绝；root/祖先 symlink 拒绝；
5. acquire 前后 root 或 lock inode 替换、持锁期间 directory entry 被替换，在安全边界失败；
6. body 主异常优先于 unlock/close 故障；无主异常时 release failure 可见；所有 fd 无泄漏；
7. Tushare/BaoStock 两 executor 的并发、SIGKILL recovery 和重复运行；
8. 既有 raw/receipt golden bytes/hash 不变；旧测试不得仅删除断言来变绿；
9. 生产路径无 `O_EXCL` writer marker、无 lock unlink、无 PID/mtime lease、无 sleep；
10. 全量 pytest、Ruff、mypy。

## 8. 独立初验

全新 Grok High 会话只读生产代码和实现者测试，只写初验报告；必须新增至少：

- 三进程竞争：A 持锁、B ACTIVE、杀 A、C 获取成功；
- 在 A 持锁时 unlink/recreate lock directory entry，证明 A 退出报告 release failure，且实现不会把新 inode
  误当自己的 lock 解锁；
- lock fd 继承/子进程边界，证明 `O_CLOEXEC`；
- 两 executor 在 hard crash 后从既有 intent/raw/candidate 合法恢复，而不是只证明 helper 可重锁。

不通过按标准六项格式返工并回到原实现会话；独立复验明确通过后才进入主 Agent 终验和 R1B。

## 9. 与 R1A 的两路并行执行屏障

R0 主验后，R1L 允许与 R1A 同时由两个全新的 `cursor-grok-4.5-high` 实现会话执行，因为两包生产代码、
测试和交付报告白名单互斥。并行模式必须遵循：

1. R1L 完成自身全部文件写入和定向测试后，在自身交付报告写入精确标记
   `PARALLEL_BARRIER_READY: R1L`；写入该标记后不得再修改生产代码或实现者测试。
2. 只读等待 R1A 交付报告出现 `PARALLEL_BARRIER_READY: R1A`；不得读取 R1A 未冻结的中间源码来调整本包。
3. 双方标记齐全后，才运行全量 pytest、Ruff、mypy。三项命令整体必须在 WSL
   `flock /tmp/quant-m3-r1-validation.lock` 下串行执行；该协调 lock 只做测试资源协调，不进入项目或产品合同，
   但任何会话均不得 unlink，避免旧 inode 持锁时创建新 inode 形成 split-brain。静态文件可留在 `/tmp`，
   后续只复用 flock。
4. 全量验证完成后补齐报告并改为“待独立初验”。任一方在屏障前失败，另一方保持待合流状态，由主 Agent
   处理失败包；不得把对端未完成写成自己的通过。

两个实现会话都退出且报告完整后，R1A 与 R1L 的两个全新独立初验会话才可并行启动；初验同样使用上述
临时 `flock` 串行运行重检查，并且只写各自互斥的初验报告。
