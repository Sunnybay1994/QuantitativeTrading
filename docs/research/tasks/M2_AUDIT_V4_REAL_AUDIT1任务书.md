# M2-AUDIT-V4-REAL-AUDIT1 真实财务流量语义审计任务书

> 状态：`TASKBOOK_READY / CENTRAL_ADMISSION_REQUIRED`
>
> task id：`M2-AUDIT-V4-REAL-AUDIT1`
>
> 规划基线：`e3686880076105c967425f9cc5b9269cb930965f`
>
> 结论上限：`REAL_AUDIT_EVIDENCE_READY / IMPLEMENTED_PENDING_REAL_AUDIT_REVIEW`
>
> 当前资源：`NONE`；本任务书不授权真实 I/O

## 1. 目标、前置和非目标

本任务只在中央另行冻结的 latest clean main 上，对已经权威 terminal 的 Tushare 财务四表执行一次只读、
bytes-verified 的 audit-v4，形成不可覆盖的原生审计证据。它消费已经合流的
`quant.data.audit_tushare_financials`，不再修改 production、tests、config、ledger、raw 或 clean。

权威前置来自既有治理 SSOT：

- `balancesheet/cashflow/fina_indicator/income` 各 `COMPLETE=44,296`，合计 `177,184`；
- `PENDING/RUNNING/RETRYABLE/FAILED/SPLIT_REQUIRED=0`，active lease=0，writer/Python absent；
- UA-M2-001 recovery2 terminal SHA256 为
  `33655f1f15144551cd536610cac033534047341f39419452c84e325df4a1691b`；post-terminal result SHA256 为
  `7757a3c40526121cb26b2d087a81b14885968c37f96f2db89fd5ddae1c079386`；
- audit-v4 implementation source `673d8bb3942dab3b32dbfdff44ca2d872d7d962c` 已 no-ff 合流到规划基线
  `e3686880076105c967425f9cc5b9269cb930965f`，Windows integration 为 54 tests PASS、Ruff/mypy/cold PASS。

本任务不发布 financial snapshot，不调用 publisher，不修改 `allowed_report_types` 或 PIT config，不启动 R3、
PIT、research trial、PAPER 或 writer。audit 结果即使 PASS，也只能进入独立 evidence review 和下一任务冻结，
不能自动串接 snapshot。

## 2. 文档 owner 与 exact Git 写集合

规划/执行闭环只允许以下文档路径；运行证据写入第 4 节 ignored root，不属于 Git：

1. 经理：`docs/research/tasks/M2_AUDIT_V4_REAL_AUDIT1任务书.md`；
2. 执行 owner：`docs/research/deliveries/M2_AUDIT_V4_REAL_AUDIT1交付报告.md`；
3. 独立 evidence reviewer：`docs/research/reviews/M2_AUDIT_V4_REAL_AUDIT1独立复核报告.md`。

本轮经理只写第 1 路径。中央必须先以 exact1 安全提交本任务书，再基于新的 latest clean main 冻结执行 SHA；
不得在 dirty main 上运行 audit。执行/复核文档必须分别由不同 owner 写入，不得修改代码、测试、配置或 roadmap。

## 3. exact 输入与唯一命令

### 3.1 输入身份

中央执行冻结时必须逐项记录 absolute resolved path、plain regular/directory 边界、bytes/size/SHA256（适用时）：

- project root：`F:\AI_Coding\QuantitativeTrading`；
- data root：`F:\AI_Coding\QuantitativeTrading\data`；
- ledger：`F:\AI_Coding\QuantitativeTrading\data\run_state\tushare_bulk\state.sqlite`；
- plan report：
  `F:\AI_Coding\QuantitativeTrading\data\run_state\tushare_bulk\plan_reports\20260815T094124.671741Z-a227e9cc51f5.json`；
- catalog：`F:\AI_Coding\QuantitativeTrading\configs\data\tushare_bulk_v1.toml`；
- interpreter：中央 fresh 核定的 Windows Miniforge Python；必须记录 resolved path、size、SHA256 和
  `sys.executable`；
- executable code：必须从中央提交本任务书后的 latest clean main 加载；identity probe 要求
  `quant.data.audit_tushare_financials.__file__` 位于该 main，且 production/test/config bytes与 merge
  `e3686880076105c967425f9cc5b9269cb930965f` 对应路径无漂移。任何 source/config 漂移先 STOP 重冻，不能把
  旧开发验证自动绑定到新字节。

不得预先遍历或抽样 raw 来“看看结果”。raw 文件、metadata、canonical instrument inventory 与 ledger 只能由
public audit 调用链按已合流合同读取；carrier 不复制第二套 request/raw 选择逻辑。

### 3.2 唯一经济调用

真实数据调用 exact 一次：

```text
<python> -m quant.data.audit_tushare_financials
  --data-root <absolute data root>
  --plan-report <absolute plan report>
  --catalog <absolute catalog>
  --threads 2
  --verify-bytes
```

必须使用 `.NET ProcessStartInfo.ArgumentList` 逐参数传递，禁止拼接 shell command、重定向字符串、环境变量猜路径
或第二次 audit。`PYTHONPATH` 只绑定 exact main 的 `src`；凭据/token 不属于输入，也不得读取、输出或记录。

## 4. exact evidence root 与输出集合

唯一 evidence root 固定为：

`F:\AI_Coding\QuantitativeTrading\artifacts\agent_runs\m2-audit-v4-real-audit1`

正式准入前该路径必须不存在且由 Git ignore；存在即 `NO_CLOBBER_STOP`，不得复用、删除或改名后继续。root 由
中央 carrier 创建一次，至少包含：

1. `run_contract.json`：execution main SHA、输入路径/size/SHA、解释器身份、命令 ArgumentList、资源合同；
2. `01_identity.stdout.log`、`01_identity.stderr.log`、`01_identity.exit`；
3. `02_audit.stdout.json`、`02_audit.stderr.log`、`02_audit.exit`；stdout/stderr/exit 在 child 启动前无条件创建；
4. `03_post_state.json`：ledger bytes/size/mtime、四表状态/lease、writer/Python absence、clean path presence 的
   pre/post 只读对照；不得包含 token、raw 行或配置内容；
5. `04_result_identity.json`：stdout bytes/size/SHA256、UTF-8/JSON/schema、关键顶层/flow/dataset维度摘要；
6. `terminal.json`、`summary.log`、`resource_release.json` 及所有文件的 `evidence_manifest.json`。

`02_audit.stdout.json` 是唯一权威 audit bytes；不得 pretty-print、删字段、改序、二次生成后冒充原生结果。
carrier 可以在进程自然退出后只读解析并写 `04_result_identity.json`，但不得再次调用 audit 或打开 raw。任何解析
失败都保留原 stdout/stderr 并 STOP。

DuckDB 使用 in-memory connection；若运行在 project cwd 产生新的 `.tmp`、cache 或其他未批准 root entry，必须
记录为 carrier residue 并 STOP，不得清理后冒充无写。中央可在执行前把 process cwd 冻结到 evidence root、同时
以 exact `PYTHONPATH` 绑定 main，从而把可能的临时文件限制在 evidence root；无论选择哪种 cwd，都必须在
`run_contract.json` 逐字记录并在执行前证明 import identity。

## 5. fresh preflight 与资源合同

正式 audit 前只允许 read-only preflight：

1. execution main HEAD/cached/status/diff-check clean；production/config identity闭合；evidence root absent+ignored；
2. plan/catalog/ledger/data root path-contained、plain、非 symlink/reparse；plan/catalog SHA 与治理 SSOT/plan内部
   identity闭合；
3. 同一 SQLite read-only transaction确认 exact `177,184 COMPLETE`、所有 noncomplete=0、active lease=0；
4. 按命令行/模块身份确认 writer absent；确认没有其他 audit/publisher/Python data process；
5. `data/clean/tushare_financials` 的 pre-presence 只记录，不读取；本任务不得创建或修改它；
6. 记录 ledger pre bytes SHA/size/mtime；禁止 reset、VACUUM、checkpoint、状态更新或恢复 writer。

资源由中央另授唯一 run-only 租约：Windows Miniforge、BelowNormal、CPU8–11/affinity `0xF00`、numeric
threads<=2、single instance。carrier 在 child 启动前 fresh 回读 priority/affinity；失败即 STOP 且 audit call=0。
长运行按预计窗口低频等待，不做分钟级空日志轮询；除非明确卡顿，仅做一次 PID/CPU/内存只读诊断。

resource finalization 必须先分项持久化 terminal、owner restored、known-child exit、Python presence，再由中央 runner
外核 `0xF00`。carrier/resource 收口若在 audit 后失败，不得重跑 audit；保留已生成的原生 stdout，另冻纯证据收口。

## 6. 结果验证与唯一状态机

audit child exit 非 0、stderr出现 traceback/error、stdout为空/非严格 UTF-8/非 JSON、schema 不等于
`tushare-financial-raw-audit-v4`，均为 `REAL_AUDIT_EXECUTION_STOP`。不得自动重试、fallback 到
`verify_bytes=false`、缩小 raw、改变 threads/tolerance 或改用 publisher。

exit0 后只读核 exact 顶层：

- `verify_bytes is true`；
- `active_lease_count == 0`；
- 四 dataset exact set，各 request/status/complete/quality evidence按v4合同存在；
- `flow_decimal_absolute_tolerance == "0.01"`；12 bucket exact集合与顺序、source-type evidence SHA、漏斗守恒；
- `blocking_issues`、`status`、`flow_semantics.status`、`publication_allowed` 交叉一致；
- pre/post ledger SHA/size/mtime及四表状态一致，writer仍 absent；clean path 未被本任务创建/修改。

终态只能是：

- `REAL_AUDIT_PASS_EVIDENCE_READY`：仅当 top status=`READY`、verify_bytes=true、blocking_issues=[]、
  flow status=`PASS`、exact12 buckets全PASS且 `publication_allowed=true`；
- `REAL_AUDIT_BLOCKED`：top status=`BLOCKED`，或 required source type untokenizable/基础质量失败；
- `REAL_AUDIT_CONTRADICTED`：任一 comparable economic mismatch使flow=`CONTRADICTED`；
- `REAL_AUDIT_INSUFFICIENT`：flow=`INSUFFICIENT`；
- `REAL_AUDIT_NOT_EVALUATED`：flow=`NOT_EVALUATED`；
- `REAL_AUDIT_EXECUTION_STOP`：进程、identity、bytes、schema、carrier或post-state闭包失败。

除第一种外全部保持 snapshot/R3/PIT STOP；任何状态都不得按真实结果调整 tolerance、coverage、minimum symbols、
fiscal years、numeric grammar、cent-resolution或冲突规则。

## 7. report-type evidence 与后续 Gate

`04_result_identity.json` 必须原样摘要 `balancesheet/cashflow/income` 的 `report_type_counts`、`comp_type_counts`、
`report_type_comp_type_counts`，以及 `fina_indicator` 的 exact empty dimension evidence。它只提供候选分布，不在本
任务自动选择或写入 `configs/research/m2_pit_quality_factors.toml`。

只有 `REAL_AUDIT_PASS_EVIDENCE_READY` 且独立 reviewer 逐 SHA/漏斗/12 bucket/维度分布复核 PASS 后，中央才能
另立任务冻结 singleton `allowed_report_types`。若三个 statement dataset不能形成同一、唯一、可解释的
report_type候选，保持 R3 STOP 并请求业务裁定；禁止按行数最大、收益、后续 PIT coverage 或实现便利猜值。

snapshot publisher 是再下一独立任务：必须消费原生 audit SHA，使用 public strict validator，pre-mkdir
fail-closed。real-audit1 不创建 snapshot root、不调用 publisher，也不把 `publication_allowed=true` 等同于 snapshot
已经发布。

## 8. 独立复核、失败保留和提交边界

执行 owner 只写 delivery，逐项记录输入 identity、命令、资源、每阶段 exit、全部 evidence SHA、原生顶层/12
bucket/维度摘要、STOP/PASS 与未运行边界。不同上下文 reviewer 只写 review，并至少补一个对抗反例：例如把
flow PASS 与 top BLOCKED 混为 publication READY、删掉失败 bucket、用最大 report-type替代 singleton、或用
pretty-printed JSON SHA冒充原生 stdout。

任何失败保留整个 evidence root、stderr、partial stdout和资源证据；禁止删除、覆盖、重跑或发布 snapshot。
review PASS 后才允许中央 exact3 文档 SAFE_COMMIT。真实 audit evidence root 至少保留到 audit文档提交、后续
singleton裁定与snapshot任务冻结完成；清理须另有精确授权，不能随 source worktree 退休间接删除。

本任务书提交、执行、复核均不改变当前事实：M2-EVAL-STOP-001仍OPEN，R3/snapshot/PIT未获授权，C1继续
`BLOCKED_BY_C0`。
