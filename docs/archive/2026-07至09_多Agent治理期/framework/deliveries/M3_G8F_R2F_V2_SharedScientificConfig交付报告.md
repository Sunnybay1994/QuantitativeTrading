# M3-G8F-R2F-V2 Shared Scientific Config 交付报告

状态：`EVIDENCE_UPDATE_DELIVERY_READY`（仅记录既有 Windows 工程验证证据组合；本轮未运行 Python、pytest、Ruff、mypy、cold、真实数据/Qlib、网络或 stage；不表示 actual successor、A14/A15/A17 或任何 M3 Gate 完成）

- task id：`M3-G8F-R2F-V2-SHARED-SCIENTIFIC-CONFIG`
- exact base/head：`fbf783ef40d9a73136ff1979409c4d369580c220`
- branch：`codex/m3-g8f-r2f-v2-shared-scientific-config`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2f-v2-shared-scientific-config`
- 实现者写集：仅 production、unit test、integration test 与本 delivery；任务书及 review 只读/未改

## 1. 六要素记录

### 1.1 现象

`_validate_request` 已对每个 fold 使用 request-bound path 做 fresh 普通文件读取、raw bytes SHA 校验、fresh `load_m3_config` 等值校验、scientific identity 收集和 fresh `verify_g1_release`，但随后仍要求 raw/full config identity 集合均为 2。两条 fold 使用同一经济/scientific config 时因此被错误拒绝。与此同时 release identity 仅检查 list 长度 2，两个完全相同的 `(manifest.release_id, manifest_sha256)` 可穿透。

### 1.2 根因

R2F/R2F-V1 的 148/148 字段审计只找到 G1 request rate、retry attempts、retry backoff 三个有条件候选；只有存在两条真实 G1 lane 的不同配额、失败预算或退避政策及对应 release policy 证据时，差异才有业务含义。当前没有这组事实，任意改值只是 identity padding，破坏 fold/lane 身份应来自显式 request/config/release/执行闭包的不变量。

### 1.3 应遵循规则

- 删除 raw/full config identity 集合及其必须互异的 size 门禁；不替换成任何仍暗示集合为权威的变体。
- 保留每 fold 的 exact path、ordinary/non-reparse fresh read、raw SHA、canonical identities、fresh loader 等值及 G8/toolchain closure；同一 physical file 也必须逐 fold fresh 读取，不能缓存第一 fold 结果。
- scientific identity 仍必须 exact one。
- release identity 仍必须 list arity exact 2，并以 canonical `(manifest.release_id, manifest_sha256)` 的 set cardinality exact 2；相同对象、wrapper 或 path alias 仍拒绝。
- 所有 request/config/release closure 失败仍归一为 `SUCCESSOR_INPUT_INVALID`，且发生在 controlled root、stage、worker、terminal 写入前。

### 1.4 最小复现

1. 两个 stable-sorted folds 各自绑定 `configs/fold_001.toml` 与 `configs/fold_002.toml`，两个文件 bytes、loaded object、raw/full/scientific identity 完全相同：旧实现因 raw/full set cardinality 拒绝；本实现逐 fold fresh closure 后允许。
2. 两个 folds 绑定不同 `VerifiedG1Release` wrapper，但其 manifest release id 与 manifest SHA 相同：旧实现因只检查长度 2 放行；本实现因 tuple set cardinality 为 1，在任何 stage handler 前拒绝。

### 1.5 新增测试

- unit：`test_validate_request_allows_shared_config_with_two_fresh_loads` 记录两个 exact request-bound paths，证明 loader 调用恰为每 fold 一次；`test_validate_request_rejects_duplicate_release_identity` 证明 duplicate release 归一为 `SUCCESSOR_INPUT_INVALID` 且两 fold closure 均已执行。
- integration：`test_same_config_paths_run_two_distinct_folds_with_fresh_closure` 使用不同 config paths 的相同 bytes/object 完整运行 two-fold，并断言 fold execution 及 release identity 仍 distinct；`test_same_config_replay_is_exact_and_second_fold_tamper_fails_fresh` 覆盖 exact replay 无二次 publication 与第二 fold bytes tamper；`test_same_config_duplicate_release_identity_fails_before_stage_work` 使用不同 wrapper、同 release tuple，断言 `public_api_calls` 为空、terminal/receipts 未写入。
- 既有不同 raw/full、同 scientific 的正向 fixture 保持不变；既有 fold order、G8 root、toolchain、receipt ownership 和 terminal/replay 测试未改其合同。

### 1.6 通过条件

静态实现满足任务书的 shared-config、per-fold fresh closure、scientific exact1 与 release exact2/distinct 生产合同；实际测试、Ruff、mypy、cold import、review 和 Windows evidence 仍须由后续授权流程验证后才能判断可验收。

## 2. 实际 diff 与文件范围

### 2.1 Production

`src/quant/research/m3/successor_runtime.py`：

- 删除 `config_identities`、`full_config_identities` 收集及其 `len == 2` 门禁。
- 修正注释，明确 raw/full 已在循环内逐 fold 闭合，不要求 artificial distinct。
- 将 release 检查强化为 `len(release_identities) == 2 and len(set(release_identities)) == 2`。
- 未修改 two-fold identity version、terminal/receipt schema、stage/gate 顺序、public verifier 或 bridge/config。

### 2.2 Tests

仅修改：

- `tests/unit/test_m3_successor_runtime.py`
- `tests/integration/test_m3_successor_runtime.py`

测试 helper 只通过既有 monkeypatch seam 构造最小 request/release/config；不修改 bridge、production verifier，不创建 test-only public hook。

### 2.3 首轮 STATIC 文件 SHA-256（历史）

以下保留首轮交付写集的 SHA-256，返工后的当前 SHA 见 §5.2；delivery 自身 SHA 由返工定稿后的只读快照采集。

| 文件 | SHA-256 |
| --- | --- |
| `src/quant/research/m3/successor_runtime.py` | `CD5A33492B399419389D5A8E93808AD4E918F3388EE5F87479FA4C5A531323BE` |
| `tests/unit/test_m3_successor_runtime.py` | `2E120707FFB75DF2CC3363BF87EC6F8A7E47F929B7A18CD95B40445809EB37FA` |
| `tests/integration/test_m3_successor_runtime.py` | `935C825B21653B9B627CFE9D181E87BA71809E5E372EA085507B85AC53FA463D` |

## 3. STATIC_ONLY 与未运行边界

本轮没有运行 Python、pytest、Ruff、mypy、cold import、真实 successor、Qlib、data/network、worker、controlled stage、root/request/release/evidence 创建、stage、Git stage 或 commit。`git diff --check` 为静态检查；未以它替代运行验证。

以下仍未证明：

- 独立 review：`docs/framework/reviews/M3_G8F_R2F_V2_SharedScientificConfig独立初验报告.md` 尚待不同上下文 reviewer 创建；review SHA 当前 `UNKNOWN/UNRUN`。
- Windows validation evidence：identity、focused unit/integration、Ruff、mypy、cold、exact6 scope/diff/temp/cache/process 均 `UNRUN`；无 evidence root/SHA。
- formal config values、controlled root、A14 scientific config、A15、A17、actual successor/Qlib、new root、retained、acceptance、M3 Gate 与 Linux Gate 均未关闭或运行。

## 4. 后续边界

只有独立 review 输出 `STATIC_REVIEW_PASS` 后，才能按任务书申请唯一 Windows CPU validation。即使该 validation 通过，也不能改写为 formal config ready、actual successor/Qlib、retained、A14/A15/A17 或 M3 Gate 完成。

## 5. STATIC_REWORK1：P1-F1/P1-F2 返工

原独立 reviewer 的 `STATIC_REVIEW_FAIL / P1-F1 + P1-F2`（review SHA：`5cee5a1ea9fbcf312c70c2e7d1f12fd8c94082b698f923199b12cbabf33b8a17`）指出：首轮测试使用两个 physical config 文件，未证明同一 physical config 在第二 fold 仍 fresh read/load；也未在同一 physical config 的 integration 正向中逐项锁定 work、receipt、gate、attestation、terminal 与 replay closure。

### 5.1 现象—根因—应遵循规则—最小复现—新增测试—通过条件

| 要素 | 本轮记录 |
| --- | --- |
| 现象 | 首轮 unit/integration 分别绑定 `fold_001.toml` 与 `fold_002.toml`；第二 fold bytes drift 只发生在已发布 terminal 的 replay 校验之后。 |
| 根因 | 测试夹具未使用任务书冻结的同一 `PurePosixPath("configs/shared.toml")`，且没有把第二次 read/load 的调用序列、第二 fold 前 drift 和完整闭包作为可观察断言。 |
| 应遵循规则 | 两个 stable-sorted request fold 必须 exact 绑定同一 shared path；unit fresh loader path 序列 exact `[shared, shared]`；第二次 read/load 或 bytes/config drift 必须在 stage/public runner/terminal 写入前归一为 `SUCCESSOR_INPUT_INVALID`；不得新增 production hook/API。 |
| 最小复现 | 两 fold 均绑定 `configs/shared.toml`；首次 loader 返回 equal config 后篡改该 physical file；第二 fold fresh `_read_regular_file` 观察 raw SHA drift。另以 distinct `VerifiedG1Release` wrapper 复用同一 release tuple。 |
| 新增测试 | unit：shared path fresh×2、unbound third file 不扫描、second-load config drift、duplicate release；integration：shared path 完整双 fold、distinct paths/equal bytes 正向、read/load 次数、work key 重算与互斥、shared/non-shared receipt ownership、四 Gate 顺序与 identity 重算、两 fold attestation binding、two-fold identity、exact replay 无二次 publication、第二 fold drift 前置拒绝、wrapper 同 tuple 拒绝。 |
| 通过条件 | 代码与测试静态上覆盖 P1-F1/P1-F2，且未扩大白名单；本轮未运行测试，不能将静态覆盖写成 runtime PASS。 |

### 5.2 当前返工实际 scope 与 SHA

本轮仅修改任务书 §10.3 允许的两个测试文件和本 delivery；production 保持冻结 SHA `cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be`。当前文件 SHA 在报告定稿前采集如下：

| 文件 | SHA-256 |
| --- | --- |
| `src/quant/research/m3/successor_runtime.py` | `CD5A33492B399419389D5A8E93808AD4E918F3388EE5F87479FA4C5A531323BE` |
| `tests/unit/test_m3_successor_runtime.py` | `4D2CDDC93E03486C98BE4734F19BC93DB16C82EDF96BE4C19A9570089A108DDC` |
| `tests/integration/test_m3_successor_runtime.py` | `8C040C593239C2D3427490FD411ADC2EE62D675C395970E29FBA2A4FEF3271D4` |
| `docs/framework/deliveries/M3_G8F_R2F_V2_SharedScientificConfig交付报告.md` | `由最终只读快照采集` |

### 5.3 STATIC_ONLY / UNRUN

本轮未运行 Python、pytest、Ruff、mypy、cold import、真实 successor/Qlib、data/network、worker、root/request/release/evidence 创建、controlled stage、Git stage 或 commit。`git diff --check` 若执行，仅是文本静态检查，不替代任何运行证据。

仍待原独立 reviewer 只读复验并写入 `docs/framework/reviews/M3_G8F_R2F_V2_SharedScientificConfig独立初验报告.md`；review PASS 前不得申请 Windows validation。A14 scientific config values、controlled root、A15、A17、actual successor/Qlib、new root、retained、acceptance、M3 Gate 与 Linux Gate 均未关闭。

## 6. STATIC_REWORK2：P1-F3 调用次数返工

### 6.1 现象—根因—应遵循规则—最小复现—修正测试—通过条件

| 要素 | 本轮记录 |
| --- | --- |
| 现象 | REWORK1 正向只断言 `load_calls == [shared, shared]`、`release_calls == 2` 与 `read_calls == load_calls`，但完整首次运行包含 pre-stage request validation 和 post-publish terminal fresh verification 两轮 request closure。 |
| 根因 | 测试计数只覆盖了第一轮 `_validate_request`，错误地把 terminal fresh verification 的第二轮闭包视为异常；同时 `_verify_controlled_tree` 会对 controlled output 内 receipt/artifact 做既有 fresh reads。 |
| 应遵循规则 | 不得删除 terminal fresh verify、修改 production、放宽为 `>=2` 或停止记录。same-physical 正向必须 exact：loader shared×4；release 顺序为 fold1/fold2/fold1/fold2；关注序列 `read_calls` 为 shared×4 后 canonical `completion.json`；完整内部 read 另行保留并确认额外读取仅来自 controlled output tree。 |
| 最小复现 | `_run` 首次成功：`run_two_fold_successor → _validate_request`，发布 terminal 后 `verify_terminal_attestation → _validate_request → _read_regular_file(completion.json)`，随后 controlled-tree verifier 读取已发布 tree。 |
| 修正测试 | integration same-physical 正向现断言 `load_calls` exact4、`release_calls` exact stable order、focused `read_calls` exact `[shared, shared, shared, shared, terminal]`，并保留 `all_read_calls` 对 unbound/config 路径与 controlled-output tree 范围的约束；§10 全部 closure/replay 断言保持。 |
| 通过条件 | 测试结构与既有 production 控制流逐项闭合，未放宽计数或移除 terminal fresh verify；本轮未运行测试，不能将静态结构写成 runtime PASS。 |

### 6.2 当前 REWORK2 scope 与 SHA

本轮仅修改 integration test 与本 delivery；production、unit、taskbook、review 均冻结。当前 SHA 在最终报告定稿前采集如下：

| 文件 | SHA-256 |
| --- | --- |
| `src/quant/research/m3/successor_runtime.py` | `CD5A33492B399419389D5A8E93808AD4E918F3388EE5F87479FA4C5A531323BE` |
| `tests/unit/test_m3_successor_runtime.py` | `4D2CDDC93E03486C98BE4734F19BC93DB16C82EDF96BE4C19A9570089A108DDC` |
| `tests/integration/test_m3_successor_runtime.py` | `F161C237CBD40E3BB3E8BDFBB7E0CB114B48DC8F9FADBEA77AA34151FB22321E` |
| `docs/framework/deliveries/M3_G8F_R2F_V2_SharedScientificConfig交付报告.md` | `待最终只读快照采集` |

### 6.3 STATIC_ONLY / UNRUN

本轮仍未运行 Python、pytest、Ruff、mypy、cold、Qlib、data/network、worker、root/request/release/evidence、stage 或 commit。`git diff --check` 只能作为文本静态检查，不能替代运行证据。REWORK2 完成后交回同一原 reviewer，只写调用图复验；review PASS 前不得申请 Windows validation。

## 7. STATIC_REWORK3：P1-F4 观测域更正

### 7.1 现象—根因—应遵循规则—最小复现—新增测试—通过条件

| 要素 | 本轮记录 |
| --- | --- |
| 现象 | REWORK2 用 `all_read_calls`、`tracked_read_paths`、`dedupe_read_paths` 拼接过滤/去重视图，把 runtime 的窄 `_read_regular_file` 记录误写成完整 I/O 序列，并把 terminal/tree 读取错误地混入 request validation 的顺序合同。 |
| 根因 | `_validate_request` 的真实调用边界与 run-state/controlled-tree 的既有读取边界未分层；过滤、去重及复制内部读取算法遮蔽了原控制流，不能证明每轮 request validation 的 exact slice。 |
| 应遵循规则 | 删除上述过滤/去重视图。由 test-owned wrapper 包裹原 `runtime._validate_request`，先记录 `runtime_read_calls`、`load_calls`、`release_calls` 的起点，真实调用原函数且不改变控制流，成功返回后保存三者 slice。完整 `_run` 必须 exact 两轮；每轮 runtime read `[shared, shared]`、load `[shared, shared]`、release `[fold1, fold2]`。全局只记录未过滤的 `runtime_read_calls`；轮外 runtime reads 不得含 unbound config，均在 controlled root，且 canonical terminal fresh-read 至少一次。不得 monkeypatch/复制 `run_state` 内部读取算法，不删除 terminal fresh verify。 |
| 最小复现 | `_run` 首轮 request validation 读取同一 physical `configs/shared.toml` 两次；发布后 terminal fresh verification 触发第二轮同样的 request closure，再读取 canonical `completion.json`；随后既有 controlled-tree verifier 读取 receipt/artifact。只能用 wrapper 的前后 slice 证明两轮，不能用全局过滤序列替代。 |
| 新增测试 | integration helper 改为仅维护未过滤 `runtime_read_calls`；新增 test-owned `_validate_request` wrapper，按调用前后保存 exact read/load/release slices；same-physical 正向断言两轮 exact2、shared read/load exact2、release fold1/fold2，并保留 terminal、controlled-root、unbound、work/receipt/gate/attestation/two-fold/replay closure；second-fold drift 继续断言第二次 fresh runtime read 前置拒绝。 |
| 通过条件 | 静态结构删除旧过滤/去重观测，且 exact 两轮及轮外边界断言与 production 既有控制流一致；本轮未运行测试，不能将静态覆盖写成 runtime PASS。 |

### 7.2 当前 REWORK3 scope 与 SHA

本轮仅修改 `tests/integration/test_m3_successor_runtime.py` 与本 delivery；production、unit、taskbook、review 均保持只读。production/unit 的冻结 SHA 分别为 `cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be` 与 `4d2cddc93e03486c98be4734f19bc93db16c82edf96be4c19a9570089a108ddc`；integration 与本 delivery 的最终 SHA 在报告定稿后由只读快照采集。

| 文件 | SHA-256 |
| --- | --- |
| `src/quant/research/m3/successor_runtime.py` | `CD5A33492B399419389D5A8E93808AD4E918F3388EE5F87479FA4C5A531323BE` |
| `tests/unit/test_m3_successor_runtime.py` | `4D2CDDC93E03486C98BE4734F19BC93DB16C82EDF96BE4C19A9570089A108DDC` |
| `tests/integration/test_m3_successor_runtime.py` | `F2D760BC96DAC5E0D52E97011A4333484802DA18CD9094C01003A35FA6974F82` |
| `docs/framework/deliveries/M3_G8F_R2F_V2_SharedScientificConfig交付报告.md` | `待最终只读快照采集` |

### 7.3 STATIC_ONLY / UNRUN

本轮未运行 Python、pytest、Ruff、mypy、cold、Qlib、data/network、worker、root/request/release/evidence、controlled stage、Git stage 或 commit。`git diff --check` 若执行，仅是文本静态检查，不替代运行证据。独立 review、Windows validation、exact6 scope/diff/temp/cache/process、formal config values、controlled root、A14/A15/A17、actual successor/Qlib、new root、retained、acceptance、M3 Gate 与 Linux Gate 均保持 `UNRUN`/未关闭；必须由后续授权流程处理。

### 7.4 Manager-gate correction

门禁复核进一步要求删除全局位置假设 `runtime_read_calls[:4] == [shared] * 4`。现改为对 raw、未修改的 `runtime_read_calls` 做位置无关的 exact shared-path closure：筛选 path 等于 `shared_path` 的条目必须恰为四次；同时每一条全局记录必须是 `shared_path` 或位于 controlled output root 内，unbound config 仍明确拒绝，canonical terminal read 至少一次。`validation_rounds == [expected_round, expected_round]` 仍是唯一的逐轮顺序权威；未放宽为 `>=2`，未删除 terminal fresh verify，未改变 production/unit/taskbook/review。

## 8. STATIC_REWORK4：replay fresh-verification 断言更正

### 8.1 V3 证据与现象—根因—应遵循规则—最小复现—修正测试—通过条件

| 要素 | 本轮记录 |
| --- | --- |
| V3 证据 | 独立 Parser preflight 后的 VALIDATION3：identity PASS；unit PASS；integration `29 passed / 1 failed`；Ruff/mypy/cold/scope UNRUN。evidence root 为 `artifacts/agent_runs/m3-r2f-v2-validation3-20260828T121638Z`，summary SHA 为 `3bc22a591a7d64d9479cd3cef5de112f65691561d1835f46d582ce39604f418f`，integration stdout SHA 为 `ad36fc0e781bb7bcd8a2210d2dc17d727013f390a9fe6166e3a33a5e518e569f`；basetemp/cache/Python/0xF00 residue 已清零。 |
| 现象 | `test_same_config_replay_is_exact_and_second_fold_tamper_fails_fresh` 首次运行后有 31 条 `public_api_calls`，exact replay 增加 4 条既有 Gate public verifier 调用；失败断言错误地把 fresh verification 误判成第二次 publication。 |
| 根因 | replay 合同只保存并比较调用总长度，没有区分首次运行 prefix 与 replay fresh-verification suffix，因而无法证明“无第二次 stage/work/publication”与“允许既有四 Gate fresh verify”同时成立。 |
| 应遵循规则 | 首次完整 `public_api_calls` 必须作为 prefix 保持逐字不变；replay 新增 suffix 必须 exact 为 `summary-public-verify`、`reproducibility-public-verify`、`readiness-public-verify`、`acceptance-public-verify`，并显式排除 public-run、run-plan、upstream/formal wave 与 publication。replay 后保存 `calls_after_replay`；shared config drift 重试必须在任何新增 public verifier/stage/publication 前归一为 `SUCCESSOR_INPUT_INVALID`，调用数保持不变。`reused`、attestation、terminal 与 two-fold identity 继续 exact 不变。 |
| 最小复现 | 首次 `_run` 发布 terminal 后记录完整 public-call prefix；第二次 exact replay 触发 terminal verifier 的四个 Gate public verify；随后篡改同一 shared config，第三次 `_run` 在 request validation 阶段拒绝，不新增任何 public call。 |
| 修正测试 | integration replay 测试保存 `first_public_api_calls`，断言 replay 前缀逐字相等，断言 suffix exact 四项并排除 run/public/wave/publication 调用，随后保存 `calls_after_replay`；tamper 失败断言 `SUCCESSOR_INPUT_INVALID` 且调用长度不变。未修改 production、terminal verifier、unit 或其他 integration 反例。 |
| 通过条件 | 静态结构只放宽到既有四项 fresh verifier suffix，不接受 `+4` 或任意 suffix；保留 replay identity 与 drift 前置拒绝。V3 的 29/1 结果不被改写为本轮 runtime PASS。 |

### 8.2 当前 REWORK4 scope 与 SHA

本轮仅修改 `tests/integration/test_m3_successor_runtime.py` 与本 delivery；production、unit、taskbook、review 保持只读。REWORK4 后最终 SHA 与字节数由只读快照采集。

| 文件 | SHA-256 |
| --- | --- |
| `src/quant/research/m3/successor_runtime.py` | `CD5A33492B399419389D5A8E93808AD4E918F3388EE5F87479FA4C5A531323BE` |
| `tests/unit/test_m3_successor_runtime.py` | `4D2CDDC93E03486C98BE4734F19BC93DB16C82EDF96BE4C19A9570089A108DDC` |
| `tests/integration/test_m3_successor_runtime.py` | `待最终只读快照采集` |
| `docs/framework/deliveries/M3_G8F_R2F_V2_SharedScientificConfig交付报告.md` | `待最终只读快照采集` |

### 8.3 STATIC_ONLY / UNRUN

本轮未运行 Python、pytest、Ruff、mypy、cold、Qlib、data/network、root/request/release/evidence、stage 或 commit。V3 的 integration `29 passed / 1 failed` 是既有外部验证边界，不是本轮重跑证据；本轮仅做静态测试/报告修改。review 复验、post-fix integration、Ruff exact3、mypy、cold、exact6 scope/diff/temp/cache/process 与所有 Gate 仍为 `UNRUN` 或待后续授权流程。

## 9. EVIDENCE_UPDATE：V1–V5 Windows 工程验证闭环

### 9.1 轮次结论与可采用范围

以下内容逐字绑定 taskbook §14 的既有证据；本轮只更新文档，不重跑任何阶段。

| 轮次 | 真实结论 | 可采用证据 | 不得继承的范围 |
| --- | --- | --- | --- |
| V1 | `CARRIER_SYNTAX_INVALID_BEFORE_PRODUCT_EVIDENCE` | Python 0-call、资源未取得；summary SHA `47755ef671684c5f915629ddba624552c7a84d65c2a083ac620e36a1cbf537b8` | 所有产品阶段均 UNRUN；不构成 identity/unit/integration 证据 |
| V2 | `CARRIER_PREFLIGHT_WRAPPER_INVALID_BEFORE_PRODUCT_EVIDENCE` | Parser errors 0、Python 0-call；summary SHA `60501198f959b2db4383b5c71098a7f1f507eec9b9db16d1c3236313755c633b` | 所有产品阶段均 UNRUN；不构成 Windows validation 通过 |
| V3 | 可信产品首失败 | identity PASS；unit full PASS；integration `29 passed / 1 failed`，失败为 REWORK4 test-only replay 计数；summary SHA `3bc22a591a7d64d9479cd3cef5de112f65691561d1835f46d582ce39604f418f`；unit stdout SHA `7f0c60897d815a9e0d812a5ec768f0de50134fbdb41671316b2a62c2d511a2e6`；integration stdout SHA `ad36fc0e781bb7bcd8a2210d2dc17d727013f390a9fe6166e3a33a5e518e569f` | Ruff/mypy/cold/scope UNRUN；失败节点不可计入组合绿测 |
| V4 | post-fix 产品全部 PASS；scope carrier STOP | identity PASS；原失败节点 `1 passed`；Ruff exact3 PASS；mypy production PASS；cold PASS；summary SHA `0165770cda42407a1eb9257d85a3e7748c23cd412a70806748906472111c4468`；replay-node stdout SHA `27b93b41fc7fe0209fb0edde525c85c2884ce93570c953f81487fc13e272dd56`；Ruff stdout SHA `af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af`；mypy stdout SHA `94594db09076fe305d51b50210d0bc5e9d275fb814f8b42c1ed4cf3368392f9a` | scope 三件套不完整；不能单独宣称 exact6/scope PASS |
| V5 | scope-only PASS | exact6 count6、cached0、`git diff --check` exit0；stderr 仅三条 LF→CRLF warning；temp/cache/Python/0xF00 residue 清零；summary SHA `d52f14f869ddcfc3840ad0f6ae72738a5a3a549d8079e795022f9dc36d2c60de` | 未重复任何产品阶段；不补充 actual runtime/Qlib/network 证据 |

已明确绑定的 evidence root 只有 taskbook §13/§14 记录的 V3 root：`artifacts/agent_runs/m3-r2f-v2-validation3-20260828T121638Z`。§14 未提供 V1、V2、V4、V5 的独立 root 路径，本报告不猜测、不补造这些路径；各轮仅采用上表明确列出的 summary/stdout SHA。

### 9.2 有效组合证据与剩余边界

本包当前可采用的组合范围严格为：V3 的 identity PASS、unit full PASS 与 integration 其余 29 项通过；V4 的修正 replay node、Ruff exact3、mypy production、cold；V5 的 exact6/scope/residue PASS。该组合已覆盖 shared-scientific-config 的 Windows contract engineering validation，并明确排除 V3 唯一失败节点、V1/V2 carrier-only STOP 与 V4 scope carrier STOP；不得伪称单轮全绿或继承任何 UNRUN 阶段。

本报告不声明 formal scientific config 或 controlled root（A14）、formal G1 release（A15）、Windows py312/Qlib 环境（A17）、actual successor、真实 Qlib、network、new root、retained resume、acceptance 真实运行或 M3 Gate 完成；A14、A15、A17 与 M3 Gate 继续 OPEN，Linux Gate 亦未声明通过。

### 9.3 EVIDENCE_UPDATE STATIC_ONLY 边界

本轮仅写 delivery；未运行 Python、pytest、Ruff、mypy、cold、Qlib/data/network，未创建 root/request/release/evidence，未执行 stage/commit。production SHA `cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be`、unit SHA `4d2cddc93e03486c98be4734f19bc93db16c82edf96be4c19a9570089a108ddc`、integration SHA `28b79f7276df878351c86b45b0538362547afc03f26df76470e810a703b7bf4f` 与 taskbook/review 均保持只读；delivery 最终 SHA 在本节定稿后采集。
