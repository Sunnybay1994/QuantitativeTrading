# M3 G8C-C1 U13 R1：资源受限性能闭包与 Public CLI 长运行任务单

日期：2026-08-13  
状态：**R3 honest 300 证券 public CLI 首发、completed resume、零额外业务写与 fixture teardown 已在最终 revision 自然 PASS；Windows 工程准入闭合，不代表 Linux/ext4 或真实远端 tracking Gate**

## 1. 目标

在不改变策略、市场规则、三成本场景、21-input/29-output receipt 或 fresh verification 语义的前提下，
消除同一首次发布调用内的重复经济回放，并重新执行 Windows Python 3.12 `m3chain312` 的 honest 300
证券 public `backtest` CLI：首次发布成功后，同一参数继续验证 completed resume 与零写边界。

## 2. 性能闭包

- G7E 三场景复用一次 fresh plan、facts clone 与 session-domain 准备；各场景账户状态仍独立初始化并串行回放。
- G8 缓存仅由本次真实 `build_backtest_artifact` 在调用栈内产生；绑定 exact 29 文件 bytes、canonical
  manifest/metrics 与文件实体。temp/final closure、receipt 发布和轻量 final 签发均重新核对 21 输入与29输出摘要。
- 独立 completed resume 没有本次 builder proof，继续调用完整 `verify_backtest_build_output` 与
  `verify_backtest_artifact`，不得跨调用缓存 formal capability 或结果。
- 输出等价性必须以三次独立串行 replay 与批量 replay 七表逐值相同为证。

## 3. 资源边界

- 单一 pytest/public CLI 进程；禁止重复或并发启动同一长任务。
- Windows 进程优先级 `BelowNormal`，CPU affinity 最多 8/12 逻辑线程；保留至少4个逻辑线程给其他工作。
- `POLARS_MAX_THREADS=4`、`OMP_NUM_THREADS=4`、`OPENBLAS_NUM_THREADS=2`、`MKL_NUM_THREADS=2`、
  `NUMEXPR_NUM_THREADS=2`。
- CPU v1 保持正式基线。GPU probe 的成功只证明 backend 可用，本任务不修改训练 profile 或 artifact identity。
- 运行上限 8 小时；自然完成前低频观察，不做分钟级日志轮询。

## 4. 通过条件

- public producer 保持完整 300 证券，不使用 private capability/result 注入；
- 首次 CLI 返回 canonical 单行 JSON、`reused=false`，只新增对应 backtest 29 outputs 与 receipt；
- 第二次同参返回 `reused=true`，G1 与 stage tree 零额外写；
- session-owned stage/config/G1 roots 在 fixture teardown 后按身份精确清理，`_f0r*` 残留为0；
- 8 小时内自然得到 pytest PASS。任何超时、身份漂移或清理不完整均不得记为通过。

## 5. 路线定位

本任务只生成 M3/S3 formal 晋级证据，不再阻塞 S2+ 策略研究。运行期间主 Agent 可继续处理不争用该
工作树长链文件和高 CPU 的轻量策略设计、文档或 M4 串行工作。

## 6. 启动记录

- 启动时间：2026-08-13 16:13:19（Asia/Shanghai）；
- Python：`D:\Miniforge3\envs\m3chain312\python.exe`；
- 唯一 child PID：`43308`；优先级 `BelowNormal`；affinity `255`；
- AC sleep：disabled；
- 状态与日志：`artifacts/agent_runs/m3-u13/`；
- 终态在自然完成或8小时停止条件触发后回写，不提前声明 PASS。

## 7. R1 终态与根因（2026-08-13）

- pytest 在约 `5221.29s` 后终态为 `1 failed`。首个 public CLI 已返回 `code=0`、canonical JSON、
  `reused=false`；业务 payload、G1 零写等前置断言通过。测试在检查 stage root 新增文件集合时失败，
  因此 completed resume 未执行，R1 不满足第 4 节通过条件。
- 现象：验收 helper `_tree_signature` 把 `.stage-locks/<node-hash>/.writer.lock` 计入业务文件；允许集合只列
  backtest 29 outputs 与 receipt，所以首次运行必然多出一项。
- 根因：`StageRunner` 对每个节点调用共享 `hold_journal_writer_lock`。该组件有意保留 advisory lock；
  Windows 字节区间锁文件为单个 `NUL` 字节，POSIX 通常为空。它是并发同步元数据，不是 StageReceipt
  output，也不是业务产物。项目现有 journal 测试已采用“业务文件集合排除 `.writer.lock`”口径，而本集成
  测试遗漏了同一规则。
- 应遵循规则：21-input/29-output 与零额外业务写边界继续严格不变；只从业务 tree signature 中排除 exact
  basename `.writer.lock`，不得放宽 backtest output 或 receipt 路径集合。
- 最小复现：快速 StageRunner snapshot 首发后，`.stage-locks/*/.writer.lock` 恰有一个且为普通非链接文件；
  首发和 resume 使用同一路径。独立 tree-signature 回归证明业务文件被保留、advisory lock 被排除。
- 新增测试：`test_snapshot_stage_first_publish_resume_and_final_verify` 增加唯一锁文件与 resume 复用断言；
  `test_tree_signature_excludes_persistent_advisory_lock` 固定验收 helper 的过滤边界。Windows 定向结果为
  `2 passed`，Ruff 通过。

## 8. R2 通过条件

第 4 节全部条件不变。必须在最终测试版本上重新执行一次完整 300 证券 public CLI，并真实跑到第二次
completed resume 与 fixture teardown；不得把 R1 的首发业务成功和本轮快速测试拼接为整体 PASS。

## 9. R2 启动记录

- 启动时间：2026-08-13 22:49:29（Asia/Shanghai）；
- 唯一 pytest/public CLI 进程 PID：`11444`，包装器 PID：`32000`；
- 状态目录：`artifacts/agent_runs/m3-u13-r2/`；
- 上限：`28800` 秒（8 小时）；启动时已确认 AC 睡眠禁用；
- 资源限制：`BelowNormal`，CPU affinity `255`（最多 8/12 逻辑线程），Polars/OMP 各 4 线程，BLAS 2 线程；
- 2026-08-13 23:17 只读检查为 `RUNNING`，进程正常，未重启、未并发重复。终态前不声明 R2 PASS。

## 10. R2 终态与 R3 最小修正

- R2 唯一 pytest 进程于 2026-08-14 00:20 自然结束：`1 failed`，耗时
  `5451.68s`（`1:30:51`）。public `backtest` CLI 仍为 `code=0`、`reused=false`，规范 JSON、
  G1 零写和业务输出均已通过；失败仍发生在验收 helper 的新文件集合断言之前，
  completed resume 未执行。
- 现象：`_tree_signature` 使用 `str(path.relative_to(root))`，Windows 产生
  `work\\<key>\\backtest\\...`；验收边界使用跨平台 canonical POSIX
  `work/<key>/backtest/...`，因而 29 个合法业务输出和 receipt 全部被误拒。
- 根因：这是验收路径表示未规范化，不是 StageRunner、29-output 集合、receipt
  或经济计算缺陷。
- 应遵循规则：产物相对路径身份在所有平台都用 POSIX `/`；Windows 物理路径
  分隔符不能进入 canonical 集合。
- 最小修正：`_tree_signature` 仅把键改为
  `path.relative_to(root).as_posix()`，同时把快速回归的期望值固定为
  `work/result.json`。不改任何生产代码、文件选择、receipt、fresh verifier 或业务计算。
- 通过条件：快速路径/advisory-lock 回归和静态检查通过后，R3 必须在同一最终
  revision 上重新自然完成一次 public CLI 首发、completed resume、零写边界与 fixture
  teardown；仍不得拼接 R1/R2 的首发成功为整体 PASS。

## 11. R3 终态（2026-08-14）

- 最终 revision：`706ab2cd1f6923fed6eb5b31e78d22bc9d1c3a17`；
- 唯一 pytest/public CLI PID：`10952`，`BelowNormal`，affinity `255`，Polars/OMP 4、BLAS 2；
- 自然终态：`1 passed, 1123808 warnings in 9716.55s (2:41:56)`；stderr 为空；
- 同一测试内部依次断言首次 `reused=false`、completed resume `reused=true`、G1 与 stage business tree 零额外写、canonical JSON 及 `_f0r*` 零残留；fixture teardown 已随 pytest PASS 执行；
- 包装器 `status.json` 的 `exit_code` 为 `null`，属于 PowerShell `Start-Process` 退出对象元数据取值缺口；原始 stdout 明确 pytest PASS、进程已自然退出，未改写原始证据，也未据此放宽业务断言；
- 运行证据目录：`artifacts/agent_runs/m3-u13-r3/`。详见 `M3_G8C_C1_U13_R3_honest300PublicCLI终态报告.md`。
