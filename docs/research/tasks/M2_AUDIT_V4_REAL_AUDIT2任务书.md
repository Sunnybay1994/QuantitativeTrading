# M2-AUDIT-V4-REAL-AUDIT2 真实财务流量语义审计重放任务书

> 状态：`TASKBOOK_READY / CENTRAL_ADMISSION_REQUIRED`
>
> task id：`M2-AUDIT-V4-REAL-AUDIT2`
>
> 规划基线：`f18a8e77f348f581b91c97688d3f098f18033fc5`
>
> supersedes execution：`M2-AUDIT-V4-REAL-AUDIT1 / IDENTITY_CARRIER_STOP / AUDIT_CALL0`
>
> 当前资源：`NONE`；本任务书不授权真实 I/O

## 1. 继承合同与唯一修正

本任务完整继承
[`M2_AUDIT_V4_REAL_AUDIT1任务书.md`](M2_AUDIT_V4_REAL_AUDIT1任务书.md) 的目标、exact data/plan/catalog/code
输入、唯一 public audit 命令、只读数据边界、资源、结果状态机、report-type候选边界、snapshot/R3/PIT STOP、
独立复核和失败保留合同。除本任务书逐项 supersede 的 task id、evidence root、文档路径与 carrier 参数传递外，
R1 全部规则保持逐字有效；实现者/执行者不得重新解释或缩小。

本任务唯一技术修正：PowerShell child helper 的参数名不得使用保留自动变量 `$args`，改为显式非保留名称
`$ArgumentVector`，并在任何 Python 启动前通过无 Python sentinel 证明 `.NET ProcessStartInfo.ArgumentList`
的参数 count、顺序和 UTF-8 bytes 精确。不得借此改变 Python、module、data、threads、verify-bytes、cwd、
PYTHONPATH、priority/affinity或审计经济语义。

## 2. REAL_AUDIT1 永久 STOP 证据

R1 fixed root `artifacts/agent_runs/m2-audit-v4-real-audit1` 已永久占用，只读保留，禁止复用、覆盖、移动、删除
或修补。R1 fresh preflight PASS：main=`f18a8e77f348f581b91c97688d3f098f18033fc5` clean；implementation/config
相对 `e3686880076105c967425f9cc5b9269cb930965f` 漂移 0；plan raw SHA 前缀/文件名闭合，catalog canonical SHA
与 plan 一致；四表各 `COMPLETE=44,296`、total=177,184、noncomplete=0、lease0、Python absent、clean path
absent。ledger pre/post均为 length=101380096、SHA256
`3932b562731ae40446d3ef6afd25ce51161d4df92bf7dc0d5b26b3914812b1a5`、mtime
`2026-08-28T10:55:49.0070156Z`。

R1 首失败发生在 identity helper：形参命名为 PowerShell 自动变量 `$args`，传入数组在函数体内 Count=0，
导致 identity Python 无参数启动并空退出。`01_identity.exit=0` 但 stdout/stderr均0 bytes，随后稳定
`IDENTITY_MISMATCH`；audit call_count=0，未创建任何 `02_audit*` 文件，未取得资源，未读 raw、未写
ledger/raw/clean，未调用 publisher/audit/snapshot/R3/PIT。

R1 evidence SHA256：

- `run_contract.json`：`4b16bac3f4138952017af20e210364001746851787d686fd5dc742d283c8ed6a`；
- identity exit：`9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`；
- identity stdout/stderr empty：`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；
- terminal：`513db643b2a4e3be47722587c1a9d1f486fd6dc96076e0040a3e455511c639dc`；
- carrier failure：`ecbf7a5c589ce4aa51acdfe91d895e8f62375c1631f86baefe44f1a2d4adcfda`；
- resource release：`038e449ac059009eb19001401ae10b589ac5089d416e24cf4a558b8d3b9c3e97`；
- summary：`b21df9aa85ff3c215f31e327670f585e06a3974b4a7dd7d90eaea42c5954cb70`；
- evidence manifest：`014b4719d665c8bc73577980236ec518d39f4dd94e27b1b1124bf4a58ff67c95`。

R1 的权威终态是 `REAL_AUDIT1_EXECUTION_STOP / IDENTITY_CARRIER_STOP / AUDIT_CALL0`；不得因 R2 成功而
删除或改写。

## 3. R2 exact文档与 evidence root

Git 文档唯一写集合：

1. 经理：`docs/research/tasks/M2_AUDIT_V4_REAL_AUDIT2任务书.md`；
2. 执行 owner：`docs/research/deliveries/M2_AUDIT_V4_REAL_AUDIT2交付报告.md`；
3. 独立 reviewer：`docs/research/reviews/M2_AUDIT_V4_REAL_AUDIT2独立复核报告.md`。

R2 fixed root 唯一为：

`F:\AI_Coding\QuantitativeTrading\artifacts\agent_runs\m2-audit-v4-real-audit2`

中央在本任务书 exact1 提交后重新确认该 root absent+ignored；存在即 no-clobber STOP。R1 root 与 M2 audit-v4
开发包的 evidence/temp/cache 全部只读保留，不属于 R2 cleanup 范围。

R2 root 输出集合继承 R1，并在 identity 前新增：

- `00_parser.stdout.log/.stderr.log/.exit`；
- `00_argument_sentinel.ps1`（carrier exact bytes及SHA进入contract）；
- `00_argument_sentinel.stdout.json/.stderr.log/.exit`；
- `00_argument_sentinel_expected.json`。

## 4. carrier parser 与无 Python sentinel

R2 runner 必须先由 PowerShell Parser 零执行解析，errors exact0；parser失败时 Python/audit call均0。runner source
静态拒绝任何函数形参或 child launcher 调用中的 token `$args`；只允许显式 `$ArgumentVector`。

sentinel script 使用
`[Parameter(ValueFromRemainingArguments=$true)][string[]]$ArgumentVector` 接收剩余参数，输出单行canonical JSON，
至少记录 count、逐项原字符串、逐项 UTF-8 byte length 与 SHA256。sentinel known vector必须包含：ASCII module flag、
带空格路径、中文 segment、`--verify-bytes`、数字 `2`。caller 在启动前构造 expected JSON，并用
`ProcessStartInfo.ArgumentList.Add()`逐项加入；stdout/stderr/exit文件在启动前创建。

sentinel child 必须是本地 PowerShell，不得启动 Python、import quant、读取 data/config/ledger/raw或取得0xF00。
exit0后要求 actual count/order/string/UTF-8 bytes/SHA 与 expected逐项相等；stdout nonempty、stderr empty。任何不一致
为 `ARGUMENT_SENTINEL_STOP`，identity/audit call=0，root永久保留。

通过 sentinel 后，identity 与 audit 两个 child 均复用同一个已验证 helper 和 `$ArgumentVector` 传递方式；每次
启动前另将其 exact vector/count/UTF-8 digest 写入 `run_contract.json`。禁止 helper返回隐式pipeline对象；所有
`CopyToAsync/GetResult/Flush/Wait/Dispose` 非合同返回显式 `[void]`，caller持有固定stdout/stderr/exit路径。

## 5. R2 fresh preflight、唯一 audit 与资源

本任务书提交后，中央必须基于新的 latest clean main 重新完成 R1 全部 preflight；不得复用 R1 的动态 ledger、
process 或资源结论。尤其要求：

- implementation/config 相对 `e368688...` 无漂移，taskbook-only main演进不得改变production bytes；
- 四表 exact177184 COMPLETE、noncomplete0、lease0、writer及其他audit/publisher/data Python absent；
- ledger bytes/size/mtime、plan/catalog/interpreter identity fresh记录；clean path presence只记录不读取；
- R2 root absent+ignored；R1 root exists+ignored且内容SHA稳定；main clean/cached0/diff-check；
- sentinel PASS 后，才可申请/设置 BelowNormal/0xF00，并 fresh回读；audit threads exact2、single instance。

唯一真实调用仍为 R1 §3.2 的 public CLI exact一次、`--verify-bytes`。identity成功不计 audit；只有
`quant.data.audit_tushare_financials` main child启动才将 audit call_count从0变1。任何 audit child启动后的失败均
禁止第二次调用；保留原生 stdout/stderr/exit并按R1状态机裁定。

长任务低频等待。资源 finalization、post-state、原生JSON/12 bucket/维度摘要、evidence manifest、report-type候选
和 snapshot/R3/PIT STOP边界全部继承R1。若 carrier收口失败但audit已运行，不得用R2或新root重跑经济调用；只可
另冻不读data的证据收口任务。

## 6. 验收与完成边界

R2执行交付必须同时报告 R1 STOP历史和R2各阶段 call_count；不能只报告最终成功。独立reviewer必须逐SHA读取
R1/R2 roots，并至少增加一个反例：例如把sentinel PASS外推为Python收到参数、把identity exit0空stdout视为PASS、
或在audit已启动后因carrier失败重新调用。

R2的最高状态仍沿R1：只有 top READY、verify_bytes=true、blocking=[]、flow exact12 PASS、
publication_allowed=true 才为 `REAL_AUDIT_PASS_EVIDENCE_READY`；其余按BLOCKED/CONTRADICTED/INSUFFICIENT/
NOT_EVALUATED/EXECUTION_STOP fail closed。即便PASS，也必须先独立evidence review，不自动发布snapshot、选择
allowed_report_types、修改config或启动R3/PIT。C1保持 `BLOCKED_BY_C0`。
