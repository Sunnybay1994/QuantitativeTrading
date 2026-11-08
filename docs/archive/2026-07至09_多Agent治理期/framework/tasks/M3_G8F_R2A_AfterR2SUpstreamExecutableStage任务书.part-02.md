1. 仅修改 `tests/integration/test_m3_successor_upstream_stage.py` 与既有 delivery；production、其他tests、taskbook（本节经理追加除外）及review冻结。
2. provider真实调用与backtest-plan真实调用必须各自置于独立、test-owned的 `pytest.MonkeyPatch.context()`；每个context只安装该support所需替换，并在离开时由pytest精确恢复，禁止跨两套fixture共享残留patch authority。
3. 不得patch production verifier、最终返回值、错误码或把真实调用改回mock/源码检查；两套真实正向调用、有效 `ProviderValidationSpec`、PROJECT-only `artifact_roots`、返回类型/identity断言和既有负向反例全部保留。
4. 若独立context后仍在backtest support前置失败，必须STOP并回报首个真实公开错误与调用边界，不得继续叠加monkeypatch或修改production猜修。
5. delivery记录现象、根因、monkeypatch authority生命周期规则、最小复现、修正测试、通过条件与 evidence root `artifacts/agent_runs/m3-r2a-validation5-20260826T072447Z/`；绑定focused stdout SHA `717DC4F54A946DF3B51BD8F27B6B0B991078CEC7E8FA9895F07BF29952A0A02B`、summary SHA `6C2815D0A0FBC5619CD3451F63B957C04C5701033D47FF5FEC956DA9F3F59017`。
6. 原独立reviewer复验production SHA不变、两个context真正隔离、退出恢复且真实API正负合同未弱化。PASS后重新申请完整VALIDATION6：identity→focused exact4→Ruff production2/tests4→mypy production2→cold production2→exact9 scope/residue。

零Python、pytest、Ruff、mypy、cold、Qlib、network、actual worker、new root、retained、stage或commit。不得把73/1记为整包通过；M3 Gate保持未关闭。

## 16. VALIDATION7 只读节点协议类型返工（2026-08-26）

VALIDATION7 有效组合：identity PASS；focused exact4 `74 passed / 374914 warnings`；Ruff production2/tests4 PASS；mypy production2 在 `successor_upstream_stage.py` 首失败9项；cold与scope `UNRUN`。§15 monkeypatch authority隔离已由运行证据证明闭合。

9项同源根因：`_ReceiptNodeView` Protocol 将 `fold`、`horizon_sessions` 等由 `_new_receipt_ref` 只读消费的成员声明为可写实例变量，而真实 `StageNode` 与 `_SummaryNodeRef` 以只读property提供这些成员；结构子类型因此被mypy正确拒绝。运行比较、receipt identity与发布逻辑未因此判红。

授权同一 adopter 在 `STATIC_ONLY` 下最小类型返工：

1. 仅修改 `src/quant/research/m3/successor_upstream_stage.py` 与既有 delivery；其他production/tests、taskbook（本节经理追加除外）及review冻结。
2. 将 `_ReceiptNodeView` 中只读消费的成员逐项改为 `@property` 抽象声明，返回类型保持现有精确类型；不得新增setter、mutable Protocol、Any、cast、type ignore或扩大接受对象。
3. 不修改 `_new_receipt_ref` 函数体、StageNode/_SummaryNodeRef、运行分支、比较、排序、receipt/schema/identity、错误码或测试；不为mypy改任何业务语义。
4. delivery记录现象、根因、只读结构子类型规则、最小复现、修正、通过条件及 evidence root `artifacts/agent_runs/m3-r2a-validation7-20260826T000444Z/`；绑定focused SHA `5E6711F702211439E999082D6C66522B0BE976470B3CA70E4C1E7241BC21CCD8`、Ruff SHA `AF352A86840AD0AF3D37EA0D9197F868363A6DAC6B1C2EF5D2722F6B41D2D9AF`、mypy SHA `BF020D2F0C7741E88537FA22AB792C9B935DE4EE7CAD102C95C67541E9D5C0E0`、summary SHA `F569CABA36F3DBB64E301DADD5673D355B5497681F355E91509E4EC263A2B3CC`。
5. 原独立reviewer复验仅Protocol只读注解变化，runtime/schema/identity零变化。PASS后申请postfix窄验证：identity→Ruff实际修改production文件→mypy production2→cold production2→exact9 scope/residue；不重复已绿focused74和其余Ruff。

零Python/pytest/Ruff/mypy/cold/Qlib/network/worker/stage/commit。状态仍仅Windows工程验证候选，不关闭R2A/bridge/CLI/M3 Gate。

## 17. Windows 工程验证组合闭包与证据复核（2026-08-26）

本包Windows开发验证以组合证据闭合：VALIDATION7 focused exact4 `74 passed` 且 Ruff production2/tests4 PASS；POSTFIX VALIDATION8 identity、Ruff实际production文件、mypy production2、cold production2、exact9 scope/diff/temp/process全部PASS。VALIDATION1–7的历史首失败、carrier失败与UNRUN边界继续保留，不改写为单轮全绿。

授权同一 adopter 仅更新taskbook/delivery最终执行证据与状态 `R2A_WINDOWS_ENGINEERING_VALIDATED`（或任务书既有等价值）；production/tests/review冻结，零Python、零stage/commit。必须记录 VALIDATION8 evidence root `artifacts/agent_runs/m3-r2a-postfix-validation8-20260826T003929Z/`、summary SHA `7BEE5B9B623FBDD6CA61DEDC59F6D170BE7A6477D6496BA7711DAFB5DCC71B51`、mypy SHA `07A5CA23E5D39B2565C0C1361F0556B8C3C75484BBA05841F400436D190BB660`、cold SHA `FDB6604E0E2D6BA154D20B746709F7BE55A421A390955F144ECD8611E0E3B0EB`、scope SHA `95BD7969B952C1C62269C0F63203BB9834D5759B3D6785C382960E0EE1AB5F17`，并与VALIDATION7 focused/Ruff证据组合说明。

随后由同一原独立reviewer仅写唯一review报告执行 `EVIDENCE_REVIEW`，复核历史证据链、关键SHA/exit、actual8⊆exact9、scope/cached/diff/residue及未验证边界，输出PASS/FAIL。PASS后方可申请安全提交。

边界保持：仅 `EXECUTABLE_STAGE_SUBSTRATE` Windows工程闭包，不关闭production bridge/CLI/actual worker/真实Qlib/new root/retained/M3 Gate。

## 18. VALIDATION1–8 Windows 工程验证组合证据（终态）

经理授权 `EVIDENCE_UPDATE_READY`。状态仅升为 `R2A_WINDOWS_ENGINEERING_VALIDATED`。

**组合闭合口径（不得改写为单轮全绿）：**

- VALIDATION7：focused exact4 `74 passed` + Ruff production2/tests4 **PASS**；mypy production2 当时 **9 errors STOP**；cold/scope **UNRUN**（证据根与 SHA 见下表；只读 Protocol 返工后由 VALIDATION8 postfix 闭合 mypy/cold/scope）。
- POSTFIX VALIDATION8：identity、Ruff（实际修改 production）、mypy production2、cold production2、exact9 scope/diff/temp/process **全部 PASS**。
- VALIDATION1–7 历史首失败、carrier-invalid 与各轮 UNRUN 边界 **永久保留**。

### 18.1 VALIDATION8 证据根与阶段 SHA

| 项 | 值 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m3-r2a-postfix-validation8-20260826T003929Z/` |
| identity | **PASS** |
| Ruff（实际 production 文件） | **PASS** |
| mypy production2 | **PASS**；stdout SHA `07A5CA23E5D39B2565C0C1361F0556B8C3C75484BBA05841F400436D190BB660` |
| cold production2 | **PASS**；stdout SHA `FDB6604E0E2D6BA154D20B746709F7BE55A421A390955F144ECD8611E0E3B0EB` |
| exact9 scope/diff/temp/process | **PASS**；scope SHA `95BD7969B952C1C62269C0F63203BB9834D5759B3D6785C382960E0EE1AB5F17` |
| stage-summary SHA | `7BEE5B9B623FBDD6CA61DEDC59F6D170BE7A6477D6496BA7711DAFB5DCC71B51` |
| scope 子集 | **actual8 ⊆ exact9**；**cached0**；diff/residue 按 summary **PASS**（不另造未提供的分项 SHA） |

### 18.2 VALIDATION7 组合证据（与 V8 联立，不重复 focused）

| 项 | 值 |
| --- | --- |
| evidence root | `artifacts/agent_runs/m3-r2a-validation7-20260826T000444Z/` |
| focused exact4 | `74 passed`；stdout SHA `5E6711F702211439E999082D6C66522B0BE976470B3CA70E4C1E7241BC21CCD8` |
| Ruff production2/tests4 | **PASS**；stdout SHA `AF352A86840AD0AF3D37EA0D9197F868363A6DAC6B1C2EF5D2722F6B41D2D9AF` |
| mypy production2（修前） | exit=1；**9 errors**；stdout SHA `BF020D2F0C7741E88537FA22AB792C9B935DE4EE7CAD102C95C67541E9D5C0E0` |
| stage-summary SHA | `F569CABA36F3DBB64E301DADD5673D355B5497681F355E91509E4EC263A2B3CC` |
| cold / final scope | **UNRUN**（首失败合同；由 V8 postfix 闭合） |

### 18.3 VALIDATION1–8 真实失败/通过链与 UNRUN（不改写）

| 轮次 | 结果边界 |
| --- | --- |
| VALIDATION1 | identity PASS；focused `61 passed / 3 failed`；Ruff/mypy/cold/scope **UNRUN**；空 carrier → `CARRIER_INVALID_BEFORE_PRODUCT_EVIDENCE` |
| VALIDATION2 | identity PASS；focused `64 passed`；Ruff 首失败 STOP；mypy/cold/scope **UNRUN** |
| VALIDATION3 | identity+Ruff PASS；mypy **115 errors** STOP；cold/scope **UNRUN** |
| VALIDATION4 | identity PASS；focused `73 passed / 1 failed`；Ruff/mypy/cold/scope **UNRUN** |
| VALIDATION5 | identity PASS；focused `73 passed / 1 failed`；Ruff/mypy/cold/scope **UNRUN** |
| VALIDATION6 | 授权完整 validation（§15 后）；有效 focused74+Ruff 组合与 VALIDATION7 证据根联立记录；不以臆造独立 root 冒充 |
| VALIDATION7 | focused74 + Ruff PASS；mypy 9 STOP；cold/scope **UNRUN**（上表） |
| VALIDATION8 | identity/Ruff/mypy/cold/scope **全部 PASS**（上表）；**actual8 ⊆ exact9** / **cached0** |

### 18.4 未验证边界（强制保留）

仅 `EXECUTABLE_STAGE_SUBSTRATE` / `R2A_WINDOWS_ENGINEERING_VALIDATED` Windows 工程闭包。**明确未闭合、不得宣称**：production bridge、CLI、actual worker、真实 Qlib dump/materialization、new root、retained、acceptance、目标终态 `EXECUTABLE_STAGE_SUBSTRATE_WINDOWS_VALIDATED` 若与本工程标签区分时的更高 Gate、以及 **M3 Gate**。

随后由同一原独立 reviewer 仅写唯一 review 报告执行 `EVIDENCE_REVIEW`；PASS 后方可申请安全提交。
