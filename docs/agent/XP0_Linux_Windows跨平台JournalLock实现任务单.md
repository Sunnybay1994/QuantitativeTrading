# XP0 Linux/Windows 跨平台 Journal Lock 实现任务单

日期：2026-07-17  
角色：主 Agent 冻结合同；外部实现 Agent 与外部独立初验 Agent 必须使用不同全新会话  
状态：已授权实施；不授权任何真实数据网络请求，不关闭 M3/M4 或任何 Gate

## 1. 目标与价值

- 用户可观察结果：`quant.data`、M3 HISTORY/REFERENCE 相关模块可在 Linux 与 Windows Python 导入；
  journal writer lock 在两个平台都保持非阻塞独占、进程崩溃自动释放、持久锁文件不代表活跃 writer。
- 价值：Windows 原生 Miniforge 可作为普通开发/测试反馈环；Linux/目标文件系统仍承担平台特有发布终验。
- 明确非目标：不执行 HISTORY-PILOT10，不联网，不修改 raw/journal/receipt，不为 Windows 降低 G1
  `RENAME_NOREPLACE` 发布合同，不安装/升级依赖，不把 Qlib 装入 base，不顺手修其他跨平台问题。

## 2. 现状与权威上下文

- Windows base Python 3.13.13 已安装当前项目 `.[dev,data,research]`；同一 M3 定向组在收集阶段因
  `src/quant/data/_journal_lock.py` 顶层 `import fcntl` 出现 5 个 `ModuleNotFoundError`。
- Windows 全量 `pytest --collect-only` 已收集 365 项，44 个模块均沿同一 import 链因该 `fcntl` 依赖失败；
  当前没有第二个独立收集期平台缺陷证据。XP0 修复后必须重跑全量 collect，不能把“单一根因”当成已证明
  后续执行期全部兼容。
- Linux 实现已通过既有多轮对抗，使用 persistent `.writer.lock`、`flock(LOCK_EX|LOCK_NB)`、目录 FD、
  `O_NOFOLLOW`、inode/dev/nlink 与祖先身份复验；这些安全语义不得回退。
- SSOT：`AGENTS.md`、`.ai/coding_rules.md`；领域调用方为 `m3_backfill.py`、`m3_reference.py`，稳定错误码
  为 `M3JournalLockError` 现有六类。

## 3. 成功标准

- [ ] `_journal_lock.py` 在 Linux 与 Windows 均可导入，公共接口和稳定错误码不变。
- [ ] Linux 后端保持现有 `flock`、dir-fd/nofollow、祖先/root/lock identity、hardlink/symlink/TOCTOU 与
  release 失败语义；既有 Linux 对抗测试不得删除或弱化。
- [ ] Windows 后端只用标准库/Win32 Python 能力（优先 `msvcrt` 非阻塞字节区间锁），锁文件至少包含可锁的
  1 byte；第二 writer 在同进程不同句柄及不同进程均稳定得到 `JOURNAL_WRITER_ACTIVE`。
- [ ] Windows 正常退出、异常退出/进程终止后锁由内核释放；锁文件保留且下一 writer 可重新获取。
- [ ] Windows 拒绝相对路径、缺失/非目录 root、root 或任一祖先 symlink/junction/reparse 路径、锁文件
  symlink/目录/多 hardlink/打开后身份替换；所有异常保持脱敏稳定码。
- [ ] acquire 后与 release 前均复验 root/祖先/lock 身份；已有主异常时 release 异常不得覆盖主异常。
- [ ] `m3_backfill` 与 `m3_reference` 的错误映射不变；两平台并发调用不产生第二份 API/raw/journal 副作用。
- [ ] Windows M3 定向组能完成收集并通过；Linux 相关锁与 M3 定向回归通过。
- [ ] 文档明确双平台开发反馈环与平台特有 Gate，不声称 Windows 与 Linux 文件系统原语完全等价。

## 4. 事实、假设与设计边界

- 已确认 Windows stdlib 没有 `fcntl`；不得通过条件跳过锁、全局线程锁或“文件存在即被锁”替代。
- `msvcrt.locking(..., LK_NBLCK, 1)` 若采用，必须固定 offset=0、确保文件长度至少 1，并把共享冲突映射为
  `JOURNAL_WRITER_ACTIVE`；其他 IO 失败映射到既有稳定码。
- Windows 路径校验必须显式识别 symlink 与 junction/reparse ancestor；仅 `Path.is_symlink()` 不足时使用
  Python 3.13 可用的 `os.path.isjunction` 或等价只读能力。
- 不新增第三方锁依赖。若标准库无法同时证明同进程与跨进程互斥，停止并提交证据，不自行改成 lockfile
  create/delete 协议。
- Linux 与 Windows 可以有私有平台后端；公共 context manager、异常合同、复验顺序保持统一。

## 5. 文件范围

允许修改：

- `src/quant/data/_journal_lock.py`
- `tests/unit/test_m3_journal_lock.py`
- `tests/unit/test_m3_backfill_requests.py`（仅直接依赖 `fcntl` 的锁注入测试适配）
- `tests/unit/test_m3_reference.py`（仅跨平台锁集成测试必要适配）
- `AGENTS.md`（仅 §8 双平台开发/验证边界）
- `README.md`（仅环境/验证命令同步）
- `docs/agent/XP0_Linux_Windows跨平台JournalLock实现交付报告.md`

禁止修改：其他 `src/**`、其他测试、`pyproject.toml`、配置、`data/**`、`artifacts/**`、既有任务/验收报告、
`.git`。禁止联网、真实数据命令、删除或覆盖 `.writer.lock`。

## 6. 实现与验证要求

### 6.1 外部实现 Agent

- 使用全新 Windows `cursor-agent` 普通 Agent 会话，显式模型 `cursor-grok-4.5-high`；workspace 为
  `F:\AI_Coding\QuantitativeTrading`。
- 完整读取 `AGENTS.md`、本任务单、目标源码与测试。Windows 项目命令用
  `D:\Miniforge3\python.exe`；Linux 项目命令通过 WSL
  `/home/mabw/miniforge3/bin/conda run -n base`，项目路径
  `/home/mabw/AI_Coding_win/QuantitativeTrading`。
- 不得等待或干扰当前主 Agent 已启动的 WSL pytest；若仍有同文件测试进程，先只实现，待其结束再验证。
- 交付报告只保留命令、退出码、摘要与风险，不回传长日志。

最低验证：

```text
Windows:
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_journal_lock.py -q -p no:cacheprovider
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_reference.py -q -p no:cacheprovider
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_g1_planning.py tests/unit/test_m3_g1_candidate.py tests/unit/test_m3_g1_workflow.py tests/unit/test_m3_run_g1.py -q -p no:cacheprovider
D:\Miniforge3\python.exe -m ruff check <白名单 Python 文件>
D:\Miniforge3\python.exe -m mypy src/quant/data/_journal_lock.py src/quant/data/m3_backfill.py src/quant/data/m3_reference.py

Linux（WSL base，待既有 pytest 结束后）：
python -m pytest tests/unit/test_m3_journal_lock.py tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_reference.py -q
python -m pytest tests/unit/test_m3_g1_planning.py tests/unit/test_m3_g1_candidate.py tests/unit/test_m3_g1_workflow.py tests/unit/test_m3_run_g1.py -q
ruff check <白名单 Python 文件>
mypy src/quant/data/_journal_lock.py src/quant/data/m3_backfill.py src/quant/data/m3_reference.py
```

至少新增并实际运行以下反例：

1. Windows 同进程第二句柄与 fresh subprocess 均不能获取已持有锁；
2. Windows 持锁 subprocess 被强制终止后 fresh process 可获取；
3. Windows junction ancestor 与 lock hardlink fail closed；
4. acquire 后 lock entry 被替换，release 返回 `JOURNAL_LOCK_RELEASE_FAILED`；主异常存在时不覆盖；
5. Linux 既有 acquire 后 root/ancestor/lock 替换、hardlink、symlink、fork/subprocess 反例仍通过。

### 6.2 外部独立初验 Agent

实现停止后使用另一全新 `cursor-grok-4.5-high` 会话。生产/测试/文档只读，唯一允许写：

`docs/agent/XP0_Linux_Windows跨平台JournalLock独立初验报告.md`

初验必须重新运行两平台聚焦测试并增加实现者未使用的反例：Windows 同进程重入是否真的互斥，以及 junction
或锁文件替换是否可能在校验后绕过。发现问题按“现象—根因—规则—最小复现—新增测试—通过条件”退回。

## 7. 停止与回滚

- 发现 Windows 标准库后端无法提供 crash-safe 内核锁、同进程互斥或 fail-closed 路径校验时立即停止；
  不引入未授权依赖、不降低 Linux 合同。
- 任一测试触达项目真实 `data/**`、网络或凭据立即停止。
- 回滚是恢复白名单源码/测试/文档；环境中的 Windows extras 安装不属于代码回滚，不修改业务数据。
