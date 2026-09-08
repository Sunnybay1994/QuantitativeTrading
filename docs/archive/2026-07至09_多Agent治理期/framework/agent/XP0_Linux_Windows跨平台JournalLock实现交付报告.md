# XP0 Linux/Windows 跨平台 Journal Lock 实现交付报告

日期：2026-07-17  
角色：外部实现 Agent（本轮唯一实现者；不兼任独立初验或主验）  
任务单：`docs/framework/agent/XP0_Linux_Windows跨平台JournalLock实现任务单.md`
状态：**实现已交付待独立初验**；**不声称 Gate / 主验通过**

## 1. 结论

- 已将 `quant.data._journal_lock` 拆为 Linux `flock` 与 Windows `msvcrt.locking` 双后端，公共接口与六类稳定错误码不变。
- 探针证实 Windows 标准库字节锁满足：同进程第二句柄互斥、跨进程互斥、进程强制终止后内核释放；未引入第三方锁依赖，未降级 Linux 安全语义。
- Windows 全量 `pytest --collect-only` 现为 **1349 collected / exit 0**（修复前为 import 链 `fcntl` 失败）；M3 G1 定向组两平台均可 collect（112 项 / exit 0）。
- 锁专项与 Linux backfill 回归通过；部分 Windows symlink 特权不足用例、`test_m3_reference` fixture KeyError、以及 G1 candidate/workflow 超长运行属既有/环境限制，见风险节。

## 2. 修改文件（白名单）

| 文件 | 目的 |
|---|---|
| `src/quant/data/_journal_lock.py` | 双平台后端；Windows `msvcrt` + reparse/junction fail-closed；Linux 保持 flock/dir-fd/O_NOFOLLOW |
| `tests/unit/test_m3_journal_lock.py` | 跨平台化既有反例；新增 Windows 同进程/跨进程/kill/junction/hardlink/release 反例 |
| `tests/unit/test_m3_backfill_requests.py` | unlock 注入测试适配 `msvcrt`/`fcntl` |
| `tests/unit/test_m3_reference.py` | `SIGKILL`→`kill()` 以跨平台终止子进程 |
| `AGENTS.md` | 仅 §8：Windows 反馈环 vs WSL Gate 边界 |
| `README.md` | 环境/验证命令同步 |
| `docs/framework/agent/XP0_Linux_Windows跨平台JournalLock实现交付报告.md` | 本报告 |

## 3. 设计要点

- **公共层**：`hold_journal_writer_lock` / `M3JournalLockError` / 六稳定码；acquire 后与 release 前复验 root/祖先/lock 身份；主异常存在时 release 失败不覆盖。
- **Linux**：持久 `.writer.lock` + `flock(LOCK_EX\|LOCK_NB)` + 目录 FD + `O_NOFOLLOW` + inode/dev/nlink；既有对抗路径保留。
- **Windows**：`msvcrt.locking(..., LK_NBLCK, 1)`，offset=0，文件至少 1 byte；路径用 `lstat` + `isjunction` + `st_file_attributes` reparse 位 fail-closed；无 dir-fd（stdlib 无法以 BACKUP_SEMANTICS 打开目录）。
- **不变量**：锁文件持久、内容不可信；不以文件存在代替活跃 writer。

## 4. 验证命令与退出码

### Windows（`D:\Miniforge3\python.exe`）

| 命令 | 退出码 | 摘要 |
|---|---:|---|
| `pytest tests/unit/test_m3_journal_lock.py -q -p no:cacheprovider` | **0** | 20 passed |
| `pytest tests/unit/test_m3_backfill_requests.py -q -p no:cacheprovider` | **1** | 120 passed / 11 failed：均为创建 symlink/fifo（WinError 1314 无特权）等既有平台限制；锁相关 4 项单独跑通过 |
| `pytest tests/unit/test_m3_backfill_requests.py -k "lock or JOURNAL_WRITER or stale_lock or concurrent" -q` | **0** | 4 passed |
| `pytest tests/unit/test_m3_reference.py -q -p no:cacheprovider` | **1** | 大量 ERROR：fixture `KeyError` at L395（request_id 缺失）；与锁无关 |
| `pytest tests/unit/test_m3_g1_planning.py -q` | **1** | 17 passed / 1 failed：`test_source_symlink_and_root_symlink_rejected` WinError 1314 |
| `pytest tests/unit/test_m3_run_g1.py -q` | **1** | 34 passed / 2 failed：config symlink 用例 WinError 1314 |
| `pytest tests/unit/test_m3_g1_candidate.py`（执行） | **未完成** | 卡在 `test_response_order_and_frame_row_order_stable_identity`（长时间 CPU，非锁死）；已终止 |
| `pytest tests/unit/test_m3_g1_workflow.py`（执行） | **未完成** | 长时间无收尾；已终止 |
| G1 四文件 `--collect-only -q` | **0** | 112 collected |
| 全量 `--collect-only -q` | **0** | **1349 collected** |
| `ruff check` 白名单 Python | **0** | All checks passed |
| `mypy src/quant/data/_journal_lock.py m3_backfill.py m3_reference.py` | **0** | Success |

### Linux（WSL `conda run -n base`，`/home/mabw/AI_Coding_win/QuantitativeTrading`）

| 命令 | 退出码 | 摘要 |
|---|---:|---|
| `pytest tests/unit/test_m3_journal_lock.py -q -p no:cacheprovider` | **0** | 19 passed / 3 skipped（Windows-only） |
| `pytest tests/unit/test_m3_journal_lock.py tests/unit/test_m3_backfill_requests.py -q` | **0** | 150 passed / 3 skipped |
| `pytest ... journal+backfill+reference -q` | **1** | 186 passed / 3 skipped / **80 errors**：同 reference fixture KeyError |
| `pytest tests/unit/test_m3_g1_planning.py -q` | **0** | 18 passed |
| `pytest tests/unit/test_m3_g1_candidate.py` / `workflow`（执行） | **未完成** | >10min 仍高 CPU 无收尾（DrvFs/体量）；已终止；**不记为通过** |
| G1 四文件 `--collect-only -q` | **0** | 112 collected |
| `ruff check` 白名单 | **0** | All checks passed |
| `mypy` 同上三文件 | **0** | Success |

## 5. 任务单要求反例覆盖

1. Windows 同进程第二句柄 + fresh subprocess → `JOURNAL_WRITER_ACTIVE`（已测通过）  
2. Windows 持锁进程强制终止后 fresh acquire（已测通过）  
3. Windows junction ancestor + lock hardlink fail-closed（已测通过）  
4. acquire 后 lock 身份漂移 → release `JOURNAL_LOCK_RELEASE_FAILED`；主异常不覆盖（已测；Windows 因无法 unlink 打开锁文件，release 路径用校验漂移模拟，Linux 仍真实 unlink 替换）  
5. Linux 既有 root/ancestor/lock 替换、hardlink、symlink、subprocess 反例（19 passed，未删减）

## 6. 风险与未决

- **未声称 Gate/主验通过**；独立初验与主验仍需另开会话。
- Windows 无 symlink 创建特权时，依赖 `symlink_to` 的非锁用例失败（WinError 1314）；junction 路径已覆盖祖先 reparse。
- Windows 持锁期间无法 `unlink` 锁文件；release 期“目录项替换”物理 TOCTOU 与 Linux 不等价，已在文档/§8 声明原语不等价。
- `test_m3_reference.py` fixture KeyError（`history_batch` request_id 不在 fake responses）两平台均现，**超出 XP0 锁白名单根因**，阻塞 reference 锁集成执行项。
- G1 candidate/workflow **执行期**在本环境极慢/未在时限内收尾；collect 已证明 import 链修复，执行回归需初验/主验在更合适 I/O 环境重跑。
- AGENTS.md §1.1 仍有“默认 WSL 命令”表述；§8 已补充 Windows 反馈环，不以 Windows 绿测代替 Linux Gate。

## 7. 回滚

恢复上表白名单文件即可；无 data/artifacts/依赖/Git 变更。
