# M2-AUDIT-V4-REAL-AUDIT3 真实财务流量语义审计第二次重放任务书

> 状态：`TASKBOOK_READY / CENTRAL_ADMISSION_REQUIRED`
>
> task id：`M2-AUDIT-V4-REAL-AUDIT3`
>
> 规划基线：`f02bbc561960c5e5cde4905bd7541875242ad85a`
>
> supersedes execution：`M2-AUDIT-V4-REAL-AUDIT2 / PREFLIGHT_CONTRACT_STOP / AUDIT_CALL0`
>
> 当前资源：`NONE`；本任务书不授权真实I/O、Python或audit

## 1. 目标、继承与非目标

本任务在全新no-clobber身份下恢复真实audit-v4。它完整继承
[`M2_AUDIT_V4_REAL_AUDIT1任务书.md`](M2_AUDIT_V4_REAL_AUDIT1任务书.md) 的exact data/plan/catalog/code输入、
唯一public audit命令、只读数据边界、资源、结果状态机、report-type候选、snapshot/R3/PIT STOP、证据与失败保留
合同，并继承
[`M2_AUDIT_V4_REAL_AUDIT2任务书.md`](M2_AUDIT_V4_REAL_AUDIT2任务书.md) 的非`$args` ArgumentList helper、Parser、
argv sentinel、固定输出路径和隐式pipeline返回抑制合同。

本任务唯一合同修正是把fresh准入分层为：root前零Python静态准入 → 创建R3 root → Parser/argv sentinel → identity →
固定Windows Python窄SQLite只读preflight → 资源获取 → 唯一audit。除task id、root、文档路径与该顺序外，R1/R2
合同不得重新解释或缩小。

非目标：不修改production/config/tests/roadmap；不发布snapshot；不选择或写入`allowed_report_types`；不启动R3/PIT；
不恢复writer；不读取financial clean；不写ledger/raw/clean；不运行第二次audit；不清理R1/R2或开发包证据；C1保持
`BLOCKED_BY_C0`。

## 2. R1/R2永久历史

R1 fixed root `artifacts/agent_runs/m2-audit-v4-real-audit1` 已永久占用并只读保留。其权威终态为
`REAL_AUDIT1_EXECUTION_STOP / IDENTITY_CARRIER_STOP / AUDIT_CALL0`：PowerShell helper误用自动变量`$args`，identity
Python无参数空退出；未运行audit、未读raw、未写数据。R1 summary SHA256为
`b21df9aa85ff3c215f31e327670f585e06a3974b4a7dd7d90eaea42c5954cb70`，evidence manifest SHA256为
`014b4719d665c8bc73577980236ec518d39f4dd94e27b1b1124bf4a58ff67c95`。

R2 taskbook已由commit `f02bbc561960c5e5cde4905bd7541875242ad85a`冻结。中央在创建R2 root前发现合同冲突并
首失败STOP：root absent阶段须完成fresh SQLite动态preflight，同时sentinel PASS前禁止任何Python；但主机没有可用
非Python SQLite authority。`Get-Command sqlite3`为空，候选`D:\Miniforge3\Library\bin\sqlite3.exe`、
`D:\Miniforge3\Scripts\sqlite3.exe`、`C:\Windows\System32\sqlite3.exe`均不存在，PowerShell无可用
`Microsoft.Data.Sqlite`或`System.Data.SQLite`provider。R2终态为
`REAL_AUDIT2_PREFLIGHT_CONTRACT_STOP / ROOT_ABSENT / PYTHON0 / SQLITE0 / AUDIT_CALL0`；未创建evidence，未读
data/ledger/raw/clean，未取得资源，main保持clean/cached0。

R1 root禁止复用、覆盖、移动、删除或修补。R2 fixed root
`artifacts/agent_runs/m2-audit-v4-real-audit2`即使仍absent也已属于已终止任务身份，永久禁止创建或复用。禁止通过
P/Invoke、Add-Type、猜测SQLite ABI或复用R1动态ledger结论绕过R2合同STOP。

## 3. exact文档、fixed root与输出

Git文档唯一写集合：

1. 经理：`docs/research/tasks/M2_AUDIT_V4_REAL_AUDIT3任务书.md`；
2. 执行owner：`docs/research/deliveries/M2_AUDIT_V4_REAL_AUDIT3交付报告.md`；
3. 独立reviewer：`docs/research/reviews/M2_AUDIT_V4_REAL_AUDIT3独立复核报告.md`。

R3 fixed root唯一为：

`F:\AI_Coding\QuantitativeTrading\artifacts\agent_runs\m2-audit-v4-real-audit3`

正式准入须确认它absent+ignored；存在即no-clobber STOP。R1 root必须exists+ignored且冻结SHA稳定；R2 root必须absent，
不得把R2 absence解释成可复用。开发包V1-V9 evidence、V1-V6 temp、三个tool cache和source退休残留全部只读保留。

R3输出继承R1集合，并在audit前至少固定预建：

- `00_parser.stdout.log/.stderr.log/.exit`；
- `00_argument_sentinel.ps1`、`00_argument_sentinel_expected.json`；
- `00_argument_sentinel.stdout.json/.stderr.log/.exit`；
- `01_identity.stdout.json/.stderr.log/.exit`；
- `01_sqlite_preflight.stdout.json/.stderr.log/.exit`；
- `run_contract.json`、`terminal.json`、`resource_release.json`、`evidence_manifest.json`。

所有文件no-clobber；stdout/stderr/exit在child启动前创建。任何STOP永久保留R3 root及已形成证据，不覆盖、不补写不存在的
产品结果、不删除后重试。

## 4. 唯一可执行顺序

### 4.1 root前零Python静态准入

中央基于提交本任务书后的latest clean main fresh验证：

- main/production/config/taskbook身份、tracked clean、cached0、`git diff --check`；
- R3 root absent+ignored，R1 root exists+ignored且冻结证据稳定，R2 root absent；
- exact project/data/ledger/plan/catalog/interpreter路径与全部ancestor为plain、non-reparse且path-contained；
- plan/catalog/interpreter静态bytes identity、implementation/config相对`e3686880076105c967425f9cc5b9269cb930965f`漂移0；
- Python/pythonw、writer、audit/publisher/data Python进程均不存在，0xF00可用；
- clean path仅记录presence，不读取内容。

此阶段不得启动Python、不得打开SQLite、不得读取raw/clean、不得创建R3 root。任一失败保持root absent并以
`STATIC_PREFLIGHT_STOP / PYTHON0 / SQLITE0 / AUDIT_CALL0`收口。

### 4.2 创建root、Parser与argv sentinel

静态准入PASS后才原子创建R3 root并预建固定输出。runner先由PowerShell Parser零执行解析，errors exact0；静态拒绝
函数形参或launcher token`$args`，只允许`$ArgumentVector`。

sentinel使用`[Parameter(ValueFromRemainingArguments=$true)][string[]]$ArgumentVector`，以本地PowerShell接收包含ASCII、
带空格路径、中文、`--verify-bytes`和数字`2`的known vector，输出canonical JSON。必须逐项闭合count、原字符串、UTF-8
byte length与SHA256；stdout nonempty、stderr empty、exit0。所有`CopyToAsync/GetResult/Flush/Wait/Dispose`非合同返回
显式`[void]`，caller只使用固定输出路径。sentinel不得启动Python或读取data/config/ledger/raw/clean。

Parser或sentinel失败：SQLite/identity/audit call均0，root永久保留并STOP。

### 4.3 identity

sentinel PASS后，以同一已验证ArgumentList helper启动exact `D:\Miniforge3\python.exe`一次identity child；必须验证
stdout nonempty、stderr empty、exit0、`sys.executable`与解释器exact path一致，audit module与publisher module均来自
latest main exact workspace。identity失败时SQLite/audit call均0，root永久保留。

identity只验证运行身份，不import或执行audit main，不读取SQLite/raw/clean，不取得0xF00。

### 4.4 fixed Windows Python窄SQLite只读preflight

identity PASS后，允许且只允许同一exact Windows Python启动一次独立窄SQLite child。它使用SQLite URI read-only连接
`data/run_state/tushare_bulk/state.sqlite`，在单一只读transaction中只查询四dataset状态聚合和lease；不得import项目
audit/publisher模块，不得读取raw/clean，不得写数据库。

preflight必须fresh证明：balancesheet、cashflow、fina_indicator、income各`COMPLETE=44296`，合计177184；
`PENDING/RUNNING/RETRYABLE/FAILED/SPLIT_REQUIRED`全0；lease rows=0、active lease=0。ledger在child前后length、SHA256、
mtime逐字稳定；stdout为nonempty canonical JSON、stderr empty、exit0。其exact vector/count/UTF-8 digest和输出SHA进入
`run_contract.json`与evidence manifest。

任一启动、identity、解析、计数、transaction、只读模式或ledger稳定性失败，R3 root永久保留并以
`SQLITE_PREFLIGHT_STOP / SQLITE_PREFLIGHT_CALL1 / AUDIT_CALL0`收口；禁止进入资源获取或audit，禁止第二次SQLite
preflight。该Python child不计audit call，成功也不得外推为audit成功。

### 4.5 资源与唯一audit

SQLite preflight PASS后才可取得唯一资源租约：owner/known child为单实例，BelowNormal、affinity exact0xF00、numeric
threads<=2；设置后fresh回读。随后只允许R1冻结的public CLI exact一次：

```text
D:\Miniforge3\python.exe -m quant.data.audit_tushare_financials
  --data-root F:\AI_Coding\QuantitativeTrading\data
  --plan-report F:\AI_Coding\QuantitativeTrading\data\run_state\tushare_bulk\plan_reports\20260815T094124.671741Z-a227e9cc51f5.json
  --catalog F:\AI_Coding\QuantitativeTrading\configs\data\tushare_bulk_v1.toml
  --threads 2
  --verify-bytes
```

public parser不接受`--ledger`，audit ArgumentList严禁加入该参数。ledger只由§4.4窄SQLite preflight直接只读，并由
public audit基于absolute `--data-root`按production合同内部派生；carrier不得把ledger另注入audit CLI。

exact cwd为项目根，PYTHONPATH指向latest main `src`；ArgumentList逐项传递。`run_contract.json`必须在audit启动前记录
上述exact vector、count、逐项UTF-8 bytes digest及aggregate digest，并与sentinel已证明的helper输入逐项闭合。只有audit
main child启动时audit call_count从0变1。audit启动后的任何产品、carrier、证据或finalization失败均禁止第二次经济
调用；低频等待并保留原生stdout/stderr/exit。不得调用publisher、不得创建snapshot、不得运行R3/PIT。

resource finalization须分别持久化terminal、owner restored、known children exited、Python presence与errors；仅核授权owner
及记录child PID，不因不可读旁观进程遮蔽产品终态。最终中央另做0xF00 fresh只读旁证。

## 5. 结果状态机与证据

最高状态仅在原生audit JSON同时满足以下条件时为`REAL_AUDIT_PASS_EVIDENCE_READY`：top status=`READY`、
`verify_bytes=true`、`blocking_issues=[]`、`flow_semantics.status=PASS`、固定12 buckets exact集合/顺序且全PASS、
`publication_allowed=true`，并闭合三statement dimension evidence、source type evidence、ledger post-state与资源释放。

top `BLOCKED`、flow `CONTRADICTED`或`INSUFFICIENT`、前置不足导致`NOT_EVALUATED`、JSON/identity/bytes/资源/evidence
不闭合或进程失败均fail closed并按R1状态机报告；不得调容差、改数据、重跑或把partial bucket表述成PASS。audit调用前
STOP须明确SQLite/identity/audit call_count；audit调用后STOP也必须诚实保留call_count=1。

执行owner只写R3 delivery；独立reviewer须逐SHA读取R1 root、R2合同STOP和R3 root，至少补一个对抗反例，例如把
identity PASS外推为SQLite PASS、把SQLite PASS外推为audit PASS，或在audit已启动后因证据收口失败重跑。

即使`REAL_AUDIT_PASS_EVIDENCE_READY`，也只允许进入独立evidence review；不得自动发布snapshot、选择或写入
`allowed_report_types`、修改config、启动R3/PIT。真实snapshot及后续链必须由中央另行冻结。C1继续
`BLOCKED_BY_C0`。
