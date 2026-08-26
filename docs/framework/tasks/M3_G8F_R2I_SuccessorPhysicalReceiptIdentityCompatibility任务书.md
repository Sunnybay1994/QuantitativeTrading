# M3-G8F-R2I Successor Physical Receipt Identity Compatibility 任务书

状态：`R2I_WINDOWS_ENGINEERING_VALIDATED`（Windows 工程验证组合闭合；**不**表示 R2W、R2B、actual worker、真实 Qlib、new root、retained 或 M3 Gate 完成）<br>
task id：`M3-G8F-R2I-SUCCESSOR-PHYSICAL-RECEIPT-IDENTITY-COMPAT`<br>
exact base：`eca54af513078ca6d000feb544329cba69797948`<br>
branch：`codex/m3-g8f-r2i-successor-physical-receipt-identity-compat`<br>
worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2i-successor-physical-receipt-identity-compat`

## 1. 目标与根因

R2W 静态审计证明 successor 当前错误地把三类不同身份混成同一个 `scope_key`：successor 聚合 Gate identity、receipt 槽位所有权、真实 public stage 的 physical receipt scope。真实 reproducibility/readiness/acceptance stage 因此无法接入，而不应通过修改这些既有 stage 的权威发布身份来迁就 successor。

本包只修正 successor runtime 的 physical receipt identity/root alias compatibility。终态上限为 `R2I_WINDOWS_ENGINEERING_VALIDATED`；不实现 downstream callable、bridge/CLI、actual worker、真实 Qlib、network、new root、retained 或 M3 Gate。

## 2. 唯一写白名单（exact6）

1. `src/quant/research/m3/successor_runtime.py`
2. `tests/unit/test_m3_successor_runtime.py`
3. `tests/integration/test_m3_successor_runtime.py`
4. `docs/framework/tasks/M3_G8F_R2I_SuccessorPhysicalReceiptIdentityCompatibility任务书.md`（经理独占）
5. `docs/framework/deliveries/M3_G8F_R2I_SuccessorPhysicalReceiptIdentityCompatibility交付报告.md`（实现者独占）
6. `docs/framework/reviews/M3_G8F_R2I_SuccessorPhysicalReceiptIdentityCompatibility独立初验报告.md`（独立 reviewer 独占）

实现者只写1–3、5，不写4、6。reviewer只写6，其余只读。禁止修改 readiness、reproducibility、acceptance、quality、orchestration、R2A/R2S、config、`__init__.py`、roadmap、共享 SSOT 或任何其他路径。

## 3. 权威身份语义

- `GateExecution.identity` 继续作为 successor 聚合身份，绑定两fold、全部 prior Gates 与 Gate 顺序。
- `StageReceiptRef.scope_key` 必须逐字等于真实 public `StageReceipt.scope_key`；不得再写入 successor join hash。
- receipt 槽位所有权由 `gate + fold + horizon + node_id` 及既有 stage/scope 闭合，不借用 physical `scope_key` 表达。
- 删除或停止导出误导性的 `compute_successor_gate_scope_key`；不得保留新旧两个含义并存的兼容分支或隐式 fallback。

## 4. 各 Gate physical receipt 合同

- summary：exact 2份，按 horizon；physical key保持真实 `experiment_key`。
- reproducibility：exact 4份，按 fold×horizon；physical key为真实 `comparison_key`，四者必须唯一。
- readiness：exact 2份，按 fold；未来R2W分别以该fold的config/release运行public stage，得到两个不同 `readiness_key` 和物理receipt。StageReceipt本身仍无fold；不得复制path/bytes或改写scope。
- acceptance：exact 1份；physical key为真实 `acceptance_key`，明确允许不同于 `GateExecution.identity`。

`_validate_gate_execution` 只验证精确槽位集合、stage/scope、physical key形状与必要唯一性，不得把physical key与aggregate join比较。

## 5. Root alias 与 canonical G8

- acceptance之外的 successor receipt inputs/outputs继续exact `PROJECT`。
- acceptance receipt inputs/outputs必须exact `G8`。
- `G8`只能由两个冻结fold config共同解析出的同一个 `project_stage_root` 产生；禁止caller传入任意root。
- 两config的 `project_stage_root` 必须一致，并与 `controlled_output_root` 逐字解析相等；否则必须在任何stage运行、controlled root创建或worker启动前 `SUCCESSOR_INPUT_INVALID`。
- terminal/receipt fresh verification按stage选择唯一root map：acceptance为 `{"G8": canonical_stage_root}`；其他为 `{"PROJECT": project_root}`。
- 禁止混合alias、额外alias、G8路径漂移、任意root注入或把G8字符串复制为第二SSOT。

## 6. Verification 与 terminal 不变量

- `_verify_receipts`及controlled-tree复验必须使用§5 canonical root map，并继续要求ref与真实receipt的stage/scope/scope_key/path/SHA完全一致。
- `_unique_refs`保持严格单射；不得新增shared-receipt例外。不同semantic owner不得复用同path、同bytes或同physical ref。
- terminal attestation继续同时绑定Gate aggregate identity和全部physical receipt refs；terminal schema/output集合不得改变。
- 错误保持现有 successor fail-closed稳定域，不泄露绝对路径、config或artifact内容。

## 7. 必须覆盖的反例

至少覆盖：

1. 把旧 successor join hash伪装为comparison/readiness/acceptance physical key。
2. 同一readiness path/bytes复制给两个fold；两fold readiness key碰撞；fold所有权错配或缺一fold。
3. acceptance key被替换为Gate identity；真实physical key与aggregate identity不同的正向保持。
4. acceptance receipt混入PROJECT、非acceptance receipt混入G8、额外/mixed alias。
5. 两config解析出不同G8 root；controlled output root与canonical G8不一致；caller尝试注入任意root。
6. physical receipt stage/scope/scope_key/path/SHA漂移；不同node复用同path、bytes或semantic owner。
7. summary/repro/readiness/acceptance槽位缺失、多余、重复、乱序及fold/horizon错配。
8. terminal attestation仍同时绑定aggregate Gate identity与physical refs，任一漂移均fail closed。

## 8. STATIC_ONLY、review 与 STOP

实现者先读 `AGENTS.md`、本任务书、R2W STOP delivery及 exact6 源码；只做最小identity/root compatibility修改与测试，delivery逐项记录“现象—根因—规则—最小复现—新增测试—通过条件”。零Python、pytest、Ruff、mypy、cold、actual worker、Qlib、network、new root、retained、stage/commit。

完成后回 `DELIVERY_READY`。另一全新外部 reviewer 只写唯一review报告，必须增加实现者未使用的对抗反例，重点挑战physical/aggregate身份分离、readiness双fold单射与G8 root authority。`REVIEW_PASS`后才可另申请Windows验证。

若 exact6 不足、需要改public stage/config/schema、无法从现有config唯一得到G8、或必须放宽 `_unique_refs` / root identity，立即在delivery精确STOP，不得自行扩围。

静态退出要求 actual dirty仅属exact6、cached=0、普通 `git diff --check` PASS，无临时文件、真实产物或凭据。R2W/R2B继续冻结，直至本包合流并从latest integration重建。

## 9. STATIC_REWORK1：独立初验缺失反例闭包

独立初验结论为 `REVIEW_FAIL`：生产侧 physical/aggregate 分离与 canonical G8 静态实现大体符合合同，但 §7 的三类强制对抗证据尚未闭合。本轮复用原实现会话，仅在既有 exact6 内做最小测试/交付返工；不得创建第二实现者，不扩生产路径，不运行 Python。

### F1 — mixed/extra alias

- 现象：已有测试只覆盖整单错 alias，未锁定同一 receipt outputs/inputs 内混合 `PROJECT`/`G8`，也未锁定 root map 额外 alias。
- 规则：每个 stage 只能使用 §5 指定的唯一 exact root map；mixed 或 extra alias 必须在 fresh receipt closure 中稳定 fail closed。
- 最小复现：构造 acceptance receipt 的 inputs 或 outputs 一部分为 `G8`、一部分为 `PROJECT`；另构造验证 root map 含未消费的第二 alias。
- 新增测试：至少覆盖 acceptance mixed alias；若现有公共入口可表达 extra root map，则补其拒绝节点。测试不得通过其它 scope/path 漂移提前失败。
- 通过条件：稳定拒绝且失败确由 alias/root-map 闭包触发。

### F2 — readiness 双 fold 单所有权

- 现象：已有碰撞测试未覆盖两份不同 physical key 却同标一个 fold、未知 fold 或缺一 fold。
- 规则：readiness exact 两份 receipt 必须分别且仅分别归属冻结的两个 fold；不同 key 不能掩盖 fold 所有权错配。
- 最小复现：两 ref 均 `fold_001`；或一份为未知 `fold_003`；或只提供一份 readiness ref。
- 新增测试：至少锁定同折与缺折，必要时补未知折；稳定 `SUCCESSOR_GATE_FAILED`。
- 通过条件：fold 集合、数量与单所有权均逐字闭合，不能依赖 scope-key 碰撞才拒绝。

### F3 — readiness 同 bytes 异 path 单射

- 现象：现有 shared-path 测试先因 receipt scope 漂移失败，未真正证明 `_unique_refs` 对自洽 ref/receipt 的同字节异路径别名拒绝。
- 规则：两个 fold 的 receipt 即使各自 stage/scope/scope_key/path/SHA 全部自洽，也不得复用相同 receipt bytes/SHA；physical ownership 保持严格单射。
- 最小复现：为两个 fold 发布不同路径、不同 readiness key、各自自洽的 receipt，但令 canonical receipt bytes/SHA 相同；其余 identity 均合法。
- 新增测试：锁定 terminal/ownership closure 因 bytes 单射冲突拒绝，不能靠 scope/path/key 漂移提前失败。
- 通过条件：稳定 `SUCCESSOR_TERMINAL_INVALID`（或源码既有 terminal ownership 稳定码），terminal 不发布。

实现者须在delivery按“现象—根因—规则—最小复现—新增测试—通过条件”记录 F1–F3，并保持 production 字节不变，除非新增测试证明现有实现确有同合同直接冲突；若需改production，先STOP举证。返工交付后由原独立reviewer复验并只更新唯一review报告；初验通过前不得申请Windows验证或解冻R2W。

## 10. STATIC_REWORK2：VALIDATION1 fixture mkdir 修正

VALIDATION1 的 identity PASS；unit 为 `29 passed / 1 failed`。唯一失败发生在 `test_global_ownership_rejects_readiness_same_bytes_different_paths`：两个目标文件共享 `readiness-evidence` 父目录，fixture 先创建 `first_path.parent`，随后对相同的 `second_path.parent` 再次执行默认 `exist_ok=False` 的 `mkdir(parents=True)`，触发 `FileExistsError`，尚未进入 production ownership 断言。integration、Ruff、mypy、cold、scope均未运行。

授权原实现者 STATIC_ONLY 仅修改 `tests/unit/test_m3_successor_runtime.py` 与交付报告：把该共享父目录创建收敛为一次，或让第二次创建显式 `exist_ok=True`；必须保持两条不同 receipt path、相同 payload/SHA、不同fold/key与后续 `_validate_global_receipt_ownership` 断言完全不变。禁止修改production、其他测试、review报告，禁止Python/自动重跑。delivery按“现象—根因—规则—最小复现—修正—通过条件”记录本轮，并引用VALIDATION1 evidence root。完成后由原独立reviewer只读复验；PASS后另申请新的完整验证，不能把本轮29绿冒充整包通过。

## 11. Windows 工程验证组合证据（终态索引）

本包终态仅为 `R2I_WINDOWS_ENGINEERING_VALIDATED`。**不**关闭 R2W / R2B / actual worker / 真实 Qlib / new root / retained / M3 Gate。

| 轮次 | evidence root | 结果（历史保留，不洗白） |
| --- | --- | --- |
| VALIDATION1 | `artifacts/agent_runs/m3-r2i-validation1-20260826T105333347Z` | identity PASS；unit `29 passed / 1 failed`（fixture 共享父目录二次 `mkdir` → `FileExistsError`）；integration / Ruff / mypy / cold / scope **UNRUN**；`STOP=STAGE_FAILED:02-unit` |
| STATIC_REWORK2 | exact6 unit fixture + delivery | 共享 parent `mkdir` 收敛为一次；production/其他测试未改 |
| VALIDATION2 | `artifacts/agent_runs/m3-r2i-validation2-20260826T110402344Z` | identity PASS；unit **30 passed**；integration **25 passed**；Ruff exact3 PASS；mypy source PASS；cold PASS；scope 因本轮 `.mypy_cache` 残留 **STOP**（`STOP=CACHE_RESIDUE:.mypy_cache`）后精确清理 |
| scope-close | `artifacts/agent_runs/m3-r2i-validation2-scope-close-20260826T111225888Z` | 独立无 Python scope-close **PASS**（`SCOPE_CLOSE=PASS`；cached=0；diff-check PASS；cache/process residue=0） |

### VALIDATION2 product SHA（stdout）

| 阶段 | SHA-256 |
| --- | --- |
| unit | `2dc90a1cfec229d3ca15bdeea243ef755f053ed260f5f1af0baf133c91d48bd2` |
| integration | `bfefd10ad1f7f178543d7c6837f86069b74d49d6b2e6c31209b60dbc66340e22` |
| Ruff | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| mypy | `8e63ae22e8213e327a5e9cbd584067681681bd8ef7f25c869877887ccdcfc4ff` |
| cold | `c1a6694e0f5d2fe587ae68c0c187026cd54e534db00fb4217a256e7342e7a4c2` |

### scope-close SHA

| 项 | SHA-256 |
| --- | --- |
| scope | `095e8db4ecb5a4afd563dc74332556988499c5aac2e68c9a93810e612497d256` |
| summary | `bc09f1322eea35c4b68dbc7d44d04400802c92ac19bc7b3e79a37609a085224d` |
