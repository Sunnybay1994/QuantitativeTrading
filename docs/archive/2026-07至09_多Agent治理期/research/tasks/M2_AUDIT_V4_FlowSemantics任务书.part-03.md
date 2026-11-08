POSTFIX Validation5 使用新的 ignored/no-clobber evidence/temp roots 执行；权威 evidence root 为
`artifacts/agent_runs/m2-audit-v4-postfix-validation5-20260828T162821Z`，temp root 为
`artifacts/validation_tmp/m2-audit-v4-postfix-validation5-20260828T162821Z`。Parser errors=0、identity PASS，
冻结 focused6 全部 PASS（6 passed）；focused6 stdout SHA256 为
`7e2fafef6fcf9fba6825daa9465b55bbf6db0564e46b486565b536ba21959a92`，stderr empty、exit0。mypy
production2 首失败为唯一 audit line 1892 list invariance：
`list[tuple[_FlowObservation,_FlowObservation,_FlowObservation]]` 不能赋给已注解的
`list[tuple[_FlowObservation,_FlowObservation,_FlowObservation | None]]`；mypy stdout SHA256 为
`67e324871a2ea3bdffd10162fdef62bd8ad955b34230fceb666c2ab8ebca371c`，stderr empty、exit1。Ruff、cold、
exact8 scope 均 UNRUN，不得冒充 PASS。

Validation5 runner SHA256 为
`7cc98ca4f66a681bfaa347de5e33150d4932cd42b675617e7ec82c1c7141fe3d`，summary SHA256 为
`8cfb6647088e40e52d0fa153b31ba055425bc711e86f686397f412cefbbd45f2`，runner stderr SHA256 为
`c1a60507145d7c7df86649714c4e1cf606f25b45ce7d96ce8f14b7ae90ba269d`。runner 在 finally 中已先恢复自身
priority/affinity，随后因全局枚举旁观进程的 `ProcessorAffinity` 遇不可读进程而中断；合同内
`resource_release.log` **MISSING**，禁止伪补或把外层旁证冒充该 artifact。外层 fresh 只读核证明退出后
Python/pythonw=0、exact0xF00=0、现有 shell Normal/0xFFF，故资源实际已释放；业务 exact8 未修改，cached0，
ordinary `git diff --check` exit0（仅既有 LF→CRLF warning）。

STATIC_REWORK10 只允许同一原 implementer 修改：

- `src/quant/data/audit_tushare_financials.py`；
- `docs/research/deliveries/M2_AUDIT_V4_FlowSemantics交付报告.md`。

publisher production、tests2、roadmap、taskbook（实现阶段）与 review 均只读。唯一允许的代码修正是把
REWORK9 的 mutable list 注解机械替换为：

```python
numeric_pairs: Sequence[
    tuple[_FlowObservation, _FlowObservation, _FlowObservation | None]
]
```

`Sequence` 已由 audit production 的 `collections.abc` 既有导入；不得新增、删除或改写 import。Q1
comprehension、else `previous_pairs`、后续 `for` 必须逐字保持。该变量只允许保持现有单次只读迭代；禁止
复制、`extend`、cast、Any、type-ignore、运行时容器转换、分支/alias/顺序/None/计数/逻辑变化或 P2 夹带。
原因与通过条件冻结如下：

- **现象**：扩大 tuple 第三元素后，外层 mutable list 仍因 invariance 被 mypy 拒绝；
- **根因**：`list[T]` 不协变，而两分支实际只需要一个只读可迭代接口；
- **应遵循规则**：使用既有 `Sequence[T_co]` 表达唯一消费方式，保留两个实际 list 对象及 alias；
- **最小复现**：Validation5 mypy line 1892 唯一错误；
- **测试**：Validation5 focused6 已 PASS；修正后 Validation6 只重跑两个直接 flow 节点并执行 mypy；
- **通过条件**：mypy production2 PASS，Q1 与 Q2/Q3/FY 的对象、顺序、None、previous cutoff、operand 与计数
  行为不变。

delivery 必须逐项记录上述现象—根因—规则—最小复现—修正—未来通过条件，并诚实保留 Validation5 的
Ruff/cold/scope UNRUN 与 resource-release artifact MISSING 边界。同一原 reviewer 仅写原 review 复验；不得由
实现者或 reviewer 自行启动 Validation6。

POSTFIX Validation6 必须使用新的 no-clobber evidence/temp roots，并修正 carrier 的 resource-finalization：

1. finally 先分别、无条件尝试并持久记录 terminal 状态、owner `$self` priority/affinity 恢复、carrier 已记录的
   known-child PID 全部退出、以及 `Get-Process python,pythonw` presence count；各项使用独立 try/catch，任一
   真实 owner/known-child 恢复失败均明确 STOP，但一个字段失败不得抹除其他已形成 artifact。
2. runner 内只核已授权 owner 与其记录的 child PID；禁止 `Get-Process` 全局枚举后读取所有进程的
   `ProcessorAffinity`。旁观进程权限错误不得遮蔽 owner 已恢复的证据。
3. 全局 exact0xF00 只由 runner 外中央 fresh read-only 旁证并单独持久记录；它不能替代合同内 release artifact，
   也不能反向阻断该 artifact 先形成。

Validation6 顺序冻结为 Parser 零执行门禁 → identity →
`tests/unit/test_audit_tushare_financials.py::test_selection_conflicts_missing_drift_and_chain_have_no_fallback` →
`tests/unit/test_audit_tushare_financials.py::test_flow_and_publisher_bucket_order_is_exact_and_stable` → mypy
production2 → Ruff exact4 → cold → exact8 Unicode/NUL-safe scope、cached0、diff-check、Validation1–6
evidence/temp roots exist+ignored、owner/known-child/Python presence resource artifact 与 runner 外 exact0xF00
旁证。不跑 full tests2。首失败 STOP 并保留证据；全绿也保留证据待经理/中央复核。STATIC_REWORK10 与
review 继续 `STATIC_ONLY / CPU NONE / REAL DATA I/O NONE`：零 Python、pytest、Ruff、mypy、cold、DuckDB、
真实 data/audit/snapshot、network、stage、commit。

### 12.7 Validation6–9 组合证据与最终 evidence-review 边界

Validation6 使用新的 no-clobber evidence/temp roots 执行，evidence root 为
`artifacts/agent_runs/m2-audit-v4-postfix-validation6-20260828T164359Z`，temp root 为
`artifacts/validation_tmp/m2-audit-v4-postfix-validation6-20260828T164359Z`。可信产品阶段全部 PASS：Parser
errors=0、identity PASS、冻结 focused2 PASS、mypy production2 PASS、Ruff exact4 PASS、cold PASS。关键 stdout
SHA256 分别为：focused2
`3ed6fd346dfc27ee652c412ba643af3d0da21f1402843af29da686c1fa3151bf`、mypy
`0c37c4158c91ef55c724ba017bf6465f26018199badb08e3ff13f98acdf056c2`、Ruff
`82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`、cold
`f2fa5abb3a94f7638617a512fe5f805721df611e0918049ef9780a23a332da3b`。runner SHA256 为
`f289fc52c44c43cd6faf290a729de50621261cf6758ad5f8b469b8e5b9d7c493`，summary SHA256 为
`ef8b723f5fdf86f83d5c4b08b75a4f1d5b37417e0d52c893c944bde73521320c`。唯一 STOP 位于 exact8 scope
carrier：合法 NUL 协议终止符形成空尾 record，PowerShell 5.1 的 Split 调用未可靠移除空项，runner 在空项上执行
`Substring(3)` 失败。因此 Validation6 只能记为 `PRODUCT_GREEN / SCOPE_CARRIER_STOP`，不得写成全绿。

Validation6 resource finalization 已按 §12.6 分项持久化并闭合：terminal SHA256
`722594f855bb9a887c3a9c5416e98a87bbfef79d253ae5d93d400abae4cc1003`、self-restored SHA256
`b454c9068b3b6c7fd4106f99da44dbb95a60ece0e816b7b8f9d2c8f8ef2d6037`、known-children SHA256
`edc19edf4c9d775707e2981842dba49711c3dc08f8af5da46b3dd3914d97d100`、python-presence SHA256
`d950b4e86f37941c3520e2f6072e72fac7dd04015e53cf27644030cfef1c1216`、finalization SHA256
`e8a04bf0a88930c2a0d5d2e95cf84b0ed16c357615f11c3e4ca7e2571aec9800`。owner 恢复
Normal/0xFFF，known children started=5/exited=5，Python count=0，finalization errors=0；runner 外 fresh 旁证为
Python=0、exact0xF00=0。该证据不恢复 Validation5 缺失的 resource artifact，也不改变其历史 STOP。

Validation7 evidence root 为
`artifacts/agent_runs/m2-audit-v4-scope-validation7-20260828T164850Z`，summary SHA256 为
`4d150ae26e6b73ff9d36a7fd38ebd638c57bc5d9b8f0509ad40b779512566a69`。它在 scope 前因经理请求额外加入的
“worktree 根级 cache 必须不存在”条件而 STOP；taskbook §12.6 从未冻结该 absent 条件。`.pytest_cache`、
`.ruff_cache`、`.mypy_cache` 均为 ignored validation carrier residue，其中 Ruff/mypy cache 的时间落在 Validation6
窗口。故 Validation7 诚实记为 `PREFLIGHT_STOP / SCOPE_NOT_EVALUATED`，不是产品或 taskbook 合同失败，也不得
删除 cache 后改写历史。

Validation8 evidence root 为
`artifacts/agent_runs/m2-audit-v4-scope-validation8-20260828T165056Z`。baseline cache pre-manifest PASS：
exact 27 files，manifest bytes=2694，manifest SHA256/aggregate digest 均为
`a1fa6231c070d99c22851c1e8828a6d3e63a50c2e86a0899f23e9990d86a59ba`；三目录均 exists+ignored、无
reparse、无额外 root cache。native status 本身 exit0、stderr0、raw stdout 464 bytes，SHA256 为
`c6612035a17758c9081e7facc4d9773af535187dccee39150314d91375b6fb3a`。但 helper 的
`CopyToAsync(...).GetAwaiter().GetResult()` 非路径返回对象污染 PowerShell pipeline，使调用方的 status path
成为多值对象，故 raw NUL 解析及后续 scope UNRUN。runner SHA256
`9f1b06a14fd65e4f9483f2ca06b7d632e49163b93a7296b71f8aa066f8a186a7`，summary SHA256
`440706fcafac64f0c15bf525f4e2cef72e1833de80905095664257dc8d849c0d`。Validation8 只记为
`CARRIER_STOP / SCOPE_NOT_EVALUATED`。

Validation9 使用固定 caller 路径、helper 全部非合同返回显式抑制及显式过滤 NUL 空尾 record，完成无 Python、
无 0xF00 的 baseline-aware scope-only 闭包。evidence root 为
`artifacts/agent_runs/m2-audit-v4-scope-validation9-20260828T165408Z`。cache pre/post 均为 exact 27 files、
2694 bytes、SHA256/aggregate
`a1fa6231c070d99c22851c1e8828a6d3e63a50c2e86a0899f23e9990d86a59ba`，证明 V9 未写 cache。raw NUL
status 464 bytes、SHA256
`c6612035a17758c9081e7facc4d9773af535187dccee39150314d91375b6fb3a`，过滤唯一空尾后逐 record
Length/XY+space 均闭合，decoded exact8 paths SHA256
`c84195caefbeb1da2e69f6fb04411d8da1b22ebbb97844939b14b474850514cf`；exact8 count/set、cached raw
bytes=0、`git diff --check` exit0、V1–V9 evidence roots与V1–V6 retained temp roots exists+ignored 均 PASS。
diff-check stderr 仅既有 LF→CRLF warning，SHA256
`e38e6f6335acd611aaaec8d8c5be4377785b8855f715218ebf1b176dadf0794b`。runner SHA256
`b025ecb61fccbd75e6faafb10319f207883a471906cc062adfab88d807375a2a`，summary SHA256
`afabb0b4c30113db062c0462ea51004ae2908583d39412fdc4775e5d694a5c9c`，terminal PASS SHA256
`c26de83abdc9496cd1301470918ec39ecca1cf389ef0ae1c6504da1800d1c431`，process SHA256
`8393b61af401a68f4b1beb9ba4b3ea40fdab36213c224b8f9af1af1e605b0031`。

权威组合结论仅为：Validation6 产品链绿色 + Validation9 scope 闭包 PASS，形成 Windows development
validation 证据；Validation7/8 的 carrier STOP 历史永久保留。三个根级 tool cache 及全部 V1–V9 evidence/temp
在 final evidence review 与 SAFE_COMMIT 裁定前不得删除。该组合仍不代表真实 audit-v4、snapshot READY、R3
READY、PIT 授权、Linux/WSL Gate 或真实财务数据质量通过。实现者只可在既有 delivery 追加上述证据；同一原
reviewer 随后只写既有 review 做最终 evidence review。二者不得修改 production/tests/taskbook/roadmap、不得运行
Python/检查、不得 stage/commit；最终 review PASS 后才可申请 SAFE_COMMIT。

## 13. 实现、验证和真实数据阶段

### 13.1 STATIC_ONLY

Worker 只实现 exact production2/tests2 并写 delivery；不得运行 Python、pytest、Ruff、mypy、cold、真实 audit
或 snapshot，不得 stage/commit。发现必须扩路径、DuckDB/Parquet 实际类型无法满足本合同、或 v3 语义无法在
safe projection 中保持时，立即 `STOP / CONTRACT_DRIFT`，由经理回中央重冻。

### 13.2 独立初验

STATIC_DONE 且经理 scope/合同核对通过后，由不同上下文只读审查 exact implementation6，唯一写 review。
reviewer 不改 production/test/delivery。P0/P1 退回同一实现链最小返工。

### 13.3 validation-only（另申请）

REVIEW_PASS 后向中央申请唯一 CPU8–11/0xF00 租约，BelowNormal、threads<=2、exact cwd/PYTHONPATH、项目内
ignored basetemp 和持久日志。建议顺序：

1. identity + collect-only；
2. focused audit flow/type/source/safe-union nodes；
3. focused publisher strict validation/audit-SHA nodes及所有既有邻接；
4. Ruff production2+tests2；
5. mypy production2；
6. cold import；
7. exact8 Unicode/NUL-safe scope、cached0、diff-check、temp/process evidence。

失败即 STOP 并保留证据；全绿也先保留日志，经理复核后才申请 SAFE_COMMIT。禁止 full suite、网络、真实
financial I/O、snapshot、PIT 或 PAPER。

### 13.4 真实 audit-v4（实现合流后另冻）

真实 audit 必须基于合流后的 latest clean main、权威 plan/catalog、terminal ledger 与 bytes verify，单次只读、
受控资源执行。结果若 `BLOCKED/INSUFFICIENT/CONTRADICTED/NOT_EVALUATED`，立即保持 snapshot/R3/PIT STOP，
不得按数据调 tolerance/threshold、fallback 或补值；只有 v4 PASS 且 public fresh verifier 闭合后，中央才根据
真实 `allowed_report_types` 证据冻结后续 snapshot/R3。该阶段不包含在本实现任务的资源授权中。

## 14. 交付与完成边界

delivery 必须用“现象—根因—应遵循规则—最小复现—新增测试—通过条件”记录所有返工或 STOP；列出 exact
改动、未运行事项、schema/I/O 边界及剩余平台风险。Worker 完成只回：

`DELIVERY_READY docs/research/deliveries/M2_AUDIT_V4_FlowSemantics交付报告.md`

本包在实现/静态审查阶段的最高状态为 `IMPLEMENTED_PENDING_VALIDATION_AND_REAL_AUDIT`；即使单测全绿也不得
宣称 audit-v4 PASS、snapshot READY、R3 READY 或 PIT 已授权。
