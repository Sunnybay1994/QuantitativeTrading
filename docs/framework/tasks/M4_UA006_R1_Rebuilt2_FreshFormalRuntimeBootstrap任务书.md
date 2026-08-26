# M4-UA006-R1 Rebuilt2 Fresh Formal Runtime Bootstrap 任务书

状态：`FRESH_FORMAL_BOOTSTRAP_WINDOWS_ENGINEERING_VALIDATED`（Windows 工程验证闭合；**UA-M4-006 / PAPER / soak / Linux Gate 仍 OPEN**）

## 1. 身份与目标

- task id：`M4-UA006-R1-REBUILT2-FRESH-FORMAL-RUNTIME-BOOTSTRAP`
- exact base：`9cc5b56d176a18aa468386b369d550be73051edb`
- branch：`codex/m4-ua006-r1-fresh-formal-runtime-bootstrap-rebuilt2`
- worktree：`artifacts/dev_worktrees/m4-ua006-r1-fresh-formal-runtime-bootstrap-rebuilt2`
- 目标：消费已合流 P1 canonical LF config 与 P2 formal broker materialization compatibility，提供新 root/new epoch 的 fail-closed formal runtime bootstrap。
- 退出状态上限：`FRESH_FORMAL_BOOTSTRAP_STATIC_DELIVERED`；Windows 主验后最多 `FRESH_FORMAL_BOOTSTRAP_WINDOWS_ENGINEERING_VALIDATED`。

旧 R1 与 R1-rebuilt 为事故/CONTRACT_STOP 现场，只读保留。不得复制旧 runtime root、验证产物或失效 fixture；只可参考任务文档中的问题边界。

本包不创建真实 formal root/epoch，不运行 PAPER、soak、network 或真实 worker；`UA-M4-006` 始终 OPEN。

## 2. exact7 与职责

1. `src/quant/execution/paper_formal_bootstrap.py`（new）
2. `src/quant/execution/__init__.py`
3. `tests/unit/test_paper_formal_bootstrap.py`（new）
4. `tests/integration/test_paper_formal_bootstrap.py`（new）
5. `docs/framework/tasks/M4_UA006_R1_Rebuilt2_FreshFormalRuntimeBootstrap任务书.md`
6. `docs/framework/deliveries/M4_UA006_R1_Rebuilt2_FreshFormalRuntimeBootstrap交付报告.md`
7. `docs/framework/reviews/M4_UA006_R1_Rebuilt2_FreshFormalRuntimeBootstrap独立初验报告.md`

经理唯一写 5；外部实现者只写 1–4、6；不同全新外部 reviewer 只写 7。禁止修改 broker store、policy/account loader、config、schema、migration、ExecutionStore/PaperBrokerStore、session barrier、formal composition、roadmap或共享 SSOT。

## 3. 输入与 root topology

- 唯一输入至少包含 current-platform exact concrete absolute `config_path: Path` 与显式 UTC `now`；拒绝 Path subclass、PurePath、relative、symlink/reparse/junction、非普通文件及读取前后漂移。
- config 必须由现有 public loader读取；canonical bytes/SHA进入 bootstrap identity。不得从 env/CLI默认发现，不得归一化 CRLF/BOM或接受第二表达。
- 五个 runtime roots 必须位于同一固定 NTFS parent 下，为 exact siblings、绝对、非nested、非project-root、非system-temp、非symlink/reparse/junction；parent真实存在且identity稳定。
- 所有目标 root 初始必须不存在；未知文件、partial root、跨parent、identity漂移均在 initializer 前 fail closed。
- Windows验证 basetemp也必须同卷、project外、非system-temp、no-clobber；测试不得 patch `_actual_project_root` 或 `_system_temp_root`。

## 4. public bootstrap sequence

bootstrap 只能组合已合流 public API，并在单一显式顺序内：

1. fresh加载 canonical config并构造 policy/account/runtime identities；
2. 创建并验证 formal session barrier，固定 new root、new epoch、session/account/store/gateway/config/lock-root身份；
3. 通过 public initializer分别建立 formal OMS 与 broker store；P2允许首次 broker root materialization时环境/attestation identity变化，但经济 policy/binding/account字段必须保持；
4. fresh verifier重新验证 materialized chain，最终 capability必须绑定新materialized identity；不得接受 cold/stale对象；
5. 返回 frozen、不可序列化/伪造的强类型 bootstrap result/capabilities；不得返回raw token、secret、SQLite connection或private store对象。

禁止 raw SQLite、private store旁路、caller bool/token、重复初始化器、手工 descriptor/row/receipt、旧 root adoption 或异常后补完。

## 5. 事务、rollback 与 reopen

- 每个 public initializer 的事务/锁语义保持原实现；bootstrap不得复制事务或绕过 shared barrier。
- initializer失败时只可精确回滚由本次创建、identity闭合且不含 broker正式bytes的路径。
- 未记录 WAL/SHM、broker正式bytes、ownership不明或cleanup失败时稳定返回人工清理错误；禁止递归删除 parent、静默 adopt或伪成功。
- exact reopen仅接受完整 OPEN bundle且所有fresh identities闭合，不得重跑 initializer或产生新经济影响。
- partial root、identity drift、CLOSING、CLOSED均拒绝；CLOSING/CLOSED反例只使用现有 public terminal transition链，不得raw token/SQLite/private store造状态。

## 6. P1/P2前置不变量

1. P1：两个版本化 formal TOML保持 repository/index/worktree canonical LF bytes；bootstrap不得文本归一化或复制配置。
2. P2：cold→materialized比较只允许环境派生/attestation字段变化；稳定经济语义必须相等。
3. materialized tuple必须经过现有 public fresh preflight，再验证physical root存在；不得仅凭目录存在接受。
4. final capability必须来自最新materialized chain；stale cold policy/binding/account、错 source/config/schedule/account runtime字段均拒绝。
5. bootstrap不得修改或复述 P2投影逻辑；只消费 public initializer/verifier结果。

## 7. 必测反例

至少覆盖：

1. config Path subclass/PurePath/relative/symlink/reparse、CRLF/BOM/noncanonical、读取前后漂移；
2. 五 root少/多/nested/cross-parent/project-root/system-temp/symlink/reparse、partial/unknown existing root；
3. public verifier wrapper/lambda替换、错类型、等值但stale、policy/binding/account/materialized identity漂移；
4. 首次 public broker materialization正向，环境identity变化但经济字段不漂移；经济source/config/schedule/account字段漂移拒绝；
5. initializer中途失败的精确rollback、unknown sidecar/broker正式bytes导致人工清理边界、无parent递归删除；
6. exact OPEN reopen零initializer/零写；partial、CLOSING、CLOSED、wrong epoch/session/account/store/gateway/config拒绝；
7. object construction/replace/copy/pickle/伪capability、raw token、bool或private store旁路拒绝；
8. 返回bundle中所有capability identity逐项闭合，错误码稳定且不泄露路径/config bytes。

reviewer 必须增加实现者未用对抗，优先挑战 TOCTOU、partial root、capability forgery、P2 stale cold对象与 rollback ownership。

## 8. 实现、验证与 STOP

STATIC_ONLY 阶段禁止 Python/pytest/Ruff/mypy/cold/SQLite probe、真实 root/PAPER/soak/network/worker、stage/commit。实现者在 delivery 记录逐路径变化、全部 UNRUN 项，以及“现象—根因—应遵循规则—最小复现—新增测试—通过条件”。

静态完成后由未参与实现的全新外部 reviewer 只读 1–6、唯一写 7。REVIEW_PASS 后另申请 Windows资源，建议顺序：identity → focused unit+integration → Ruff production2+tests2 → mypy production2 → cold production2 → exact7 scope/diff/temp/process。basetemp必须使用中央批准的同卷项目外非system-temp no-clobber根。

以下任一立即 STOP：exact7不足；需要修改 broker store/policy/account/config/schema/migration/barrier/formal composition；public P2 API仍不能完成首次materialization；ownership/rollback无法证明；base/branch/worktree漂移；第二 writer；白名单外 dirty。不得自行扩围或用private字段/伪对象绕过。

## 9. STATIC_REWORK1：bootstrap 组合根 identity 与对抗闭包

首轮独立初验结论为 `REVIEW_FAIL / P1×1 + P2×4`。批准同一原实现者在 exact7 内 STATIC_ONLY 返工；review 报告在交付前只读，完成后交回同一 reviewer 复验。不得运行 Python/SQLite 或修改 broker/P2 等只读模块。

### F1 — broker capability 与 materialized chain 字段级闭包

mint 与最终 result 必须逐项证明：

- broker runtime environment identity == materialized environment verification identity；
- broker execution policy identity == materialized policy identity；
- broker binding identity == materialized binding identity；
- broker account verification identity == materialized account verification identity；
- broker runtime config identity == materialized config identity；
- broker session date/account/gateway等公开稳定字段与 chain/result exact 相等。

任一分叉稳定 STALE/INVALID；不得只检查非空、总 capability identity或对象 `is`。增加 forged broker↔chain字段分叉反例与正向逐字段断言。不得复制 P2 私有经济投影。

### F2 — fresh materialized chain不得回灌 cold对象

- `_reload_materialized_chain` 返回后，environment/policy/binding/account必须是fresh materialized身份；policy、binding、account均不得继续等于cold身份。
- 使用各public对象公开字段建立完整 join：binding→environment/policy、account→binding/policy/config/session/account；仅使用公开API/字段，不读取 P2 私有 helper或复制经济投影。
- verifier透传、cold policy/binding/account回灌时，在OMS initializer前稳定拒绝，OMS调用0/零写。

### F3 — OPEN barrier身份集合完整

reopen的 OPEN 闸必须逐项闭合 barrier epoch、session date、account、OMS store、broker store、gateway、config、lock identity与当前 capability/result。不得只核子集或信任 state 字符串。

增加参数化 wrong epoch/session/account/OMS store/broker store/gateway/config/lock identity反例；均零initializer、零写。若public open verifier已完全闭合某字段，也须测试通过真实public路径证明，不能删去 bootstrap 闸后仅口头声明。

### F4 — CLOSED 与经济漂移反例

- 使用现有public formal terminal链将合法runtime从 OPEN→CLOSING→CLOSED；CLOSED reopen稳定拒绝、initializer调用0、row/descriptor不变。
- source/config/schedule/account runtime等稳定经济字段任一漂移拒绝；不得把环境派生identity变化误判为经济漂移。
- 修正名为 `rejects_stale_cold` 的测试，使其真实构造并断言 STALE，而非仅正向顺序。

### F5 — TOCTOU 与真实路径反例

- config叶 symlink/reparse必须拒绝；测试不得patch掉public path authority。
- 在第二次 absent检查后、broker initializer前植入 broker root，必须映射到稳定 roots-not-absent/invalid并零adopt；不得静默使用后来出现的root。
- 保留partial root、system-temp/project-root、cross-parent、symlink/reparse现有反例。

### F6 — capability伪造与rollback边界不回退

- object construction/replace/copy/pickle、错类型 verifier与不一致字段 capability继续拒绝。
- broker正式bytes后失败仍只返回人工清理边界；不得因新增identity检查提前/延后而递归删除或静默adopt。
- delivery 对 F1–F5逐项记录“现象—根因—应遵循规则—最小复现—新增测试—通过条件”，纠正首轮测试覆盖声明；全部运行检查继续 `UNRUN`。

返工后同一独立reviewer须复核：P2 private投影未复制、public join完整、production/test scope仍exact7、旧STOP与Gate边界诚实。仅无 P0/P1/P2 后申请 Windows验证。

## 10. STATIC_REWORK2：cost schedule identity join

REWORK1 reviewer确认原 P1 与其余 F1–F6 已静态闭合；唯一 P2 为 public chain join / 经济稳定检查遗漏 `binding.cost_schedule_identity`。

批准同一原实现者仅修改 `paper_formal_bootstrap.py`、直接相关 unit/integration tests与delivery：

1. materialized binding 的 `cost_schedule_identity` 必须逐字等于 materialized policy公开对应身份；不得只闭合 policy/binding总identity。
2. cold→materialized 经济稳定检查必须证明 cold binding与current binding的 `cost_schedule_identity` exact相等；该字段漂移稳定 STALE/INVALID并在OMS initializer前失败。
3. fresh/current chain中 environment→policy→binding→account既有join保持；不得复制 P2 private经济投影、不得用 `Any`/cast/bool或总identity掩盖字段缺口。
4. 增加两条定向反例：current binding vs policy cost schedule错配；cold vs current binding cost schedule漂移。均断言 OMS调用0、零写。正向断言该字段在 cold/current policy/binding/result闭合。
5. delivery记录现象—根因—规则—最小复现—新增测试—通过条件；全部运行检查仍 `UNRUN`。

production其他模块、`__init__.py`、taskbook与review冻结。完成后由原reviewer只读复验；无 P0/P1/P2 后才可申请Windows验证。

## 11. STATIC_REWORK3：VALIDATION1 源码禁用扫描自匹配修正

VALIDATION1 的 identity 已通过；focused unit+integration 为 `23 passed / 4 skipped / 1 failed`，Ruff、mypy、cold、scope 均 `UNRUN`。唯一失败是 test-only source self-reference，不构成 production 失败或整包通过。授权同一原实现者仅修改 `tests/integration/test_paper_formal_bootstrap.py` 与既有 delivery；production、unit test、`__init__.py`、taskbook、review 字节冻结，零 Python/SQLite、零 stage/commit。

### F7 — 禁用 monkeypatch 证明不得匹配断言自身

- 现象：集成测试读取整个自身源码并搜索完整 `monkeypatch.setattr(... "_system_temp_root" / "_actual_project_root")` 字面量；这些被禁字符串同时逐字存在于断言自身，因此测试必然自匹配失败。
- 规则：保留“测试不得 monkeypatch 两个真实路径 authority”的强约束，但扫描范围必须排除自证明断言本身。可将 forbidden token 由不连续片段在运行时组合，或只检查真实测试调用体的 AST/等价窄边界；不得用删除禁用检查、宽泛 substring、跳过文件片段而漏掉真实调用或改 production 来通过。
- 正向仍必须使用真实 `_actual_project_root()` 与 `_system_temp_root()` authority；无中央批准 basetemp 时维持原 skip。补显式自证：若在实际测试调用体新增任一 forbidden monkeypatch，检查必失败；断言文本本身不构成命中。

delivery 必须记录 F7 的现象—根因—规则—最小复现—修正测试—通过条件，并绑定 VALIDATION1 evidence root与 summary SHA；如实保留23绿/4skip/1失败、后续UNRUN及outer PowerShell exit不代表产品PASS的边界。完成后交同一原独立reviewer只读复验，确认 production/unit SHA不变且禁用扫描未弱化。REVIEW_PASS 后申请完整 VALIDATION2：identity → focused unit+integration → Ruff production2+tests2 → mypy production2 → cold production2 → exact7 scope/diff/temp/process；不得继承失败轮替代重跑。

## 12. EVIDENCE_UPDATE：VALIDATION1 → REWORK3 → VALIDATION2 → SCOPE1

中央授权 EVIDENCE_UPDATE（STATIC_ONLY：仅本任务书 + delivery；production / tests / `__init__.py` / review 冻结只读；不清 evidence；零 Python；零 stage/commit）。

| 轮次 | evidence root | 原生结果（保留；不洗白） |
| --- | --- | --- |
| VALIDATION1 | `artifacts/agent_runs/m4-ua006-r1-rebuilt2-validation1-20260826T194000Z` | identity PASS；focused **`23 passed / 4 skipped / 1 failed`**（test-only source self-match：`test_integration_module_does_not_patch_forbidden_runtime_roots`）；Ruff/mypy/cold/scope **UNRUN**；`STOP=STAGE_FAILED:focused`；summary SHA `1F4065B1C22061370BCBACB9EEB705945BA97D8D708093E6B09DAE3479DB4C51` |
| STATIC_REWORK3 / F7 | （实现者写集：integration test + 当时 delivery） | 禁用扫描改为 AST Call + 片段组合；断言自匹配消除；正向仍用真实 `_actual_project_root()` / `_system_temp_root()` |
| VALIDATION2 | `artifacts/agent_runs/m4-ua006-r1-rebuilt2-validation2-20260826T195000Z` | identity PASS；focused **`24 passed / 4 skipped`**；Ruff exact4 PASS；mypy production2 PASS；cold production2 PASS；**scope carrier STOP only**（`STOP=STAGE_FAILED:scope`；产品阶段已绿）；summary SHA `F452D75E597840EFDD3680EA4872D5334DB765E949A1AA326DDD3F9D1CB686C6`；focused stdout SHA `48EE027B41C71B0C0D7D66589A621F0673DA931D8CBB870F3BC563ED1CFA34C7` |
| SCOPE1 | `artifacts/agent_runs/m4-ua006-r1-rebuilt2-validation2-scope1-20260826T200000Z` | exact7 / cached0 / diff / temp(residue) / process **PASS**（`PASS=ALL_SCOPE_CHECKS`）；summary SHA `552D75D607B2EA0F3908D784797E1DEC68308381AB96F523EEF2F50825FC596B` |

状态上限达成：**仅** `FRESH_FORMAL_BOOTSTRAP_WINDOWS_ENGINEERING_VALIDATED`。

**仍 OPEN**：`UA-M4-006`、PAPER、soak、Linux Gate。不得宣称主验合流、无人值守实盘或 Gate 关闭。
