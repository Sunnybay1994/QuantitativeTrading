# M3-G8F-R2S Formal Summary Stage Publication Compatibility 交付报告

状态：`R2S_WINDOWS_ENGINEERING_VALIDATED`（VALIDATION8 Windows 工程验证闭合；**不**表示 R2A、bridge/CLI、actual worker、真实 Qlib、new root、retained 或 M3 Gate 完成）

- task id：`M3-G8F-R2S-FORMAL-SUMMARY-STAGE-PUBLICATION-COMPAT`
- exact base：`57dcf2e579175ead8d7c833ed7fb4b7bccedc5c5`
- branch：`codex/m3-g8f-r2s-formal-summary-stage-publication-compat`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2s-formal-summary-stage-publication-compat`
- 终态上限：只关闭 summary StageRunner-shaped publication compatibility 的 **Windows 工程验证**；**不**表示 R2A、bridge/CLI、actual worker、真实 Qlib、new root、retained、`FORMAL_SUMMARY_STAGE_PUBLICATION_COMPAT_VALIDATED` 或 M3 Gate 完成。

## 1. 现象—根因—规则—最小复现—新增测试—通过条件

| 字段 | 内容 |
| --- | --- |
| 现象 | legacy `build/verify_research_summary_artifact` 强制根叶名 `horizon={n}`；`make_summary_run_plan` 最终根为 `summaries/{experiment_key}/h{n}/{model}/{model_version}`；`StageRunner` temp 为 `stage_root/.stage-tmp/.{node_id}.*`。三者不可直接组合。 |
| 根因 | legacy API 把 publication leaf 名绑定到科学契约；StageRunner publication identity 使用 canonical plan `final_directory`；handler 只能写 runner 拥有的 temp leaf。 |
| 规则 | 任务书 §3–§6+§10：保留 legacy；三阶段互斥 typed verifier + module-private dispatcher；temp→final 只经 `StageRunner.run_static`；PROJECT-only；错误不泄路径/cause。 |
| 最小复现 | 同经济输入：legacy `horizon={n}`；stage 写 `.stage-tmp` leaf；final publication/artifact 仅 `stage_root/final_relative_path`（artifact 另需 receipt）。 |
| 新增测试 | formal summary legacy/bytes；unit 三阶段互斥/dispatcher 无 fallback/plan/GateExecution/handmade；integration fresh=`build/pre/publication/artifact`、resume=`publication/artifact`。 |
| 通过条件 | legacy 不变；三阶段互斥；dispatcher 无 fallback；STATIC_ONLY 未执行验证命令。 |

## 2. exact diff（白名单 1–5、7）

1. `src/quant/research/m3/evaluate.py`
   - 新增 frozen `FormalSummaryStagePublicationIdentity`
   - 新增 `build_research_summary_stage_artifact` / `verify_research_summary_stage_precommit` / `verify_research_summary_stage_publication` / `verify_research_summary_stage_artifact`（§10 三阶段互斥）
   - 抽取 `_publish_formal_summary_files` / `_verify_formal_summary_at_root` 复用 legacy 科学计算与 canonical serialization
   - legacy `build_research_summary_artifact` / `verify_research_summary_artifact` 仍强制 `horizon={n}`，签名与错误边界不变
2. `src/quant/research/m3/summary_stage.py`（新）
   - `FormalSummaryStageResult` + `run_formal_summary_stage`
   - handler 仅 build；`_make_summary_stage_closure_dispatcher`（exact final→publication，否则 prove temp→precommit，无 fallback）
   - `make_summary_run_plan` → `select_run_plan_nodes` 全闭包 → 唯一 node → `StageRunner.run_static` → post-run artifact verifier
3. `tests/unit/test_m3_formal_research_summary_artifact.py` — legacy 回归 + stage/legacy bytes
4. `tests/unit/test_m3_summary_stage.py`（新；§18–§21 仅改本文件）— 三阶段互斥/dispatcher；canonical evaluation；formal experiment；authority 分域；**§21 真实 model_version 与 horizon 唯一定位**
5. `tests/integration/test_m3_summary_stage.py`（新）— fresh/resume 调用序列锁定；§12 preexisting-no-receipt 恢复与篡改 fail 序列
7. 本交付报告

未改：任务书、review、orchestration/StageRunner、`__init__.py`、successor_runtime、config、共享 SSOT、R2A STOP 现场。未 commit。

终态门禁证据（STATIC_ONLY 静态核对）：

- dirty 范围：exact8 内（`evaluate.py`、`summary_stage.py`、三测试文件、delivery；任务书/review 只读既有 untracked）
- §21 本轮写集：仅 `tests/unit/test_m3_summary_stage.py` + 本 delivery
- `evaluate.py`：`git diff --numstat` ≡ `-w` = `412 14`（本轮未改 typed verifier）；`git diff --check` exit=0；WT/HEAD `CRLF=239`；`i/mixed w/mixed`
- §14：`summary_stage` dispatcher 词法 abspath + 非跟随 lstat；R3 junction/lexical 反例
- 未执行 pytest/Ruff/mypy/网络/commit；未改 review 报告
## 3. 未运行边界（STATIC_ONLY）

禁止并**未执行**：Python、pytest、Ruff、mypy、cold import、真实 Qlib、网络、actual worker、新 root 真实运行、retained、stage/commit。独立初验与经理授权 Windows 定向验证前，不得声称运行态通过。

## 4. 关键实现选择（合同内）

- temp→final 身份证明依赖既有 `StageRunner._run_static_locked` 的 `commit_directory_noreplace(temp → stage_root/final_directory)`；本包不复制/rename/发布文件，故**无需**改 orchestration/StageRunner，不触发 STOP。
- `select_run_plan_nodes` 使用完整 plan node-id 闭包；再要求与当前 horizon/model/version 匹配的**唯一** canonical node（拒 0/2）。
- ~~precommit 接受 identity 绑定的 temp **或** final root（StageRunner 对 temp 与 publish 后 final 调用同一 closure）；final verifier 另函且强制 receipt。~~ **已由 §10 CONTRACT_REFREEZE_B / 下文 §6–§7 supersede**：改为三阶段互斥 + module-private dispatcher。
- precommit/publication 无 receipt 时 `VerifiedResearchSummaryArtifact.summary_receipt_sha256` 为 `"0"*64`；post-run artifact 使用真实 receipt sha。

## 5. STATIC_REWORK1：`evaluate.py` EOL 最小变更闭包

| 字段 | 内容 |
| --- | --- |
| 现象 | 首次交付后 `evaluate.py` 整文件 LF 化，普通 `git diff` 出现约 825 行换行噪声（`--numstat` 远大于语义 `-w`），`ls-files --eol` 曾为 `w/lf`。 |
| 根因 | 编辑器/工具链把工作树写成纯 LF，而 base blob 为 **mixed**（HEAD：`CRLF=239` / `LF_ONLY=2223`）；整文件统一 EOL 会把未改行也打进 diff。 |
| 规则 | 任务书 §9：恢复与 base 一致的物理换行，保留语义增量；`--ignore-space-at-eol`/`-w` 语义 diff 不因返工增减；其他 production/test 字节不动；`git diff --check` PASS；exact8 不变。 |
| 最小复现 | 对 base blob 做字节级 splice：仅替换 summary formal API 段与两处 import（`stat`、`PurePosixPath`）；未改行保留 HEAD 原 CRLF/LF；新增段使用与邻域一致的 LF。 |
| 通过条件 / 证据 | 初态证据见当时 `333 14`；**最终以 §7 为准**。仍 STATIC_ONLY，未跑 Python/pytest/Ruff/mypy/网络/commit。 |

## 6. ARCHITECTURE_STOP 与 CONTRACT_REFREEZE_B（任务书 §10）

| 字段 | 内容 |
| --- | --- |
| 现象 | 首次交付把 precommit 做成 temp/final 双相，试图迎合 StageRunner 对同一 `closure_verifier` 先 temp 后 final 的调用序列；与“precommit 严格 temp-only”冲突。 |
| 根因 | `StageRunner._run_static_locked` 对 closure 分别传入 temp、发布后 final、reuse final；单一 temp-only precommit 无法覆盖 final 调用点。 |
| 规则 | §10 取代原 §4–§5 冲突表述：三阶段互斥强类型；`summary_stage` 唯一 module-private dispatcher（exact final→publication，否则证明 temp→precommit；禁止 try-temp/catch-as-final）。 |
| 最小复现 | 合法 temp 内容 tamper → 只走 precommit 失败；canonical final tamper → 只走 publication 失败；任意/alias root → 失败且不跨 phase 重解释。 |
| 新增测试 | unit：`test_three_phase_verifiers_are_mutually_exclusive`、`test_dispatcher_routes_without_temp_final_fallback`；integration：fresh=`build/pre/publication/artifact`，resume=`publication/artifact` 且无 `pre`。 |
| 通过条件 | temp∉publication/artifact；final∉precommit；dispatcher 无 fallback；旧“precommit 接受 temp 或 final”表述失效。 |

实现要点：

1. `evaluate.py`：`verify_research_summary_stage_precommit`（temp-only）、新增 `verify_research_summary_stage_publication`（final pre-receipt）、`verify_research_summary_stage_artifact`（post-run final+receipt）。
2. `summary_stage.py`：handler **仅 build**；`_make_summary_stage_closure_dispatcher` 做 root 身份路由；`run_static` 返回后调用 artifact verifier。
3. 删除 temp/final fallback helper；未改 orchestration/StageRunner。

## 7. STATIC_REWORK2：EOL 误恢复事故与语义重建（任务书 §11）

| 字段 | 内容 |
| --- | --- |
| 现象 | STATIC_REWORK1 误将 `evaluate.py` 整文件恢复为 HEAD，stage publication 语义曾丢失；旧 delivery 未及时更正。 |
| 根因 | 失败的整文件 LF/`git apply` 路径覆盖了已批准语义块，而非“保留语义 + 恢复未改行物理 EOL”。 |
| 规则 | §11：以 base 为干净起点按 §3–§6+§10 重建；未改行保留 base 物理字节；新增/修改 hunk 用 LF 且无 CR 尾随空白；同步 tests/dispatcher；delivery 追加事故与最终 exact diff。 |
| 处置 | 对 HEAD blob **字节拼接**重建三阶段 API（非整文件覆盖）；同步 `summary_stage.py` 与 tests；本报告 supersede 旧双相表述。 |
| 最终 exact diff 证据（交付前静态核对） | 见交付末“终态门禁”；`evaluate.py` 语义 hunks only；ordinary `git diff --check` PASS；dirty 仅 exact8。 |

## 8. MANAGER_STATIC_REWORK3：preexisting final without receipt（任务书 §12）

| 字段 | 内容 |
| --- | --- |
| 现象 | §10 要求 preexisting-no-receipt recovery；此前交付未锁定该序列。 |
| 规则 | 先真实 `run_formal_summary_stage` 形成 final，精确删除 receipt；内容未漂时 `resume=True` 必须 fresh 走 final publication closure，不得用 temp precommit 采信 final；恢复后 post-run artifact+receipt 闭合。receipt 缺失且 final bytes 被篡改时 fail closed，不发新 receipt，不转 temp phase。 |
| 新增测试 | `tests/integration/test_m3_summary_stage.py::test_actual_summary_stage_preexisting_final_without_receipt` |
| 锁定序列 | 恢复成功：`publication(final) → build(temp) → pre(temp) → publication(final) → artifact(final)`；`pre` 根仅 `.stage-tmp`；`publication` 根仅为 canonical final；receipt 恢复后出现。篡改 fail：`["publication"]` only，`STAGE_RECOVERY_CONFLICT`，receipt 仍缺失，无 build/pre/artifact。 |
| 范围 | 仅 exact8 测试+delivery；未改 production。仍 STATIC_ONLY。 |

## 9. REVIEW_FAIL → STATIC_REWORK4：temp leaf exact ownership 与 link/reparse（任务书 §13）

| 字段 | 内容 |
| --- | --- |
| 现象 | (1) `_require_stage_temp_output_root` 仅 `startswith(f".{node_id}.")`，`v1` 可吞掉 `v1.2` sibling leaf；(2) §6 要求的 symlink/reparse 反例缺失。 |
| 根因 | 前缀匹配把更长 sibling node 的 leaf 误认为本 node 的 mkdtemp leaf；测试未锁定 link/reparse fail-closed。 |
| 规则 | temp leaf = exact `.{node_id}.` + 非空唯一后缀；后缀禁止 `.`、路径分隔符及非 `tempfile.mkdtemp` 字符集 `[a-z0-9_]`。不得仅加长 startswith。build / 三阶段 verifier / dispatcher 对 symlink 与 reparse 属性注入均 fail closed。 |
| 最小复现 | `node_id=…v1` 下 leaf `.…v1.2.abc12xyz`：startswith 为真但 exact 后缀含 `.` → 拒绝。对 temp/final `os.lstat` 注入 `st_file_attributes|=0x400` → 全路径拒绝。 |
| 新增测试 | `test_temp_leaf_exact_ownership_rejects_longer_sibling_and_bad_suffix`；`test_temp_final_symlink_and_reparse_injection_fail_closed`（属性注入必测；host 可创 symlink/junction 时追加真实链路）。 |
| 通过条件 | sibling/空后缀/非法后缀拒绝；合法 mkdtemp 后缀可 build；reparse 注入覆盖 build/precommit/publication/artifact/dispatcher；`evaluate.py` `git diff --numstat`≡`-w`=`412 14`，`git diff --check` PASS，CRLF=239 与 HEAD 对齐；dirty 仍 exact8（不含 review）。 |

生产改动：`evaluate.py` 新增 `_MKDTEMP_SUFFIX_CHARS` + `_require_stage_temp_leaf_name`，由 `_require_stage_temp_output_root` 调用。编辑器曾将 `evaluate.py` 整文件 CRLF 化；已按 HEAD 物理字节语义拼接恢复（非整文件覆盖），未改 review 报告。

## 10. REVIEW_FAIL → STATIC_REWORK5：dispatcher 原始叶身份闭包（任务书 §14）

| 字段 | 内容 |
| --- | --- |
| 现象 | dispatcher 在非跟随检查前对 root/candidate final `resolve(strict=True)`，随后 `lstat`/转发的是解析目标；exact final lexical leaf 为 junction/symlink 时可能绕过 typed verifier 的 `abspath≠resolve`/reparse 拒绝。 |
| 根因 | resolve-before-check 丢失原始叶身份，并把 resolved target 交给 publication。 |
| 规则 | §14：只形成词法 `raw_absolute=Path(os.path.abspath(root))`；先对 raw 做非跟随 `lstat` 拒 symlink/reparse/非目录；phase 仅 `normcase(raw)` vs `normcase(candidate_final_lexical)`；typed verifier 只收 `raw_absolute`；禁止 resolve 替代、phase fallback、guard 放宽。 |
| 最小复现 | final leaf = junction→独立真实 summary 树：direct `verify_research_summary_stage_publication` 拒绝；同 path 经 dispatcher 亦拒绝，且无成功 publication、无 precommit fallback。wrong-lexical 同内容目录只走失败 pre；shadow symlink 在 phase 前拒。 |
| 新增测试 | `test_dispatcher_r3_final_junction_and_lexical_alias_reject`（恒定 lexical/`..`；host 可用时 shadow + exact-final junction/symlink）。 |
| 通过条件 | `summary_stage._make_summary_stage_closure_dispatcher` 无 phase 前 resolve；exact8；`git diff --check` PASS；未改 evaluate typed verifier / review。 |

生产改动：仅 `summary_stage.py` dispatcher。未放宽 `evaluate.py` 三阶段 verifier。

## 11. VALIDATION2 STOP → STATIC_REWORK6：h10 fixture 字段归属（任务书 §15 / F4）

| 字段 | 内容 |
| --- | --- |
| 现象 | VALIDATION2：Parser/BOM、argv sentinel、identity 三重 carrier **PASS**；focused exact3 有效执行 **9 passed / 14 failed**。14 项失败均在 `_stage_bundle` 构造 h10 时炸在 fixture，summary stage 测试体未进入。 |
| 根因 | inner `replace(item.manifest, …)` 误传 `evaluation_receipt_sha256`；该字段属于外层 `VerifiedEvaluationArtifact`，不属于 `EvaluationManifestV1`。 |
| 规则 | §15：inner manifest replace 仅 `horizon_sessions=10` + 对应 `work_key`；outer artifact replace 设 `root`、更新后 manifest、`evaluation_receipt_sha256=receipt_sha`。禁止改 schema/contracts/`Any`/`type: ignore`或预判后续逻辑。 |
| 最小复现 | 非法 keyword 进入 `EvaluationManifestV1` → TypeError/构造失败于 `_stage_bundle`，与 production 无关。 |
| 修正测试 | 仅 `tests/unit/test_m3_summary_stage.py`：删除 manifest replace 中非法 keyword；outer 保留 `evaluation_receipt_sha256=receipt_sha`；receipt file/SHA、h10 context/upstream/fold/model 闭包不变。 |
| 通过条件 | fixture 可构造；production/`evaluate.py`/`summary_stage.py`/其他 tests/taskbook/review **字节未改**；不得把未运行的 VALIDATION3/Ruff/mypy/cold 写成通过。 |

引用边界：VALIDATION2 carrier 三重 PASS + 9 绿 / 14 失败（fixture 归属，非 production 失败）。Ruff、mypy、cold、scope 均未运行。

## 12. VALIDATION3 STOP → STATIC_REWORK7：canonical summary plan fixture（任务书 §16 / F5）

| 字段 | 内容 |
| --- | --- |
| 现象 | VALIDATION3：Parser/BOM、argv sentinel、identity carrier **PASS**；focused exact3 **18 passed / 5 failed**。5 项失败均在 `run_formal_summary_stage` 的 public plan/input 阶段；后续 Ruff/mypy/cold/scope **UNRUN**。 |
| 根因 | legacy h5 使用任意 `sha256("work-{index}")`；h10 只同步 manifest；root/receipt 非 `make_summary_run_plan` 要求的 public work publication tree（`work/<work_key>/evaluation` + `receipts/evaluation/<work_key>.json`），且 `manifest.work_key` 必须逐字等于 `compute_work_key(experiment_key, fold, horizon)`。 |
| 规则 | §16：每 fold+horizon 唯一 canonical work_key；同步 manifest/metrics/`evaluation_spec`（h10 另同步 label/prediction horizon）；canonical 路径逐项构造；对象字段变更后用既有 `_canonical_bytes(asdict(...))` 重写 metrics/manifest 并重算 outer hashes；upstream/`by_root` 同步；fixture 自证 + `make_summary_run_plan` 可构造 h5+h10 exact nodes。 |
| 最小复现 | 非 canonical work_key/path → `make_summary_run_plan` / stage 入口 `STAGE_INPUT_INVALID`（summary 测试体未进入科学路径）。 |
| 修正测试 | 仅 `tests/unit/test_m3_summary_stage.py`：新增 `_materialize_canonical_evaluation`；重写 `_stage_bundle`；科学内容/production/dispatcher/R3 闭包不变；不处理 `VerifiedG1Release` repr。 |
| 通过条件 | fixture 自证通过；`make_summary_run_plan` 产出 `summary.h5.*` 与 `summary.h10.*`；production/`evaluate`/`summary_stage`/另两 tests/taskbook/review **未改**；不得把 VALIDATION4/Ruff/mypy/cold 写成通过。 |

引用边界：VALIDATION3 carrier PASS + **18 pass / 5 fail**；Ruff、mypy、cold、scope、VALIDATION4 **UNRUN**。

## 13. VALIDATION4 STOP → STATIC_REWORK8 / F6：`CONTRACT_STOP`（任务书 §17）

| 字段 | 内容 |
| --- | --- |
| 现象 | VALIDATION4：Parser/BOM、argv sentinel、identity **PASS**；focused exact3 **9 passed / 14 failed**。F5 evaluation canonical 门禁已越过；14 项失败统一在 `make_summary_run_plan` 自证的 `_experiment_boundary_inputs`。后续 Ruff/mypy/cold/scope **UNRUN**。 |
| 根因 | bundle 对象 exact type 为 `VerifiedExperimentIdentity`（`test_m3_alignment.py::_formal_nominals` 包装），故 `_experiment_boundary_inputs` 要求 stage=`experiment-identity`、path=`receipts/experiment-identity/<key>.json`。但 fixture 链 legacy receipt 实际由 `test_m3_label_artifact.py::_experiment` 以 **development** stage 发布。 |
| 规则 | §17：须复用 legacy 已验证 receipt 的 **exact bytes**，且静态证明其中 stage/scope/scope_key 逐字为 formal `experiment-identity`；若为 development 或无法证明 → **立即 CONTRACT_STOP**，禁止发明第二套 receipt / 改名冒充。 |
| 最小复现 / 精确证据 | 见下表。未改 `tests/unit/test_m3_summary_stage.py`（无法在白名单内合法 materialize）。 |
| 修正测试 | **无**（合同阻断，不生成替代 receipt）。 |
| 通过条件 | 本轮目标未达成；经理需合同再冻结（例如批准 formal experiment fixture 源，或允许在 exact8 外提供已验证 formal receipt 字节）后方可继续。 |

### F6 静态证据（未执行 Python；源码逐字）

| 证据项 | 值 / 位置 |
| --- | --- |
| bundle 对象类型 | `VerifiedExperimentIdentity` — `tests/unit/test_m3_alignment.py` `_formal_nominals` L280–284 |
| `_experiment_boundary_inputs` 对应该类型的 stage | `"experiment-identity"` — `orchestration.py` L2044–2048 |
| 要求的 receipt 相对路径 | `receipts/experiment-identity/<experiment_key>.json` — `_receipt_external` + L2062–2067 |
| 要求的 experiment root | `…/runs/<experiment_key>/`（`_stage_root_for(..., container="runs")`） |
| legacy receipt 发布 stage | **`development-experiment-identity`** — `tests/unit/test_m3_label_artifact.py` L105–109 |
| legacy receipt scope | **`EXPERIMENT`** — 同处 L108 |
| legacy receipt scope_key | **`key`**（=`experiment_key`）— 同处 L109 |
| legacy receipt 路径 | `common/receipts/development-experiment-identity/{key}.json` — L99 |
| legacy verify API | `verify_development_example_experiment_identity` — L119 |
| 上游引用路径 | `test_m3_fold_plan_artifact.py` L153–157、L172 仍指向 `development-experiment-identity` |
| 结论 | stage **≠** formal `experiment-identity` → **禁止**把该 receipt bytes 复制到 `receipts/experiment-identity/` 冒充 formal；白名单内亦无权改 label/fold fixture 或 production |

引用边界：VALIDATION4 carrier PASS + **9 pass / 14 fail**；Ruff、mypy、cold、scope、VALIDATION5 **UNRUN**。

## 14. STATIC_REWORK9 / §18：public formal experiment publication fixture

| 字段 | 内容 |
| --- | --- |
| 现象 | §17 F6：legacy development-experiment-identity receipt 无法满足 `_experiment_boundary_inputs` 对 `VerifiedExperimentIdentity` 的 formal stage/path；白名单内禁止改名/手写/复制 receipt。 |
| 根因 | summary fixture 上游仍走 development example experiment 发布链；formal summary plan 需要真实 `experiment-identity` stage receipt 与 `runs/<key>/` 根。 |
| 规则 | §18：仅经公开链 `make_experiment_identity_run_plan` → `StageRunner.run_experiment_identity` → `make_experiment_identity_handler` → typed `verify_experiment_identity_output` / `verify_experiment_identity` 发布；只读复用 `test_m3_experiment_identity._fixture` 的 snapshot/provider/validation/config/spec；禁止 monkeypatch experiment verifier、手写/改名/copy receipt、cross-import 业务实现；`_stage_bundle` 在 canonical evaluations 前切换 formal experiment 并同步 key/scientific_config/work_key/manifest/metrics/spec/嵌套 upstream receipt/bytes/SHA；development receipt 不得进入 plan/context。 |
| 最小复现 | 公开链发布后：receipt stage=`experiment-identity`、scope=`EXPERIMENT`、path=`receipts/experiment-identity/<key>.json`、root=`runs/<key>/`；`make_summary_run_plan` 输入仅含 formal receipt；contexts 嵌套 `experiment_receipt_path` 同路径且无 `development-experiment-identity`。 |
| 修正测试 | 仅 `tests/unit/test_m3_summary_stage.py`：新增 `_publish_formal_experiment_identity` / `_bind_context_to_formal_experiment`；扩展 `_materialize_canonical_evaluation`（experiment_key + scientific_config_sha256）；重写 `_stage_bundle` 先验自证；h5/h10/fold/summary 语义保留。production / 另两 tests / 任务书 / review **未改**。 |
| 通过条件 | fixture 自证 formal object/receipt/path/SHA；`make_summary_run_plan` 产出 h5+h10；development receipt 不进入 plan/contexts；STATIC_ONLY 未跑验证命令；不得把 VALIDATION5/Ruff/mypy/cold 写成通过。 |

§17 F6 STOP 证据表（上节）完整保留，作为本轮对照；本轮以公开链闭合而非改名冒充。

## 15. VALIDATION5 STOP → STATIC_REWORK10 / §19：共享 worker monkeypatch 作用域隔离

| 字段 | 内容 |
| --- | --- |
| 现象 | VALIDATION5：BOM/Parser、argv sentinel、exact-worktree identity **PASS**；focused exact3 **9 passed / 14 failed**。14 项失败统一在 `_stage_bundle` → legacy feature fixture 构造（`M3_FEATURE_ARTIFACT_INVALID`），summary stage 测试体未进入。Ruff、mypy、cold、scope **UNRUN**。证据根 `artifacts/agent_runs/m3-r2s-validation5-20260826T051500/`；focused stdout SHA-256 `637a87dc544d47c280233a78b4f6a6eb511d80fc1db3232afbd652a22256b89e`；stage summary SHA-256 `62a6d5c6ca74d2badc7b108c12a96e533e9ea5ac5467a85d90434630bf5a3246`。 |
| 根因 | formal experiment 支持链经外层 `pytest.MonkeyPatch` 替换共享 `subprocess.run`（`provider_validation.subprocess.run` 即同模块）；随后 `test_m3_feature_artifact._build_feature_bundle` 在入口捕获该 fake 并 `setattr` 当作“真实 worker”恢复，导致正式 feature worker 边界失败。属 fixture 作用域泄漏，非 production。 |
| 规则 | §19：`_publish_formal_experiment_identity` 必须在独立嵌套 `pytest.MonkeyPatch.context()` 内跑 formal 支持链；进入前保存 `subprocess.run` exact callable；退出后断言 `subprocess.run is original` 再调用 `_SUMMARY._context`；内部仍用既有受控 fake；禁止只换顺序/延长 patch/手工恢复任意 callable/monkeypatch experiment verifier；退出后 formal artifact 须能被真实 typed verifier fresh 复验。 |
| 最小复现 | 外层 patch 泄漏 → feature 捕获 fake → `M3_FEATURE_ARTIFACT_INVALID`。嵌套 context 退出后 `subprocess.run is original` → feature 捕获真实 callable → legacy summary 支持可构造。 |
| 修正测试 | 仅 `tests/unit/test_m3_summary_stage.py`：`_publish_formal_experiment_identity` 改嵌套 MonkeyPatch；退出后 `verify_experiment_identity` fresh 复验；`_stage_bundle` 先验锁 internal fake / 退出恢复 / legacy feature 真实 callable / development receipt 隔离。production / 另两 tests / 任务书 / review **未改**。 |
| 通过条件 | 嵌套退出后 exact callable 恢复；legacy feature 使用真实 callable；formal receipt/context 同步保持；STATIC_ONLY 未跑验证命令；不得把 VALIDATION6/Ruff/mypy/cold 写成通过。 |

## 16. VALIDATION6 STOP → STATIC_REWORK11 / §20：runtime identity 与 worker authority 分域

| 字段 | 内容 |
| --- | --- |
| 现象 | VALIDATION6：Parser、argv sentinel、exact-worktree identity **PASS**；focused exact3 **9 passed / 14 failed**。REWORK10 已消除 legacy feature 侧 worker fake 泄漏；14 项失败统一在 formal publication 后、整体嵌套 context 退出后的真实 `verify_experiment_identity`，稳定 `LABEL_ARTIFACT_IDENTITY_MISMATCH`；legacy `_SUMMARY._context` 未进入。Ruff、mypy、cold、scope **UNRUN**。证据根 `artifacts/agent_runs/m3-r2s-validation6-20260826T025000/`；focused stdout SHA-256 `eb49c20321587aa4fcae3a07301ca52430c43b26f13efc09d6b139923e7f1d50`；stage summary SHA-256 `0a4ff280f6ccf83e593a0c8b6feb31ee999e60c2eb594dce91b6517e92cc19ca`。 |
| 根因 | §19“退出全部 formal fixture monkeypatch 后再 fresh verify”过强：experiment 测试支持在确定性 `build_provider_runtime_fingerprint` 替身下生成 formal provider/experiment；真实 typed verifier fresh 调用 provider verifier 并重算 runtime fingerprint。撤销该窄 identity 替身后拒绝，不表示 formal receipt 或 production 错误。 |
| 中央合同修正 / authority 分域 | §20 **supersede** §19 之“整体嵌套 MonkeyPatch.context 一次性撤销全部 patch”。测试 runtime identity 替身（`build_provider_runtime_fingerprint`）与 StageRunner `commit_directory_noreplace` 替身可留在外层 monkeypatch；worker 执行替身（共享 `subprocess.run`）必须在 formal publish 后立即精确恢复为进入前 exact callable，且 `subprocess`/`provider`/`provider_validation`/feature 观察同一真实 callable 后再进入 legacy `_SUMMARY._context`。 |
| 最小复现 | 嵌套 context 退出撤销 fingerprint → fresh verify `LABEL_ARTIFACT_IDENTITY_MISMATCH`。外层保留 fingerprint/commit + 仅恢复 worker → typed verify 闭合 → legacy feature 捕获真实 worker。 |
| 修正测试 | 仅 `tests/unit/test_m3_summary_stage.py`：去掉整体嵌套 context；外层 `_EXP._fixture`；publish 后 `_restore_shared_subprocess_run(original)`；worker 已恢复且 identity/commit 仍生效时 `verify_experiment_identity`；try/finally 保证失败也恢复 worker 且 cleanup 不掩盖主失败。production / 另两 tests / 任务书 / review **未改**。 |
| 通过条件 | worker 精确恢复；fingerprint/commit 替身可保留；fresh typed verify exact 对象/bytes/SHA 闭合；development receipt 隔离；STATIC_ONLY 未跑验证命令；不得把 VALIDATION7/Ruff/mypy/cold 写成通过。 |

## 17. VALIDATION7 STOP → STATIC_REWORK12 / §21：测试真实身份与 node 选择闭包

