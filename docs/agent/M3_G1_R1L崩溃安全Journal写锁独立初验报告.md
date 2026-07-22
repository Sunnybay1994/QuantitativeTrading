# M3 G1-R1L 崩溃安全 Journal 写锁独立初验报告

日期：2026-07-15  
状态：**初验通过（可进入主验）**  
角色：外部独立初验 Agent（未参与 R1L 实现 / 接管 / 合流收尾）  
模型：`cursor-grok-4.5-high`（非 fast）

本结论只针对 R1L 子包。**不宣称** R1L / G1 / M3 或任何 Gate 通过。

## 0. 边界与方法

| 项 | 内容 |
|---|---|
| 任务书 | [`M3_G1_R1L崩溃安全Journal写锁外部闭环任务单.md`](M3_G1_R1L崩溃安全Journal写锁外部闭环任务单.md) §8/§9 |
| 实现证据 | [`M3_G1_R1L崩溃安全Journal写锁交付报告.md`](M3_G1_R1L崩溃安全Journal写锁交付报告.md)；[`M3_G1_R1L合流证据收尾交付报告.md`](M3_G1_R1L合流证据收尾交付报告.md) |
| 只读 | 全部生产代码、实现者测试、配置、数据、交付报告 |
| 唯一写入 | 本独立初验报告 |
| 环境 | WSL Miniforge `base`；禁止 Windows Python |
| 协调锁 | `/tmp/quant-m3-r1-validation.lock` 持久 flock 串行；**未 unlink**（`LOCK_BEFORE=PRESENT` → `LOCK_AFTER=STILL_PRESENT`） |

临时对抗脚本与 runner 仅用于本轮验证，验证后删除；不进入 `tests/`。

## 1. 结论总览

| 阶段 | 结果 |
|---|---|
| 交付结构 / 屏障 / 合流证据核对 | PASS |
| 冻结合同逐项映射（§3–§7） | PASS |
| 四项未公开并发崩溃对抗（§8） | **4/4 PASS** |
| 持久 flock 重检查：定向 257 + Ruff 六文件 + mypy 81 | PASS |
| 禁项扫描（O_EXCL / lock unlink / PID·mtime lease / sleep） | PASS |
| 凭据/绝对路径扫描（helper） | PASS（0 命中） |
| **初验结论** | **通过；可进入主 Agent 终验** |

未发现需按六项格式返工的缺陷。

## 2. 交付与合流证据核对（只读）

| 核对项 | 结果 |
|---|---|
| `PARALLEL_BARRIER_READY: R1L` 已写入 | 是 |
| 首次合流 mypy 失败历史保留（`g1_planning.py:199` / R1A） | 是（交付报告 §4） |
| R1A 返工后合流重验：832 / Ruff / mypy 81 / exit 0 / 锁未 unlink | 报告可追溯；本初验未重复全量 832 |
| 白名单六生产+测试文件只读；本初验未改 `src/`/`tests/` | 是 |

## 3. 冻结合同逐项映射

| 契约面 | 证据 | 结论 |
|---|---|---|
| Helper API / 六稳定码 / `str(error)==code` / 无路径泄露 | `_journal_lock.py`；ADV1–3；实现者脱敏测试 | PASS |
| 绝对真实目录 root；祖先+root `(st_dev,st_ino)`；不 mkdir | `_snapshot_root_identities`；相对/缺失 root 测试 | PASS |
| `O_RDONLY\|O_DIRECTORY\|O_CLOEXEC\|O_NOFOLLOW` 开 root；相对 dir_fd 开 `.writer.lock`（`O_RDWR\|O_CREAT\|O_CLOEXEC\|O_NOFOLLOW`, 0o600） | 源码；ADV3 运行时 `FD_CLOEXEC` | PASS |
| 普通文件、`st_nlink==1`、directory entry 与 fd 同 inode；拒 symlink/dir/FIFO/hardlink | `_validate_lock_fd`；实现者 invalid kinds 测试 | PASS |
| `flock(LOCK_EX\|LOCK_NB)`；仅 EACCES/EAGAIN→ACTIVE；持锁不 close/unlink | 源码；ADV1 | PASS |
| 持久 lock 静态存在合法；仅 flock=active | ADV1/4；`test_stale_nonempty_lock_file_*`；executor 重复运行 | PASS |
| 释放：复核身份→`LOCK_UN`→close；漂移→`RELEASE_FAILED`；禁止 unlink；主异常优先 | `_release_journal_writer_lock`；ADV2；实现者 primary/release 测试 | PASS |
| 两 executor：mkdir/preflight 后整阶段 `with hold_...`；旧 O_EXCL/unlink 已删 | `m3_backfill.py:527`；`m3_reference.py:1099`；静态无 `lock_path.unlink`/`O_EXCL` | PASS |
| 错误映射表（Tushare ACTIVE→`JOURNAL_WRITER_ACTIVE`；BaoStock→`G1_REFERENCE_JOURNAL_INVALID`；IO/release 映射） | `_map_journal_lock_error`×2；ADV4 | PASS |
| SIGKILL 后可重获；intent/raw/candidate 合法恢复（非仅 helper 重锁） | ADV4（两 executor） | PASS |

## 4. 未公开对抗（§8）

| ID | 场景 | 结果 |
|---|---|---|
| ADV1 | 三进程：A 持锁 → B `JOURNAL_WRITER_ACTIVE` → SIGKILL A → C 立即获取；lock 文件仍在 | PASS |
| ADV2 | A 持锁时 unlink/recreate directory entry；A 退出 `JOURNAL_LOCK_RELEASE_FAILED`；新 inode 上已持有的 flock **未被** A 的 unlock 误释（再 flock 仍 EAGAIN） | PASS |
| ADV3 | 持锁 fd 带 `FD_CLOEXEC`；`close_fds=False` 子进程 exec 后父 lock fd 不存活；子进程新开仍 ACTIVE | PASS |
| ADV4 | Tushare：`after_candidate` 崩溃留下 intent/candidate/raw → 他进程持锁 SIGKILL → 恢复零 API 写 receipt；BaoStock：删 receipt 留 intent/candidate/raw → 持锁 SIGKILL → `_ExplodingClient` 零网络恢复且结果相等 | PASS |

## 5. 持久 flock 重检查

| 命令 | 结果 |
|---|---|
| 临时 ADV 脚本 | `ALL_ADV_PASS` |
| `pytest -q`（journal_lock + backfill_requests + reference） | **257 passed**（279.01s） |
| `ruff check`（R1L 六文件） | **All checks passed!** |
| `mypy src` | **Success: no issues found in 81 source files** |
| `/tmp/quant-m3-r1-validation.lock` | **STILL_PRESENT**（未 unlink） |

说明：合流全量 832 已由 R1A 返工会话在同一持久锁下完成；本初验在锁下重跑 R1L 定向与全量 mypy/Ruff（六文件），不重复约 50 分钟全量 pytest。

## 6. 下一步

- 可交主 Agent 终验（含其未公开反例与跨包不变量）。
- 实现者无需按六项返工格式返工。
- **不得**据此勾选路线图或宣称 G1/M3/Gate 通过；R1B 仍须等待主验通过后的任务书授权。
