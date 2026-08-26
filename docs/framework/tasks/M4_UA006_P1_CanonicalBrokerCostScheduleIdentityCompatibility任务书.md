# M4-UA006-P1 Canonical Broker Cost Schedule Identity Compatibility 任务书

## 1. 身份、目标与边界

- exact base/HEAD：`1d9b4e09c91293de18fea5cf0aa563b782379d37`
- branch：`codex/m4-ua006-p1-canonical-broker-cost-identity-compat`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m4-ua006-p1-canonical-broker-cost-identity-compat`
- 状态上限：`CANONICAL_BROKER_COST_IDENTITY_COMPAT_VALIDATED`

本包只消除formal policy与broker descriptor对同一个`ExecutionCostSchedule`使用两套不兼容identity算法的问题。它是M4-UA006-P2与fresh bootstrap的前置，不代表P2、bootstrap、PAPER、B1B2、soak或UA-M4-006完成。

## 2. 唯一写白名单 exact7

1. `src/quant/execution/paper_policy.py`
2. `src/quant/execution/paper_broker_store.py`
3. `tests/unit/test_paper_policy.py`
4. `tests/unit/test_paper_broker_store.py`
5. `docs/framework/tasks/M4_UA006_P1_CanonicalBrokerCostScheduleIdentityCompatibility任务书.md`
6. `docs/framework/deliveries/M4_UA006_P1_CanonicalBrokerCostScheduleIdentityCompatibility交付报告.md`
7. `docs/framework/reviews/M4_UA006_P1_CanonicalBrokerCostScheduleIdentityCompatibility独立初验报告.md`

经理唯一写5；全新外部实现者只写1–4、6；另一全新独立reviewer只写7。禁止修改config、schema、migration、formal store、session barrier、bootstrap、execution `__init__.py`、roadmap或共享SSOT。

## 3. 现象、根因与唯一SSOT

M4-UA006-P2 DIAGNOSTIC1在真实public initializer中捕获：

- `paper_formal_broker_store.py:193`调用`build_formal_paper_broker_policy_descriptor`；
- 后者抛`PaperBrokerStoreError("PAPER_BROKER_POLICY_INVALID")`，再被formal store稳定归一为`PAPER_FORMAL_STORE_INVALID`；
- `paper_policy._cost_schedule_identity`使用`paper-execution-cost-schedule-identity-v1` canonical payload；
- `paper_broker_store`却用本地`_digest(_cost_payload(...))`复核，payload含`"type": "ExecutionCostSchedule"`且字段结构不同。

因此合法fresh policy的`cost_schedule_identity`无法通过formal broker descriptor。trace SHA：`d80142bd6b987d9a76e55616f14358a92eb13fe110f82387f3715c3fa80c0338`。

权威规则：同一个schedule只能有一个canonical identity函数。不得在consumer复制payload或通过删复核、信任字符串、接受bool来绕过。

## 4. 冻结API与实现合同

- 在`paper_policy.py`把现有`_cost_schedule_identity`原样提炼/公开为窄强类型函数；exact命名按模块现有风格选择并在delivery逐字记录。
- public函数只接受exact `ExecutionCostSchedule`，使用现有canonical payload、版本、字段顺序、Decimal文本、currency/market/period规则；既有policy loader改为调用它。原合法policy的identity bytes/SHA必须逐字不变。
- `paper_broker_store.build_formal_paper_broker_policy_descriptor`只调用该public函数验证`policy.execution_cost_schedule`与`policy.cost_schedule_identity` exact一致；删除本地不兼容`_digest(_cost_payload(...))`复核。
- 不删除formal descriptor对binding/policy session、adapter/fill/fault/finality/clock、cost/fx identity的逐字段闭包。
- non-formal `build_paper_broker_policy_descriptor`及其本地descriptor identity/bytes保持不变；不要把paper_policy identity算法强塞入non-formal schema。
- formal issued-object registry、weakref identity、防伪、descriptor dataclass、store初始化/transaction、错误码、schema与migration均不变。
- 不把新函数导出到execution包根；consumer直接从`paper_policy`窄import，避免扩大公共surface。

## 5. 必测对抗

至少覆盖：

1. 既有policy fixture对新public函数的identity与旧冻结expected SHA逐字相等；loader产出的`cost_schedule_identity`等于public函数。
2. 真实public policy+binding可成功构造formal broker descriptor；descriptor字段与bytes/identity保持既有schema。
3. 语义等价schedule（新对象、相同period顺序/字段）得到相同identity。
4. commission rate/minimum、stamp tax、transfer fee、currency、market、start/end、period缺失/额外/重排等任一经济漂移按现有canonical规则改变identity并导致formal descriptor拒绝stale policy/binding。
5. policy自述identity与fresh schedule不符、binding cost identity不符、session或规则版本漂移均`PAPER_BROKER_POLICY_INVALID`。
6. 伪造/replace/object.__new__ policy或binding、非exact schedule类型、wrapper/monkeypatch public identity函数替换均fail closed；不得仅凭相等字符串接受未验证对象。
7. formal descriptor必须仍由issued registry记录；手工等值descriptor不能进入store。
8. non-formal descriptor输入、bytes、identity及既有错误码逐字回归。

独立reviewer须新增实现者未用反例，优先挑战consumer缓存函数别名导致monkeypatch authority不可见，或错误地改变non-formal descriptor bytes。

## 6. 初验后白名单扩展与返工合同

中央在独立初验后确认：`tests/unit/test_paper_formal_broker_store.py` 的既有 fixture 仍以 broker-local `_digest(_cost_payload(schedule))` 伪造 formal policy 的成本身份。新 production 校验会正确拒绝该身份，因此仅合入原 exact7 会令 integration 的既有 formal-store 测试稳定变红。

白名单由 exact7 精确扩为 exact8，新增且仅新增：

8. `tests/unit/test_paper_formal_broker_store.py`

返工只允许原实现者：

- 将 formal-store fixture 的成本身份改为公开 `paper_execution_cost_schedule_identity(...)`；
- 增加旧 broker-local `_digest(_cost_payload(schedule))` 身份被 formal descriptor 稳定拒绝的回归；
- 不修改 formal-store production、测试的其他业务语义、schema、migration 或公共 API；
- 在交付报告记录“现象—根因—规则—修正测试—通过条件”。

完成后由原独立 reviewer 复验最终 exact8。Windows 验证扩为三个测试文件：`test_paper_policy.py`、`test_paper_broker_store.py`、`test_paper_formal_broker_store.py`；Ruff 覆盖两 production 与三 tests，mypy/cold 仍为两 production，最终核 exact8 scope/residue。

## 7. 交付与验证

当前仅授权全新外部实现Agent `STATIC_ONLY`：零Python、pytest、Ruff、mypy、cold、SQLite、PAPER、network/browser、stage/commit。delivery必须写“现象—根因—规则—最小复现—新增测试—通过条件”、public API名、bytes兼容证据设计及未运行边界。

实现后由另一全新外部reviewer只读业务路径且唯一写7；REVIEW_PASS后才申请Windows验证。最终验证合同以§6 exact8为准：identity → 三个测试文件 → Ruff production2/tests3 → mypy production2 → cold production2 → exact8 scope/diff/temp/process。首失败STOP，不自动扩围。

## 8. VALIDATION1 F1：issued descriptor的持久化可观察身份

VALIDATION1有效结果：Parser/argv/identity PASS；`test_paper_policy.py`为`41 passed / 1 skipped`；`test_paper_broker_store.py`为`22 passed / 1 failed`；formal-store、Ruff、mypy、cold、scope均UNRUN。唯一失败发生在测试对成功初始化后的可观察属性断言，production initializer与issued registry已经越过。

- 现象：新增测试访问不存在的`store.policy_descriptor`。
- 根因：生产公开面为`store.policy_identity`，底层持久化描述为`store.descriptor`；测试把输入descriptor对象名误当作store API。
- 规则：不得为测试新增production属性或改变issued registry。应通过现有持久化可观察身份断言，例如`store.policy_identity == issued.descriptor_identity`，并保持clone拒绝与issued正向初始化。
- 本轮仅允许原实现者修改`tests/unit/test_paper_broker_store.py`、本任务书与delivery；全部production、其他tests和review冻结。
- delivery记录现象—根因—API规则—最小复现—修正测试—通过条件并引用VALIDATION1证据。

同一独立reviewer复验后申请完整VALIDATION2，仍按§6 exact8全序列执行，不把VALIDATION1部分绿冒充整包PASS。

## 9. STOP 与退出条件

以下任一立即在delivery留证并STOP：

- exact8不足或需要修改formal store/bootstrap/schema/migration/config；
- 无法保持policy现有identity逐字兼容；
- 需要复制第二payload、信任自述identity、删除issued-object或放宽non-formal行为；
- base/branch/worktree漂移、第二writer、白名单外dirty。

静态退出要求actual dirty只属exact8、cached=0、`git diff --check` PASS，无runtime root、SQLite、cache、临时文件或凭据。

## 10. EVIDENCE_UPDATE：VALIDATION1 STOP → F1 → VALIDATION2 全绿

中央授权 EVIDENCE_UPDATE（STATIC_ONLY：仅本任务书 + delivery；production/tests/review 冻结；不清 evidence）。

| 阶段 | 证据 / 结果 |
| --- | --- |
| VALIDATION1 | evidence：`artifacts/agent_runs/m4-ua006-p1-validation1-20260826T070627Z`；identity PASS；policy `41 passed / 1 skipped`；broker `22 passed / 1 failed`（`store.policy_descriptor`）；formal/Ruff/mypy/cold/scope **UNRUN**；`STOP\|STAGE_FAILED:03-broker-test`（test-only） |
| F1 修复 | 实现者将断言改为 `store.policy_identity == issued.descriptor_identity`；独立 reviewer **`F1_REVIEW_PASS`**（见 review） |
| VALIDATION2 | evidence：`artifacts/agent_runs/m4-ua006-p1-validation2-20260826T071606Z`；全序列 PASS（详见 delivery §11） |

状态上限达成：`CANONICAL_BROKER_COST_IDENTITY_COMPAT_VALIDATED`。**P2 / bootstrap / PAPER / soak / UA-M4-006 仍 OPEN。**
