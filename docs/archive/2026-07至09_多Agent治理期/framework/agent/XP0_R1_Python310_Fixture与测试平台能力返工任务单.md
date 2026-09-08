# XP0-R1 Python 3.10、Fixture 与测试平台能力返工任务单

日期：2026-07-18  
角色：主 Agent 汇总独立初验与主验反例后冻结返工；实现与复验必须使用不同全新外部会话  
状态：已授权实施；不关闭 XP0/M3/M4 或任何 Gate

## 1. 返工闭环总览

### R1 — Python 3.10/3.11 泄漏原始异常

- 现象：`pyproject.toml` 声明 Python `>=3.10`，但 `_is_reparse_stat` 无保护调用 Python 3.12 才提供的
  `os.path.isjunction`。主验删除该属性模拟旧版本后，首次 acquire 直接泄漏 `AttributeError`，exit 1。
- 根因：实现只在当前两套 Python 3.13 环境验证，未按项目版本 SSOT 做能力探测；Windows acquire 的 root snapshot
  又位于 backend try 块之前，故异常未映射为稳定码。
- 应遵循规则：公共模块须满足 `requires-python`；平台能力用 `getattr`/feature detection，Windows reparse 仍由
  `st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT` fail closed，不得因兼容旧版本而放行 junction。
- 最小复现：`del os.path.isjunction` 后对绝对临时 root 调用 `hold_journal_writer_lock`，当前抛原始
  `AttributeError`。
- 新增测试：两平台 monkeypatch 删除 `os.path.isjunction` 后普通目录仍可 acquire/release；当前 Windows 的真实
  junction/reparse 测试继续通过。
- 通过条件：无原始异常；普通路径成功；真实 reparse 仍返回既有稳定码；不改变六码公共接口。

### R2 — reference fixture 与当前 per-symbol suspend 计划漂移

- 现象：两平台 `test_m3_reference.py` 为 36 passed / 80 errors，最小 setup 在 `_build_inputs` 对 request id
  `KeyError`；锁集成用例也无法执行。
- 根因：当前 `plan.history_batch` 含 300 条带 `ts_code` 的 `suspend_d`，fixture 只为旧式无 symbol suspend
  构造响应。
- 应遵循规则：测试 fixture 必须服从实际 planning 合同，不得用 collect 或跳过掩盖 setup 崩溃。
- 最小复现：`test_reconcile_cross_source_happy_path_full_closure` setup `happy_inputs`。
- 新增/修正测试：为每条 `suspend_d` 按实际 request parameters 构造最小、确定、schema 合法的响应；显式断言
  fixture request ids 与 history batch 闭合，并使 stale lock / active lock + kill recovery 集成用例真正执行。
- 通过条件：两平台 reference 文件或至少全部 reference lock 集成及其共享 fixture 链通过，零 setup error。

### R3 — Windows 无 symlink 权限被误记为产品失败

- 现象：Windows backfill 11 failed、planning/run_g1 3 failed，均在测试准备阶段创建 symlink/fifo，典型为
  WinError 1314；journal lock 的 Windows junction/reparse 对抗本身已通过。
- 根因：测试无条件假设 Windows 会话具有 Developer Mode/SeCreateSymbolicLinkPrivilege。
- 应遵循规则：平台安全语义不能删除；当且仅当 Windows 明确返回“缺少创建 symlink 权限”时，该 Linux
  symlink 构造用例可在准备阶段 `pytest.skip`，其他异常必须继续失败。Windows 必须保留并通过等价可执行的
  junction/reparse、hardlink、同进程与跨进程反例。
- 最小复现：`test_controlled_roots_fail_before_any_side_effect[raw_root]`。
- 新增测试/适配：仅在实际 symlink/fifo 构造位置做窄 capability helper；禁止按 `os.name` 无条件跳过整类测试，
  禁止 skip 产品代码异常。
- 通过条件：当前无特权 Windows 环境不再出现 1314 失败，报告准确列出 skip 数；Linux 原测试仍执行并通过；
  Windows JournalLock 可执行替代反例继续通过。

### R4 — `AGENTS.md` 环境 SSOT 自相矛盾

- 现象：§8 已允许 Windows Miniforge 作为开发反馈环，但 §1.1 仍写旧
  `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` 并“禁止调用 Windows Python/conda”。
- 根因：XP0 只局部更新 §8，没有同步同一权威文件中的外部 Agent 命令边界。
- 应遵循规则：同一 SSOT 不得冲突；用户已明确允许 Windows 原生开发，同时要求 Linux+Windows 兼容。Linux/Gate
  仍以 WSL base 为准，Windows 绿测不能替代平台特有终验。
- 通过条件：§1.1 使用当前 WSL 路径 `/home/mabw/AI_Coding_win/QuantitativeTrading`；允许具体任务书指定
  Windows Miniforge 反馈命令；保留禁止从 WSL 调 Windows conda、禁止用 Windows 替代 WSL Gate。

## 2. 验证范围修订

XP0 的目标是跨平台导入与 JournalLock 合同，不以执行全部耗时 G1 candidate/workflow 作为锁正确性的必要证据。
独立初验已证明 candidate 单测在加长窗口可过，workflow 超时未证明锁问题。R1 后验收采用：

1. 两平台 JournalLock 全文件；
2. 两平台 backfill/reference 的锁、错误映射、并发副作用集成；reference fixture 修复后不得 setup error；
3. Windows backfill/planning/run_g1 的非特权能力适配结果，Linux 对应聚焦回归；
4. 两平台 M3 G1 四文件 collect；Windows 全量 collect；
5. 白名单 Ruff/mypy；
6. 不重复运行已知超长的 candidate/workflow 全文件。它们留给 M3 跨包 Gate 回归，不能在 XP0 报告中称通过。

## 3. 文件白名单

- `src/quant/data/_journal_lock.py`
- `tests/unit/test_m3_journal_lock.py`
- `tests/unit/test_m3_reference.py`
- `tests/unit/test_m3_backfill_requests.py`
- `tests/unit/test_m3_g1_planning.py`
- `tests/unit/test_m3_run_g1.py`
- `AGENTS.md`（仅 §1.1 与 §8 的环境边界去冲突）
- `docs/framework/agent/XP0_R1_Python310_Fixture与测试平台能力返工交付报告.md`

禁止修改 README、其他生产代码/测试、pyproject、配置、`data/**`、`artifacts/**`、`.git` 与既有任务/报告。
禁止联网、真实数据、安装依赖或降低 Linux 锁合同。

## 4. 外部实现与复验

实现使用全新 `cursor-grok-4.5-high` 会话。Windows 使用 `D:\Miniforge3\python.exe`；Linux 使用
`/home/mabw/AI_Coding_win/QuantitativeTrading` 的 WSL Miniforge base。逐条记录命令、exit code、pass/skip/error
摘要，不粘贴长 warning。

实现停止后，另一全新 `cursor-grok-4.5-high` 会话只读复验，唯一允许写：
`docs/framework/agent/XP0_R1_Python310_Fixture与测试平台能力独立复验报告.md`。

复验除重跑上节范围外，须增加实现者未使用反例：

- 同时令 `isjunction` 不存在并模拟普通/带 reparse attribute 的 stat，分别不得误拒与不得放行；
- reference fixture request-id 集合的少一条/多一条反例必须 fail closed 或被显式断言捕获；
- symlink helper 对非 1314 异常不得 skip；Linux symlink 测试必须实际执行。

## 5. 停止条件

- 需要改变六码错误合同、引入第三方依赖或降低 reparse/hardlink/TOCTOU 防护；
- 试图通过无条件 skip、删除安全测试或仅 collect 掩盖 reference setup error；
- 触碰白名单外文件、真实数据、网络、凭据或外部状态。
