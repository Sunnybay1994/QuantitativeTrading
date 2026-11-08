# M3-G8F-R2S Formal Summary Stage Publication Compatibility 独立初验报告

日期：2026-08-26<br>
身份：未参与本包实现与返工的全新独立静态初验 Agent（STATIC_ONLY）<br>
task id：`M3-G8F-R2S-FORMAL-SUMMARY-STAGE-PUBLICATION-COMPAT`<br>
exact base / HEAD：`57dcf2e579175ead8d7c833ed7fb4b7bccedc5c5`<br>
branch：`codex/m3-g8f-r2s-formal-summary-stage-publication-compat`<br>
worktree：`artifacts/dev_worktrees/m3-g8f-r2s-formal-summary-stage-publication-compat`<br>
唯一写入：本报告<br>
结论：**REVIEW_PASS**（§0–§7 历史 FAIL 保留；§8–§14 静态闭合）+ **EVIDENCE_REVIEW_PASS**（§15）+ **EOF_DOC_REVIEW_PASS**（§16）<br>
终态上限声明：仅确认任务/交付所称 `R2S_WINDOWS_ENGINEERING_VALIDATED` 之 VALIDATION8 工程证据闭合；**不**表示 R2A、bridge/CLI、actual worker、真实 Qlib、new root、retained、`FORMAL_SUMMARY_STAGE_PUBLICATION_COMPAT_VALIDATED` 或 M3 Gate 完成。

## 0. 审查边界

- 已阅读：根/`AGENTS.md`、任务书（含 §9–§12）、交付报告、exact8 实现与测试源码/diff。
- 只读 exact8 之 1–7；**唯一写入**本报告（路径 8）。
- **未运行**：Python / pytest / Ruff / mypy / cold / 真实 Qlib / 网络 / actual worker / new root / retained / stage / commit。
- dirty 与 exact8 一致：`evaluate.py`、`summary_stage.py`、三测试、任务书、交付；未见 orchestration/StageRunner/`__init__.py`/共享 SSOT 越界写入。
- 静态门禁抽查：`evaluate.py` `git diff --numstat` ≡ `-w --numstat` = `394 14`；`git diff --check` PASS；`ls-files --eol` = `i/mixed w/mixed`。

## 1. 合同逐项静态核对

| # | 合同点 | 静态结论 | 证据摘要 |
| --- | --- | --- | --- |
| 1 | legacy `horizon={n}` 签名/根规则/bytes 不变；stage 同经济输入 bytes 对齐 | 通过（实现+定向测） | legacy 仍强制 leaf；`test_legacy_summary_still_requires_horizon_leaf_and_stage_matches_bytes` 对齐 manifest/文件 bytes |
| 2 | 三阶段互斥 typed verifier + 唯一 module-private dispatcher（无 try-temp/catch-final） | 通过（实现+定向测） | `precommit`/`publication`/`artifact` 分函；`_make_summary_stage_closure_dispatcher` exact final→publication，否则 prove temp→precommit；unit 锁定无 fallback |
| 3 | handler 仅 build；temp→final 只经 `StageRunner.run_static` | 通过 | handler 只调 stage build + `StageBuildReport`；无 rename/copy/publish |
| 4 | PROJECT-only roots；plan 全闭包后唯一 canonical node；拒 GateExecution | 通过 | `_require_project_only_roots`；`select_run_plan_nodes` 全 ids 后再滤唯一 node；源码无 `GateExecution` |
| 5 | §12 preexisting-no-receipt：publication 采信 final，不转 temp；篡改 fail 且不发 receipt | 通过（测试面） | integration 锁定恢复序列与篡改 `["publication"]` only |
| 6 | temp leaf 与 exact `node_id` **前缀闭合** | **失败** | 见 §2 P1：`startswith(f".{node_id}.")` 在可点分 `model_version` 下接受更长 sibling node 的 leaf |
| 7 | 任务书 §6 强制 symlink/reparse 反例 | **失败** | exact8 测试中 **零** `symlink`/`reparse`/`junction` 命中；合同强制项未闭合 |
| 8 | 独立初验须新增 TOCTOU / Path alias / reparse 对抗例 | 本报告 §3 新增；实现者未覆盖 | 见反例 R1/R2 |

## 2. 发现分级

### [P1] temp leaf 用 `startswith(node_id)` 无法闭合 dotted sibling node — `src/quant/research/m3/evaluate.py`（`_require_stage_temp_output_root`）

`make_summary_run_plan` 允许 `model`/`model_version` 匹配 `^[a-z0-9._-]+$`（可含 `.`）。node_id 形如 `summary.h5.{model}.{model_version}`。

当短 identity 为 `summary.h5.lightgbm.v1`、长 sibling 为 `summary.h5.lightgbm.v1.2` 时，StageRunner 为长 node 创建的 leaf `.summary.h5.lightgbm.v1.2.<rand>` 对短 identity 满足：

`name.startswith(".summary.h5.lightgbm.v1.") == True`

因此 `build_research_summary_stage_artifact` / `verify_research_summary_stage_precommit` 会把**另一 node** 的 temp leaf 当作本 identity 合法 temp。任务书要求 leaf 与 exact `node_id` 前缀闭合；当前检查不是唯一可解析前缀。实现者仅测完全无关 prefix（`.summary.other.x`），未覆盖 sibling 前缀吞噬。

### [P1] 任务书强制的 symlink/reparse 反例缺失 — 测试面

任务书 §6 明确要求覆盖 symlink/reparse（与 arbitrary temp、wrong ancestry、wrong prefix、非空 temp 并列）。`tests/unit/test_m3_summary_stage.py` 与 integration **均无** symlink/junction/reparse 构造或断言。STATIC_ONLY 下测试即主证据，该强制反例未闭合。

### 无其他 P0

三阶段互斥、dispatcher 无 temp↔final fallback、legacy `horizon={n}`、PROJECT-only、GateExecution 拒绝、§12 preexisting-no-receipt 序列在静态阅读与既有测试面上可读且大体贴合合同。

## 3. 实现者未使用的对抗反例（新增）

### 反例 R1（temp node_id 前缀吞噬；实现者未覆盖）

**最小静态复现（未执行）：**

1. `stage_root/.stage-tmp` 下创建 leaf
   `.summary.h5.lightgbm.v1.2.forge`（模拟长 node `summary.h5.lightgbm.v1.2` 的 StageRunner temp）。
2. 构造短 identity：`node_id=summary.h5.lightgbm.v1`，`model_version=v1`，其余字段自洽。
3. 调用 `build_research_summary_stage_artifact` / `verify_research_summary_stage_precommit`，`output_root`/`root` 指向该 leaf（内容可为合法 summary 四文件或空目录按 API）。
4. **现状（源码）：** `startswith(".{summary.h5.lightgbm.v1}.")` 为真 → 通过 temp ancestry 门禁。
5. **合同预期：** 拒绝（leaf 不属于短 `node_id`；仅允许 `.{exact_node_id}.{suffix}` 且 `exact_node_id` 不可被更长 sibling 吞噬）。

**通过条件：** 新增定向测试断言短 identity 拒绝长 sibling leaf；实现改为唯一可解析绑定（例如拆出 suffix 后要求 `name == f".{node_id}.{suffix}"` 且 `node_id` 全匹配，或禁止/规范化使 plan 内 node_id 互不为前缀，并在 verifier 侧强制同一规则）。

### 反例 R2（final→temp junction / reparse TOCTOU；实现者未覆盖）

**最小静态复现（未执行；优先挑战 precommit temp identity ↔ final root）：**

1. 在合法 `.stage-tmp/.{node_id}.x` 写入与科学输入一致的 summary 四文件。
2. 在 `stage_root / final_relative_path` 创建 **directory junction/reparse**，目标指向该 temp leaf（或相反：temp leaf 为指向 final 的 reparse）。
3. 分别调用：
   - `_make_summary_stage_closure_dispatcher(...)(junction_or_alias_root)`
   - `verify_research_summary_stage_precommit` / `verify_research_summary_stage_publication`
4. **合同预期：** 任一 phase 均 fail closed；不得因 `resolve()` 后物理路径重合而把 temp 当成 publication，或把 final alias 当成 precommit；不得跨 phase 重解释。
5. 静态阅读：publication 路径上 `_is_stage_tmp_descendant` / `_require_real_absolute_path` 的 reparse 检查**可能**挡住部分情形，但 **无测试锁定**；且 R1 的 prefix 洞与 alias 组合时证据不足。

**通过条件：** Windows/支持平台上至少一条 junction/reparse 定向测试证明：dispatcher 与三 verifier 均拒绝，且 `calls` 不出现跨 phase fallback。

## 4. 失败项（现象—根因—规则—最小复现—通过条件）

### F1 — temp `node_id` 前缀闭合不严

| 字段 | 内容 |
| --- | --- |
| 现象 | 短 `node_id` 的 stage build/precommit 接受长 sibling temp leaf |
| 根因 | `_require_stage_temp_output_root` 仅用 `startswith(f".{node_id}.")` |
| 规则 | 任务书 §4/§6：leaf 与 exact `node_id` 前缀闭合；wrong node prefix 拒绝 |
| 最小复现 | 反例 R1 |
| 新增测试 | sibling dotted `model_version` 前缀吞噬 |
| 通过条件 | 短 identity 稳定拒绝长 leaf；plan 内互为前缀的 node 亦不能误绑 |

### F2 — symlink/reparse / TOCTOU 强制反例缺失

| 字段 | 内容 |
| --- | --- |
| 现象 | exact8 测试无 symlink/reparse/junction；无 temp↔final alias TOCTOU 锁定 |
| 根因 | 实现者反例集未覆盖任务书 §6 与初验优先项 |
| 规则 | 任务书 §6；独立初验须新增 TOCTOU/alias/reparse 对抗例 |
| 最小复现 | 反例 R2 |
| 新增测试 | junction/reparse 双向 alias + dispatcher phase 序列断言 |
| 通过条件 | 别名/reparse 一律 fail closed，无 phase 重解释 |

## 5. 未运行边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold | **未运行** |
| 真实 Qlib / 网络 / actual worker / new root / retained | **未运行** |
| commit / 改实现·测试·任务·交付 | **未做**（仅写本报告） |

## 6. 总判

**REVIEW_FAIL**

三阶段互斥、dispatcher 无 fallback、legacy `horizon={n}`、StageRunner wiring、§12 preexisting-no-receipt 等主路径静态可读且大体贴合合同；但 **temp `node_id` 前缀闭合存在可演示的 sibling 吞噬缺陷**，且任务书强制的 **symlink/reparse 反例未落地**。须在 exact8 内最小返工并经全新独立初验复验后，方可申请 Windows 定向验证资源与 `FORMAL_SUMMARY_STAGE_PUBLICATION_COMPAT_VALIDATED` 相关推进。

返工不得扩大为 orchestration/StageRunner 修改、R2A/bridge/actual worker，或宣称 Gate 完成。

---

## 7. STATIC_REWORK4 复验（任务书 §13 · 2026-08-26）

### 7.0 复验边界

- 对照任务书 §13、交付 §9、首轮 F1/F2；只读 production/测试/任务/交付；唯一写本报告。
- **未运行** Python / pytest / Ruff / mypy / cold / Qlib / network / commit。
- 门禁抽查：`evaluate.py` `numstat`≡`-w`=`412 14`；`git diff --check` PASS；`eol`=`i/mixed w/mixed`；dirty 仍 exact8（含本报告）。

### 7.1 首轮 FAIL 闭合核对

| 首轮项 | 复验结论 | 证据 |
| --- | --- | --- |
| F1 temp `startswith` sibling 吞噬 | **已闭合** | `_require_stage_temp_leaf_name`：exact `.{node_id}.` + 非空后缀；后缀禁 `.`/`/`/`\` 且 ⊆ `tempfile` 字符集 `[a-z0-9_]`；非仅加长 startswith。`test_temp_leaf_exact_ownership_rejects_longer_sibling_and_bad_suffix` 锁定 `v1` vs `.…v1.2.…` |
| F2 symlink/reparse 测试缺失 | **部分闭合 / 新 FAIL** | 属性注入覆盖 build/precommit/publication/artifact/dispatcher；host symlink 分支亦写。但 dispatcher **先 resolve 再 lstat/转发**，相对 typed verifier 的 abspath≠resolve 门禁被削弱（见 §7.2） |
| 其余原合同（三阶段互斥、legacy、§12、PROJECT-only、GateExecution） | **未见漂移** | 相关函数与既有测试仍在；本轮仅增 leaf helper + 两测试 |

### 7.2 本轮发现

### [P1] dispatcher 先 `resolve` 再检查，削弱 final symlink/junction 拒绝 — `summary_stage.py`（`_make_summary_stage_closure_dispatcher`）

typed verifier 经 `_require_real_absolute_path`：对**调用方传入的路径**做 `abspath` vs `resolve` 不等或 `lstat` 链/reparse → 拒绝。dispatcher 却：

1. `absolute = Path(os.path.abspath(root)).resolve(strict=True)`（先跟随 junction/symlink）；
2. `os.lstat(absolute)` 只检查**解析后目标**；
3. 将已解析 `absolute` 传给 `verify_research_summary_stage_publication` / `precommit`。

因此当 `stage_root/final_relative_path` 为指向外部合法 summary 树的 directory junction/symlink 时：直接 `verify_research_summary_stage_publication(root=junction_path)` 应拒绝；同一路径经 dispatcher 可变成对目标目录的 publication 并可能通过。`is_final` 分支同样对 `resolve(candidate_final)` 后目标做 lstat，**不**对 junction 叶本身做非跟随检查。这违反 §13「dispatcher … fail closed … 无 … guard 弱化」。实现者 symlink 测试期望 `dispatcher(final_root)` raise，与上述控制流不一致（STATIC_ONLY 未执行，属假绿风险）。

属性注入测只证明「解析后路径被标 reparse 时失败」，**不能**证明真实 junction 叶在 dispatcher 入口被拒绝。

### 7.3 实现者未使用的新对抗反例（R3）

**dispatcher × final junction × resolve-before-lstat（实现者未覆盖）**

1. 在 `link_target` 写入与 identity 科学输入一致的四文件；删除真实 final（若有）。
2. 在 `stage_root/final_relative_path` 创建 directory symlink/junction → `link_target`。
3. 调用 `verify_research_summary_stage_publication(..., root=final_junction_path)` → 预期 `M3_RESEARCH_SUMMARY_ARTIFACT_INVALID`（abspath≠resolve / leaf reparse）。
4. 调用同一 kwargs 下 `dispatcher(final_junction_path)` → **合同预期**同样 fail closed，且不得进入成功 publication；**不得**因 resolve 后目标“看起来像 final”而通过。
5. 额外锁定：dispatcher 失败时 phase `calls` 不含成功的 `publication`（或 publication 入口收到的 `root` 仍为未跟随的 junction 路径并失败）。

**通过条件：** dispatcher 在 resolve 之前对**入参 path**（及 `candidate_final` 叶）做与 `_require_real_absolute_path` 同强度的 symlink/reparse 拒绝；或拒绝把已 resolve 路径当作 publication 根除非入参叶本身已通过非跟随检查。定向测试在 host 可建 junction 时断言步骤 3–4 均拒绝；属性注入不得替代本例。

### 7.4 失败项

| 字段 | 内容 |
| --- | --- |
| 现象 | final 为 junction/symlink 时，typed publication 拒、dispatcher 可能放行 |
| 根因 | dispatcher resolve-before-lstat，并向 verifier 转发已解析目标 |
| 规则 | 任务书 §13：build/三 verifier/dispatcher 均 fail closed，无 guard 弱化 |
| 最小复现 | 反例 R3 |
| 通过条件 | dispatcher 与 verifier 对 junction 叶同等拒绝；测试锁定 calls/异常，非仅注入 |

### 7.5 未运行边界

Python / pytest / Ruff / mypy / cold / Qlib / network / commit / 改实现·测试·任务·交付：**未做**（仅更新本报告）。

### 7.6 复验总判

**REVIEW_FAIL**

§13 要求的 temp exact ownership（F1）与 reparse **属性注入**面已补；但 **dispatcher 对真实 symlink/junction 的 guard 相对 typed verifier 被削弱**，且实现者未覆盖 resolve-before-check 对抗例。不得将首轮 FAIL 或本轮部分闭合继承为 PASS。须最小修复 dispatcher 路径身份检查并经再一轮独立复验。

---

## 8. STATIC_REWORK5 复验（任务书 §14 · R3 P1 · 2026-08-26）

### 8.0 复验边界

- 对照任务书 §14、交付 §10、§7 R3 P1；production/tests/taskbook/delivery **只读**；唯一写本报告。
- **未运行** Python / pytest / Ruff / mypy / cold / Qlib / network / commit。
- dirty：exact8；`evaluate.py` `numstat`≡`-w`=`412 14`；`git diff --check` PASS；`eol`=`i/mixed w/mixed`。本轮生产改动面为 `summary_stage` dispatcher（交付声称未放宽 evaluate 三 verifier）。

### 8.1 §14 / R3 闭合核对

| 要求 | 结论 | 证据 |
| --- | --- | --- |
| 原始 root：exact native concrete absolute `Path` | **通过** | `type(root) is type(Path())` 且 `root.is_absolute()` |
| 仅词法 `raw_absolute=Path(os.path.abspath(root))`；phase 前无 resolve | **通过** | dispatcher 内无对 caller root / candidate final 的 `resolve`；注释与控制流一致 |
| raw 上非跟随 `lstat` 拒 symlink/reparse/非目录 | **通过** | `S_ISLNK` / `FILE_ATTRIBUTE_REPARSE_POINT` / `not S_ISDIR` → `ValueError`；`OSError` fail closed |
| phase 仅 `normcase(raw)` vs `normcase(candidate_final_lexical)` | **通过** | `candidate_final=abspath(stage_root).joinpath(*parts)`；相等才 `is_final` |
| typed verifier 只收 `raw_absolute`；无 resolved 替代 | **通过** | publication/precommit 均 `root=raw_absolute` |
| 无 phase fallback / mode 注入 | **通过** | 无 catch-后改 phase；失败原样抛出 |
| final leaf junction/symlink：成功 publication 前拒绝 | **通过** | 入口 lstat 拒链；即便进入 publication，typed `_require_real_absolute_path` 仍 `abspath≠resolve`/reparse 拒 |
| R3 测试：direct+dispatcher 拒；无成功 phase；lexical/`..`/shadow | **通过（测试面）** | `test_dispatcher_r3_final_junction_and_lexical_alias_reject` |
| evaluate 三阶段 / legacy / EOL / exact8 未漂移 | **通过** | `_require_real_absolute_path` 仍在；leaf ownership helper 仍在；`412 14` 与 REWORK4 终态一致；无 orchestration 越界 |

### 8.2 本轮发现

**No findings.** R3 P1 已由 lexical dispatcher 闭合；未见新的 P0/P1。

### 8.3 新增静态对抗（R4，实现者未用）

**中间路径组件 reparse/symlink × lexical final 命中（实现者未覆盖）**

1. `stage_root` 下将 `summaries`（或 `final_relative_path` 的某一非叶祖先）做成 directory junction/symlink，指向外部树；在外部树对应位置创建**真实目录叶**并写入合法 summary 四文件。
2. 令 `root` 的词法路径等于 `identity` 的 candidate final（经 `abspath`/`normcase` 可命中 `is_final`），且叶本身 `lstat` 非 symlink（仅祖先为链）。
3. 调用 dispatcher(root) 与 `verify_research_summary_stage_publication(root=raw)`。
4. **合同预期：** 不得成功 publication。dispatcher 若因叶非链而进入 publication phase，typed verifier 须因祖先跟随导致 `abspath≠resolve`（或等价）fail closed；`successes` 为空；转发 root 仍为 raw lexical，无 resolve 替代、无 pre fallback。
5. **通过条件（静态预期，本轮未执行）：** 定向测试锁定 phase calls 与异常；本对抗用于回归祖先链 TOCTOU，不替代 R3 叶 junction 例。

### 8.4 未运行边界

Python / pytest / Ruff / mypy / cold / Qlib / network / commit / 改实现·测试·任务·交付：**未做**（仅更新本报告）。

### 8.5 复验总判

**REVIEW_PASS**

§14 lexical-raw dispatcher 消除 resolve-before-check；R3 host junction/symlink + lexical/`..`/shadow 反例已落地；F1 temp ownership、三阶段互斥、legacy `horizon={n}`、EOL/exact8 静态未见回退。本 PASS 仅关闭 formal summary StageRunner-shaped publication compatibility 的**静态初验**；不授权跳过经理 Windows 定向验证，也不表示 R2A/Gate 完成。

---

## 9. STATIC_REWORK6 / F4 复验（任务书 §15 · VALIDATION2 · 2026-08-26）

### 9.0 复验边界

- 对照任务书 §15、交付 §11、VALIDATION2 边界（carrier 三重 PASS；focused **9 passed / 14 failed** 于 `_stage_bundle` fixture，非 production）。
- 本轮只读：production（`evaluate.py` / `summary_stage.py`）、其他 tests、taskbook、delivery；**唯一写**本报告。
- **未运行** Python / pytest / Ruff / mypy / cold / Qlib / network / commit。

### 9.1 F4 范围与 production 冻结

| 检查 | 结论 | 证据 |
| --- | --- | --- |
| 本轮变更面 | **通过** | 交付声称仅 `tests/unit/test_m3_summary_stage.py` + delivery；mtime：unit≈01:19、delivery≈01:19；`evaluate.py`≈00:45、`summary_stage.py`≈00:56、integration≈00:31、formal unit≈00:02（均早于 F4） |
| production 字节未因 F4 改变 | **通过** | 上述 mtime；当前 SHA256：`evaluate.py`=`8546D81495EB24359920B7BE6593C4CC61839964AD416E6E875BBD04F23388F5`；`summary_stage.py`=`A45CDE5146D806CECDA01D51D060B1BF13E3C940E3FDBF1A3C501CD06269BCBC` |
| 无 contracts/`Any`/schema 绕过 | **通过** | F4 块无新增 `type: ignore`；文件内唯一 `type: ignore[call-arg]` 在既有 GateExecution 反例（L884），非 fixture |

### 9.2 分层字段归属

| 要求 | 结论 | 证据 |
| --- | --- | --- |
| SSOT：`evaluation_receipt_sha256` ∉ `EvaluationManifestV1`；∈ `VerifiedEvaluationArtifact` | **通过** | `contracts.py` L2140–2189 |
| inner `replace(item.manifest, …)` 仅 `horizon_sessions=10` + `work_key=compute_work_key(..., horizon=10)` | **通过** | `_stage_bundle` L111–119 |
| outer `replace(item, …)` 持 `root` / 更新后 `manifest` / `evaluation_receipt_sha256=receipt_sha` | **通过** | L108–121 |
| receipt file 写入 + SHA 闭包 | **通过** | L97–106；`receipt_sha=_sha(receipt)` 进入 outer |
| h10 context / upstream / fold·model 闭包保持 | **通过** | context specs `horizon_sessions=10`；upstream 拼接 h10 receipts；model/version 自 h5 继承；fold 经原 item |

### 9.3 本轮发现

**No findings.** F4 为测试 fixture 字段归属修正；与 VALIDATION2「14 红在 fixture、非 production」叙述一致。

### 9.4 新增静态对抗（R5，实现者未用）

**inner 再次混入 `evaluation_receipt_sha256` 必须在 fixture 构造期失败（回归锁）**

1. 在临时拷贝的 `_stage_bundle` 等价构造中，故意把 `evaluation_receipt_sha256=receipt_sha` 放回 `replace(item.manifest, …)`。
2. **预期：** 在进入任一 summary stage 测试体之前，因 `EvaluationManifestV1` 无该字段而 `TypeError`（或等价构造失败）；不得被 `Any`/`type: ignore` 吞掉。
3. 对照：合法分层构造（现行代码）可完成 bundle，且 `h10[i].evaluation_receipt_sha256 == _sha(h10_receipts[i])`、`h10[i].manifest.horizon_sessions == 10`、`work_key` 与 `horizon=10` 一致。
4. **通过条件：** 定向单测或静态审查锁定「非法 keyword 仅能出现在 outer」；本对抗防止 F4 回潮。未执行。

### 9.5 未运行边界

Python / pytest / Ruff / mypy / cold / Qlib / network / commit / VALIDATION3：**未做**。不得把 VALIDATION2 的 9 绿计为全量通过。

### 9.6 复验总判

**REVIEW_PASS**

F4 h10 fixture 字段归属符合 §15；production/`evaluate`/`summary_stage` 本轮未改；outer receipt identity 仍由 summary fixture 消费。历史 §0–§7 FAIL 与 §8 PASS 原文保留。复验 PASS 后可由经理申请完整 VALIDATION3；本判不替代 VALIDATION3。

---

## 10. STATIC_REWORK7 / F5 复验（任务书 §16 · VALIDATION3 · 2026-08-26）

### 10.0 复验边界

- 对照任务书 §16、交付 §12、VALIDATION3（carrier PASS；focused **18 passed / 5 failed** 于 public plan/input；Ruff/mypy/cold/scope/VALIDATION4 **UNRUN**）。
- 只读 production/tests/taskbook/delivery；**唯一写**本报告。
- **未运行** Python / pytest / Ruff / mypy / cold / network / commit。

### 10.1 本轮冻结与范围

| 检查 | 结论 | 证据 |
| --- | --- | --- |
| 变更面 | **通过** | 仅 `tests/unit/test_m3_summary_stage.py` + delivery（mtime≈01:4x）；formal unit / integration 早于本轮 |
| production 未改 | **通过** | `evaluate.py` SHA256=`8546D81495EB24359920B7BE6593C4CC61839964AD416E6E875BBD04F23388F5`；`summary_stage.py`=`A45CDE5146D806CECDA01D51D060B1BF13E3C940E3FDBF1A3C501CD06269BCBC`（与 §9 F4 冻结相同） |
| 未借机改 `VerifiedG1Release` repr | **通过** | 本文件无 `VerifiedG1Release` 引用；无 contracts/orchestration 改动 |
| 未弱化 public builder | **通过** | 仍调用真实 `make_summary_run_plan`；无 monkeypatch 其 identity/path 规则 |

### 10.2 §16 合同逐项

| 要求 | 结论 | 证据 |
| --- | --- | --- |
| 每 fold+horizon `compute_work_key` 同步 manifest/metrics/`evaluation_spec` | **通过** | `_materialize_canonical_evaluation`；自证 L218–230 |
| h10 label/prediction horizon 同步 | **通过** | horizon 变化时 `replace` label/prediction specs（L141–147） |
| canonical `work/<key>/evaluation` + `receipts/evaluation/<key>.json`；逐项构造；physical distinct | **通过** | L95–125；`set(roots)`/`set(receipts)` 断言；无 glob/latest |
| 字段变更后 `_canonical_bytes(asdict)` 重写 + outer SHA 来自实际 bytes | **通过** | metrics/manifest 写盘后 `manifest_sha`/`receipt_sha=_sha(...)`；自证 bytes≡canonical 与 SHA |
| upstream / `by_root` 与 evaluations 顺序一致 | **通过** | `h5+h10` 元组拼接；`by_root` 覆盖全部 canonical roots |
| fixture 自证 + plan 产出 exact h5/h10 nodes | **通过** | L251–261：`summary.h5.*` 与 `summary.h10.*` |
| 科学内容/dispatcher/R3/三 verifier 不因本轮削弱 | **通过（范围面）** | 仅 fixture helper；既有 R3/ownership/phase 测试仍在同文件 |

与 public builder 对齐：`_stage_root_containing(..., container="work")` + `_receipt_external(..., key=work_key)` 期望的 publication tree 与 fixture 路径同构。

### 10.3 本轮发现

**No findings.**

### 10.4 新增静态对抗（R6，实现者未用）

**h10 漏同步 `label_spec`/`prediction_spec.horizon_sessions` 必须 fail closed**

1. 在合法 `_stage_bundle` 之后，对某一 h10 context 仅保留 `evaluation_spec.horizon_sessions=10`，故意把 `label_spec`/`prediction_spec.horizon_sessions` 改回 `5`（work_key/path 仍 canonical）。
2. 调用 `run_formal_summary_stage(..., evaluations=..., evaluation_contexts=..., horizon_sessions=10)` 或 stage build/precommit。
3. **预期：** fail closed（fresh 上下文 horizon 闭包漂移），不得静默产出 summary；phase 不得成功 publish。
4. **对照：** 现行 `_materialize_canonical_evaluation` 在 horizon 变化时同步 label/prediction；但 fixture 自证环**未**断言这两项 horizon——本对抗补实现者未锁证据。
5. 未执行。

### 10.5 未运行边界

Python / pytest / Ruff / mypy / cold / network / commit / VALIDATION4：**未做**。不得把 VALIDATION3 的 18 绿计为 F5 运行态通过。

### 10.6 复验总判

**REVIEW_PASS**

F5 canonical work_key/path/bytes/plan fixture 符合 §16；production 与另两 tests 相对本轮冻结；未处理无关 `VerifiedG1Release` repr。历史轮次原文保留。经理可申请完整 VALIDATION4；本判不替代 VALIDATION4。

---

## 11. STATIC_REWORK9 复验（任务书 §18 · F6 STOP 后 · 2026-08-26）

### 11.0 复验边界与历史 STOP

- 已读：`AGENTS.md`、任务书 §17–§18、交付 §13–§15、exact8 现行 `tests/unit/test_m3_summary_stage.py`。
- 只读 production/tests/task/delivery；**唯一写**本报告。
- **未运行** Python / pytest / Ruff / mypy / cold / network / commit / stage。
- **历史 STOP 保留：** §17 / 交付 §13 F6 — legacy `development-experiment-identity` receipt 不得改名/手写冒充 formal；白名单内曾无法合法 materialize → `CONTRACT_STOP`。本轮以公开链闭合，**不**撤销该 STOP 证据。

### 11.1 本轮冻结

| 检查 | 结论 | 证据 |
| --- | --- | --- |
| 变更面 | **通过** | 仅 unit `test_m3_summary_stage.py`（mtime≈02:13）+ delivery（≈02:14）；formal/integration 早于本轮 |
| production 未改 | **通过** | `evaluate.py`=`8546D81495EB24359920B7BE6593C4CC61839964AD416E6E875BBD04F23388F5`；`summary_stage.py`=`A45CDE5146D806CECDA01D51D060B1BF13E3C940E3FDBF1A3C501CD06269BCBC`（与 §9/§10 冻结相同） |
| 无手写 `VerifiedExperimentIdentity(` | **通过** | 文件内无该构造；仅 `published.verified` |

### 11.2 §18 公开链与 receipt 闭包

