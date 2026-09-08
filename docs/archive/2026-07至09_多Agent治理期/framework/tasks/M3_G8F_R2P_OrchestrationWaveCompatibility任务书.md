# M3-G8F-R2P Orchestration Wave Compatibility 任务书

状态：`DELIVERY_READY`（VALIDATION2 focused + VALIDATION4 post-fix 组合证据闭合；Windows 定向开发闭合；handler/bridge/CLI/actual worker/真实 Qlib/new root/retained/Gate **未**完成）

## 1. 身份、职责和终态

- task id：`M3-G8F-R2P-ORCHESTRATION-WAVE-COMPAT`
- exact base：`c124ec57e254672cd371ea04a732515a59c2fad1`
- branch：`codex/m3-g8f-r2p-orchestration-wave-compat`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2p-orchestration-wave-compat`
- 经理：框架主 Agent，独占本任务书。
- 实现：一个全新的外部 Cursor Agent 会话；只写实现白名单和唯一 delivery。
- 初验：另一全新且未参与实现的外部 Cursor Agent；实现、测试、任务书和 delivery 只读，只写唯一 review。
- 终态上限：`ORCHESTRATION_WAVE_COMPAT_VALIDATED`。不表示 executable handler、bridge/CLI、actual worker、真实 Qlib、新 root、retained、acceptance 或 M3 Gate 完成。

旧 R2 与 R2A dirty/STOP worktree 全部冻结，只能作为事故根因摘要，禁止读后机械复制 placeholder、写入、测试、提交或清理。

## 2. 三次结构 STOP 根因摘要

1. R2：public bundle 只有 upstream run-plan builders，没有 package-owned handler/closure 执行面；callback 又不携带显式 prior closure，导致 placeholder。
2. R2A：现有 provider/experiment-artifact/reconciliation/work/summary builder 固定 `stage`、`g1-release`、`qlib-dump-tool` alias，与 PROJECT-only `StageRunner`、禁止 nested roots和 successor PROJECT-only receipt合同冲突。
3. R2A：R1 把 features/labels 等伪装成单 transition，但现有真实边界是多 node wave；`make_work_run_plan` 需要 labels+reconciliations，不能在 features-before-labels 的伪顺序下合法构造。

本包不新增 `make_features_run_plan`，不拆/复制现有 work builder，不实现 handler；只让既有 builder 支持 PROJECT-only digest，并让 successor runtime 按真实 wave 边界表达顺序和 receipt 映射。

## 3. 精确白名单

exact10：

1. `src/quant/research/m3/orchestration.py`
2. `src/quant/research/m3/successor_runtime.py`
3. `tests/unit/test_m3_orchestration_plans.py`
4. `tests/unit/test_m3_orchestration_waves.py`
5. `tests/integration/test_m3_orchestration_project_root.py`（新）
6. `tests/unit/test_m3_successor_runtime.py`
7. `tests/integration/test_m3_successor_runtime.py`
8. `docs/framework/tasks/M3_G8F_R2P_OrchestrationWaveCompatibility任务书.md`（经理独占）
9. `docs/framework/deliveries/M3_G8F_R2P_OrchestrationWaveCompatibility交付报告.md`（实现者独占）
10. `docs/framework/reviews/M3_G8F_R2P_OrchestrationWaveCompatibility独立初验报告.md`（初验者独占）

实现者不得改 8、10；初验者不得改 1–9。其他 production/test/config/`__init__.py`/roadmap/共享 SSOT/旧现场只读。任何扩围需求先写 delivery 并 STOP。

## 4. PROJECT-only digest 兼容

以下既有 builder 新增一个可选、keyword-only 的窄 `artifact_roots` 参数：

- `make_provider_materialization_run_plan`
- `make_provider_validation_run_plan`
- `make_experiment_artifact_run_plan`
- `make_label_reconciliation_run_plan`
- `make_work_run_plan`
- `make_summary_run_plan`

合同：

1. `artifact_roots is None` 时，legacy alias、relative path、digest、node、edge、canonical bytes 和 plan identity 必须逐字不变；不能为重构改变排序或错误码。
2. supplied 时，每个 external input 必须调用现有 `select_artifact_root` 选择唯一 alias/root，再依据真实所选 root 重算 relative path、size/SHA/digest；禁止只替换 alias 字符串。
3. successor 只传 `{"PROJECT": project_root}`；所有 input/output receipt alias 必须是 `PROJECT`。
4. duplicate、nested、ambiguous root，路径越界、symlink/reparse、错误 relative path、bytes/SHA 漂移均 fail closed。
5. `experiment_identity` 现有 `artifact_roots` 合同保持，不修改该模块。

## 5. 真实 wave 语义

successor runtime 的唯一顺序改为真实 wave：

1. snapshot；
2. provider；
3. provider-validation；
4. experiment-identity；
5. experiment-artifacts wave：labels + folds，一次 plan、一次 wave；
6. label-reconciliation wave：全部 horizons，一次 plan；
7. work wave：features 及全部 fold×horizon alignment/train/predictions/evaluation/targets/backtest-plan，一次 plan；
8. formal backtest/tracking；
9. summary、reproducibility、readiness、acceptance 四 Gates。

禁止：

- 把 builder 不存在的 features/labels 等伪成独立 run-plan transition；
- 重复调用 experiment-artifact/work builder或重复发布同一 wave；
- 虚映射 labels 为 folds receipt；
- 修改 terminal receipt schema或复制另一套完整序列。

experiment-artifacts wave 的真实 labels receipts 与 folds receipt必须由实际 node发布结果映射；work wave 的每个实际 node receipt显式映射回 `FoldExecution` 所需 individual `StageReceiptRef`。共享 physical ownership、跨 fold共享与 global receipt uniqueness继续沿 runtime 既有合同。

Summary 仍是单独 Gate wave。本包只让 runtime protocol与真实 plan边界一致；不实现 handler、build或 verifier。

## 6. Pure run-plan node 选择 API

在 `orchestration.py` 新增一个纯选择/校验 API（建议名）：

`select_run_plan_nodes(plan, *, expected_continuation, expected_node_ids) -> tuple[StageNode, ...]`

要求：

- exact `RunPlan` / expected continuation / exact node-id闭包；
- 输出按稳定 node id排序；
- 缺失、额外、重复、错误 continuation、未知 node、输入重复一律 fail closed；
- 不执行 handler、不打开/扫描目录、不发布 artifact/receipt、不改变 plan；
- caller不能用该 API选择一部分后冒充完整 wave，runtime必须验证 expected node set 与实际 wave闭包完全相等。

`StageRunner.run_static` / `run_snapshot` 保持唯一执行原语；R2A 后续负责 package-owned handlers。

## 7. 失败语义与必须覆盖的反例

错误必须稳定、脱敏、无绝对路径、payload/config bytes、凭据或底层 cause/context。至少覆盖：

1. 六个 builder 的 legacy `artifact_roots=None` 输出 canonical bytes/identity逐字回归；
2. PROJECT-only每类 external input的 alias、relative path、size/SHA/digest正确；
3. alias字符串替换但未重算relative/digest拒绝；
4. duplicate/nested/ambiguous roots、path越界、symlink/reparse；
5. expected node缺、多、重复、错误 continuation、顺序输入漂移；
6. experiment-artifact builder只调用一次且 labels/folds 都映射真实 node receipt；
7. label-reconciliation all-horizon wave只调用一次；
8. work builder只调用一次且所有 expected node individual refs齐全；
9. 跨 fold共享receipt/physical ownership和global uniqueness漂移拒绝；
10. runtime旧伪 single-transition字段/callback/marker bundle拒绝；
11. summary仍保持单独 Gate 边界且本包没有 placeholder handler；
12. selection API零目录扫描/零发布副作用。

独立初验必须新增至少一个实现者未使用的对抗例，重点挑战 legacy bytes identity 或 wave receipt映射的缺/多/共享冲突。

## 8. 验证与交付

当前 `STATIC_ONLY`：禁止 Python、pytest、Ruff、mypy、cold、SQLite/真实 I/O、网络、Qlib、actual worker、retained、stage/commit。实现完成后先由全新外部会话独立静态初验，PASS 后再向中央申请 CPU8–11。

拟定验证顺序：identity → orchestration plan unit → wave unit → PROJECT-root integration → successor runtime定向 unit/integration → Ruff exact production/tests → mypy production2 → cold → exact10/scope/diff/temp/process。首失败 STOP，不重试扩围。

Delivery 必须记录：六 builder legacy/PROJECT映射、select API、真实 wave顺序、node→receipt映射、错误码、反例、未运行项和风险；问题统一写“现象—根因—规则—最小复现—新增测试—通过条件”。不得宣称 executable handler、bridge/CLI、actual worker、真实 Qlib、Linux或 M3 Gate。

## 9. VALIDATION1 聚焦失败与 STATIC_ONLY 最小返工（F3）

经理授权 focused 证据（本实现会话未重跑）：

- evidence root：`artifacts/agent_runs/m3-r2p-validation1-20260825T131357881Z`
- `02-unit-orchestration-plans.stdout.log` SHA-256=`c5b16b91d6385df53f55bef486fe417d87af74048d86c55933435430819fa89c`
- 结果：`2 failed / 11 passed`；失败测：`test_work_scope_keys_only_use_verified_experiment_and_work_identity`、`test_development_summary_uses_verifier_receipt_stage`

| 字段 | 内容 |
| --- | --- |
| 现象 | 两测 monkeypatch boundary stub 收到 `artifact_roots=` 时 `TypeError: unexpected keyword argument 'artifact_roots'` |
| 根因 | stub 为 `lambda *_args`，未显式接受 keyword-only `artifact_roots`；生产 builder 在 legacy `None` 路径仍 keyword 转发 |
| 规则 | §4 keyword-only `artifact_roots`；测试 stub 必须兼容生产调用面，且保持原返回值、身份断言与 legacy 行为 |
| 最小复现 | 上述 evidence root + stdout SHA；`make_work_run_plan` / `make_summary_run_plan` 默认调用即触发 |
| 修复范围 | **仅** `tests/unit/test_m3_orchestration_plans.py` 上述两测 stub 签名；production / 其他测试 / review **禁止**改动；本任务书与 delivery 补证据 |
| 通过条件 | stub 显式 `artifact_roots=None`；原返回值与身份断言不变；待授权复跑同 focused 文件不再因 stub 签名失败 |

本返工仍为 `STATIC_ONLY`：禁止 Python/pytest/Ruff/mypy/cold/提交。

## 10. VALIDATION2 聚焦失败与 STATIC_ONLY 最小返工（F4）

经理授权 focused 证据（本实现会话未重跑）：

- evidence root：`artifacts/agent_runs/m3-r2p-validation2-20260825T142500Z-a7f3`
- focused：13+15+5+36 全绿；Ruff 首失败 F841
- `06-ruff` stdout SHA-256=`355b0a73f1069325fa56ef30c15effa373eba02bf3f137d0b92a4b07244720ec`

| 字段 | 内容 |
| --- | --- |
| 现象 | `orchestration.py:2284` `manifest = next(...)` 触发 Ruff F841（赋值未使用） |
| 根因 | `_release_label_inputs` 仅需 `next` 证明 inputs 含匹配 `release.manifest_sha256` 的项，结果未消费 |
| 规则 | 消除 F841；保留校验副作用；不得改 digest/wave/receipt |
| 最小复现 | 上述 evidence root + `06-ruff` stdout SHA |
| 修复范围 | exact10 内将该赋值改为显式无赋值 `next(...)`；同步本任务书与 delivery；production 其他行为 / 测试 / review **禁止**无关改动 |
| 通过条件 | 无 F841；匹配失败仍经 `next` 失败；digest/wave/receipt 不变 |

本返工仍为 `STATIC_ONLY`：禁止 Python/pytest/Ruff/mypy/cold/提交。

## 11. VALIDATION3 类型返工（F5）

经理授权证据（本实现会话未重跑）：

- evidence root：`artifacts/agent_runs/m3-r2p-postfix-validation3-20260825T151500Z-d42b`
- mypy stdout SHA-256=`c348414b6fce19d607a2a9c518ba4a15bc528a40b9a13edeeeeee96a11615c93`

| 字段 | 内容 |
| --- | --- |
| 现象 | mypy 四错：`expected` 在 L1448/L1466 等处语义/宽度冲突 |
| 根因 | 同名变量混用二元 `(stage, horizon)` 与三元 `(stage, fold, horizon)` |
| 规则 | 明确命名；expected/actual 共用窄三元组类型；禁 ignore/Any；运行分支与 fail-closed 语义不变 |
| 最小复现 | 上述 evidence root + mypy stdout SHA |
| 修复范围 | **仅** `successor_runtime.py`（`_WaveReceiptKey` + 分波命名集合）与本任务书/delivery；review 只读 |
| 通过条件 | mypy 四错关闭；fold/horizon None 与错位集合仍 fail-closed |

本返工仍为 `STATIC_ONLY`：禁止 Python/Ruff/mypy/cold/提交。

## 12. VALIDATION2 + VALIDATION4 组合证据（提交前 evidence-only）

经理授权组合证据（本实现会话未重跑、未改 production/tests）：

### VALIDATION2 focused PASS

- evidence root：`artifacts/agent_runs/m3-r2p-validation2-20260825T142500Z-a7f3`
- focused：`13 + 15 + 5 + 36` **PASS**
- 注：同轮 Ruff 曾 F841 首失败，已由 §10 F4 修复；lint 以 VALIDATION4 为准

### VALIDATION4 post-fix 全绿

- evidence root：`artifacts/agent_runs/m3-r2p-postfix-validation4-20260825T160000Z-f19a`
- identity / Ruff / mypy2 / cold / scope / diff / process：**全 PASS**
- 无 temp / cache / `0xF00`

关键 SHA-256：

| 项 | SHA-256 |
| --- | --- |
| Ruff | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| mypy | `0c37c4158c91ef55c724ba017bf6465f26018199badb08e3ff13f98acdf056c2` |
| cold | `85b01af69016a727b65564a6669e32fa364c216cf51e3276cdd140e88a661138` |
| scope | `505d79fd5baea8c04dc1530a513bf778723e7e906b21923f09e2bdf4f465d0bd` |
| summary | `f43b88a6b1c033e4b165aa71657fc1606a39f1c4a32fa84429bc5d894b65f275` |
| runner | `3c147c5156a8822987918961069d5386d003edef666ab5b0848e4cf8b0bd801d` |

### 终态边界

- **Windows 定向开发闭合**（上列组合证据）。
- **未完成**：handler、bridge/CLI、actual worker、真实 Qlib、new root、retained、Gate。
- 本轮仅更新本任务书与 delivery；禁止 Python/检查/提交。
