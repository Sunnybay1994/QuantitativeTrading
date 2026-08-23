# M1-U0C 连续五交易日无人干预调度独立初验报告

状态：2026-07-18 独立只读初验 **FAIL**；未触发任务、未访问网络、未修改生产代码/测试/计划任务

## 1. 初验范围与结论

按 [`M1_U0C连续五交易日无人干预调度任务单.md`](M1_U0C连续五交易日无人干预调度任务单.md)
只读核对以下证据：

- `src/quant/data/scheduled_daily.py`
- `src/quant/data/run_scheduled_daily.py`
- `src/quant/data/audit_daily_streak.py`
- `scripts/run_m1_daily_streak.sh`
- `tests/unit/test_scheduled_daily.py`
- `tests/unit/test_daily_streak_audit.py`
- `artifacts/data_quality/m1_daily_streak/20260720_20260724/task_definitions/` 下五份 XML
- 既有 `run_daily.py`、`daily_run.py` 的 receipt 快路径及对应测试
- Windows Task Scheduler 中五个已注册任务的只读状态

结论为 **FAIL**。调度定义、日期、路径、双调用状态机、receipt 快路径和最终离线审计的主体设计均与任务书一致，
但 scheduler wrapper 没有对允许进入日志的 `run_id` 与 `receipt_selector` 做值域约束。一个返回合法三键 JSON、
但把绝对路径或敏感文本放入这两个字段的 runner，会被两次同身份检查接受，随后由 `as_dict()` 原样写入 scheduler
log。这违反任务书“receipt 必须为相对路径、日志禁止绝对路径或 token”的失败关闭要求，故不能关闭预注册初验。

## 2. 已通过的契约映射

### 2.1 Windows 计划任务与导出 XML

五份 XML 分别绑定 2026-07-20 至 2026-07-24，均满足：

- `StartBoundary=YYYY-MM-DDT21:30:00+08:00`；
- `Command=C:\Windows\System32\wsl.exe`；
- 参数固定为 `-d Ubuntu -- bash /home/mabw/AI_Coding_win/QuantitativeTrading/scripts/run_m1_daily_streak.sh YYYY-MM-DD`；
- `MultipleInstancesPolicy=IgnoreNew`；
- `StartWhenAvailable=true`、`WakeToRun=true`；
- 单次 `TimeTrigger`，没有 repetition；没有 `RestartOnFailure`，`RestartOnIdle=false`。

只读查询实际 Task Scheduler 的五个任务得到：均为 `Ready`，action、argument、StartBoundary 与 XML 一致，
`MultipleInstances=IgnoreNew`，`StartWhenAvailable=true`，`WakeToRun=true`，`RestartCount=0`；
`LastTaskResult=267011`（`0x41303`，尚未运行）。本次没有调用 `Start-ScheduledTask` 或其他触发操作。

### 2.2 WSL 入口与单行日志

shell 脚本只接受冻结的五个日期，按脚本自身位置解析项目根目录，固定调用 WSL Miniforge `base`，并传入冻结的
四个证券和 `--without-adjustment-factors`。`set -C` 使每日目标日志只能首次创建；成功时仅在捕获输出恰好一行后
复制，失败时写一行稳定错误 JSON。底层 stderr 被丢弃，脚本没有 `set -x`、环境导出或凭据读取。

### 2.3 SUCCESS → ALREADY_COMPLETE 与零网络快路径

`scheduled_daily.run_scheduled_daily()` 用完全相同 argv 调用 runner 两次，第一次仅接受 `SUCCESS`，第二次仅接受
`ALREADY_COMPLETE`，并要求 `run_id`、`receipt_selector` 两次相等。既有测试覆盖首次即
`ALREADY_COMPLETE`、重放身份不一致、runner 异常脱敏和非 UTC 时钟。

沿生产绑定继续追踪：`run_scheduled_daily` 默认 runner 是 `run_daily.main`；`run_daily.main` 仅在传给
`execute_daily_run()` 的惰性 `update()` 内构造 pipeline/connector。`execute_daily_run()` 在全局 writer lock 内先检查
receipt；receipt 已存在时调用 `verify_daily_receipt()` 并直接返回 `ALREADY_COMPLETE`，不会执行 `update()`。
`tests/unit/test_m1_daily_run.py` 还用 `pytest.fail("completed receipt must not execute update")` 约束该路径，并断言
connector 首次调用后总调用次数保持为一。因此当前生产绑定下第二次调用具备零 API 证据。

### 2.4 最终五日审计

`audit_daily_streak()` 要求恰好五个升序去重日期，并用 clean 日历重新计算同区间共同开市日；逐日重建相同
Tushare、不复权 spec，调用严格 receipt 验证，再要求日志中的 date/run_id/selector 与 spec 和 receipt 闭合。
日志读取拒绝 symlink/非普通文件、额外或缺失字段、多行 JSON、非规范 UTC、逆序时间以及非
`SUCCESS/ALREADY_COMPLETE/exit_code=0`。该审计不构造 connector，也不访问网络。

## 3. 阻断问题与对抗性反例

### 3.1 现象

`scheduled_daily.py` 在确认两次结果身份相同后，只要求 `run_id` 和 `receipt_selector` 的类型为 `str`，没有要求：

- `run_id` 是预期的 64 位小写十六进制；
- `receipt_selector` 精确等于 `run_state/m1_daily/<run_id>/receipt.json`；
- selector 是不含盘符、反斜线、`..` 或绝对根的相对选择器。

随后 `ScheduledDailyResult.as_dict()` 原样输出两值。

### 3.2 根因

实现把生产 `run_daily.main` 当前会返回安全固定格式这一事实，当成 scheduler 日志边界无需独立验证的隐含假设。
但 `run_scheduled_daily()` 本身暴露可替换 runner，且任务书把“日志只允许相对 receipt、不得泄露绝对路径/凭据”
定义为 wrapper 的稳定边界，因此必须在进入最终日志之前 fail closed。

### 3.3 最小反例

构造 runner，让两次都返回退出码 0 和单行三键 JSON：第一次状态 `SUCCESS`，第二次状态
`ALREADY_COMPLETE`，两次都使用相同的：

```text
run_id = "secret-token-text"
receipt_selector = "C:\\Users\\example\\private-token.txt"
```

当前代码会通过状态与同身份检查，返回成功结果；CLI 的最终 JSON 将包含上述绝对路径和敏感文本。该反例不需要
网络、文件写入或真实 connector，且现有测试未覆盖。

### 3.4 应遵循规则与通过条件

应在 scheduler wrapper 的信任边界内验证身份值，而不是依赖下游最终五日审计事后发现。最小修复应同时满足：

1. 两次结果在进入 `ScheduledDailyResult` 前，均要求 `run_id` 为规范 64-hex；
2. selector 必须与该 run_id 精确组成固定相对 selector；
3. 非法值返回稳定脱敏错误，异常没有 cause/context；
4. 新增上述绝对路径/敏感文本反例，证明结果不会进入 stdout；
5. 既有双状态、同身份、零网络和五日审计测试保持通过；
6. 修复后由未参与修复的独立上下文重新初验。

## 4. 验证执行情况

本轮成功执行了只读 Task Scheduler 查询，并完成代码、测试、XML 和既有 receipt 快路径的逐项静态核对。

计划执行的 WSL/Windows 离线 pytest、Ruff、mypy 与 `bash -n` 命令，在启动前被工具执行环境以使用额度限制拒绝；
没有测试进程启动，也没有网络请求。该情况不是代码测试失败，但也不能记为本轮独立实跑通过。实现方此前的绿测
只能作为待复核证据，不能替代本报告要求的独立复跑。由于上节静态反例已足以构成合同违例，本报告仍明确判
**FAIL**，返工复验时须重新运行最小离线测试。

## 5. 未关闭风险

- 五个真实 scheduler run 尚未发生，真实 Gate 仍为 0/5；最早只能在 2026-07-24 当日任务结束并完成最终审计后关闭。
- 任务使用 `InteractiveToken`，可在用户保持登录（包括锁屏）时无人点击运行；它不承诺用户已注销时执行。任务书未要求
  “无论是否登录均运行”，故本轮不据此判失败，但真实五日窗口需保持对应 Windows 用户会话可用。
- `StartWhenAvailable=true` 会在错过计划时间后补启动一次；这符合任务书 missed-start ASAP，但不等同自动 retry。
- 本轮未发现任务书白名单外的修改，也未在受查文件/XML 中观察到真实 token、密码或 API key。

