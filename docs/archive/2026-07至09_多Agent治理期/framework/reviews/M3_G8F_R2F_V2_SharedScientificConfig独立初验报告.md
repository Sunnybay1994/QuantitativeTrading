# M3-G8F-R2F-V2 Shared Scientific Config 独立初验报告

日期：2026-08-28<br>
结论：`STATIC_REVIEW_FAIL / STATIC_ONLY`（P1 证据缺口；不得申请后续 Windows validation）

## 1. 审查身份、输入与边界

- task id：`M3-G8F-R2F-V2-SHARED-SCIENTIFIC-CONFIG`
- exact base：`fbf783ef40d9a73136ff1979409c4d369580c220`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g8f-r2f-v2-shared-scientific-config`
- reviewer：未参与本包实现的独立 reviewer；本轮唯一写入为本报告。
- 本轮完整读取：根 `AGENTS.md`、`.ai/README.md`、`.ai/coding_rules.md`、`.ai/review_checklist.md`、`.ai/workflows/multi_agent_delivery.md`、本任务书、交付报告、冻结 runtime、unit 与 integration 文件。
- 冻结输入 SHA-256（本轮只读复核确认）：

| 输入 | SHA-256 |
| --- | --- |
| `src/quant/research/m3/successor_runtime.py` | `cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be` |
| `tests/unit/test_m3_successor_runtime.py` | `2e120707ffb75df2cc3363bf87ec6f8a7e47f929b7a18cd95b40445809eb37fa` |
| `tests/integration/test_m3_successor_runtime.py` | `935c825b21653b9b627cfe9d181e87ba71809e5e372ea085507b85ac53fa463d` |
| `docs/framework/tasks/M3_G8F_R2F_V2_SharedScientificConfig任务书.md` | `08741e292b8e2b4ef3c03a97333fc28b1c1f5cfa8b1249e9a232327feeb8e02e` |
| `docs/framework/deliveries/M3_G8F_R2F_V2_SharedScientificConfig交付报告.md` | `fd579c552c644b23d6db24e371c99019d5f10ee510993f1c6296b3f64860be80` |

使用的只读检查为 `Get-Content`、`rg`、`git diff`、`git diff --check`、`git status` 与 `Get-FileHash`。未运行 Python、pytest、Ruff、mypy、cold import、Qlib、真实 data/network、worker、controlled stage、root/request/release/evidence 创建、stage 或 commit。静态结论不等于运行通过。

## 2. 任务合同逐项映射

| 合同（任务书） | 静态证据 | 结论 |
| --- | --- | --- |
| §4.1 每 fold request-bound exact path、ordinary/non-reparse fresh read、raw SHA、fresh `load_m3_config` 等值 | `successor_runtime.py:1947-1960` 在 fold 循环内逐项计算 path、读 bytes、校验 raw SHA、再调用 loader 并比较对象；未见把第二 fold 改成缓存结果 | 实现面通过；同一 physical path 的测试证据不足，见 §3 P1-F1 |
| §4.2 删除 raw/full identity size=2 人工门禁 | 相对 exact base 的 diff 删除 `config_identities`、`full_config_identities` 及其 size 判断，并改正误导注释 | 通过 |
| §4.3 scientific identity exact1 | `successor_runtime.py:1945,1961,1976-1977` 仍收集并要求唯一 scientific identity | 通过 |
| §4.4 G1 release exact2/distinct | `successor_runtime.py:1946,1962-1979` 仍逐 fold fresh verify，并同时检查 list 长度 2 与 tuple set cardinality 2；integration alias 反例在 `test_m3_successor_runtime.py:982-1016` | 通过 |
| §4.5 fold/work/gate/receipt/terminal closure不合并 | production 保留 fold-bound work key、gate identity 与 terminal binding；integration same-config 主路径只断言 fold 数、raw/full 相等、release id 不同，未逐项断言 work/gate/terminal separation，见 §3 P1-F2 | 实现面通过；证据不足 |
| §5 失败语义与写入前拒绝 | `_validate_request` 在 `run_two_fold_successor` 的 stage/worker 前调用；duplicate release integration 断言 `SUCCESSOR_INPUT_INVALID`、public API calls 为空、terminal/receipts 不存在 | 通过（运行结果未执行） |
| §6.1/§6.2 required tests | shared-config、duplicate release、replay/tamper、different-path same-bytes 均有新增测试；两项强制 same-physical/closure assertions缺失 | 不满足完整测试合同 |
| §7 独立 review / STATIC_ONLY | 本报告仅写 review；实现、测试、taskbook、delivery 未修改 | 角色与范围通过 |

## 3. P1 发现（现象—根因—应遵循规则—最小复现—新增测试—通过条件）

### P1-F1：same physical config 的第二 fold fresh read/load 没有测试证据

**现象**：任务书 §4.1、§6.1-1、§7 明确要求两个 fold 即使绑定同一 physical file，也必须分别 fresh read/load/compare，且第二 fold 漂移要归一为 `SUCCESSOR_INPUT_INVALID`。新增 unit 测试 `test_validate_request_allows_shared_config_with_two_fresh_loads` 断言的路径是 `configs/fold_001.toml` 与 `configs/fold_002.toml`（`tests/unit/test_m3_successor_runtime.py:189-192`）；integration 测试同样只使用这两个不同路径（`tests/integration/test_m3_successor_runtime.py:939-942`）。因此它们能证明“不同路径各调用一次”，不能排除按 physical/config identity 缓存第一 fold 结果的实现回归。

**根因**：测试 fixture `_validation_request` 与 `_request(same_config=True)` 都创建两个文件；没有把两个 `SuccessorConfigInput.relative_path` 绑定到同一个 `PurePosixPath("configs/shared.toml")`，也没有在第二次 loader/read 时制造同一 physical file 的 drift。

**应遵循规则**：任务书 §4.1 第 1–5 项及 §4.1 末段规定，shared config 只放宽 raw/full distinct，不放宽 per-fold fresh closure；同一 physical file 必须在当前循环分别 fresh read/load/compare。任务书 §6.1-1 要求 fresh loader 对同一路径逐 fold 恰调用两次。

**最小复现（STATIC_ONLY，未执行）**：

1. 构造两个 sorted fold requests，令两项都绑定同一个 `configs/shared.toml`，其 request-bound `LoadedM3Config` 相等，且两条 release identity distinct。
2. 将 `runtime.load_m3_config` 替换为带计数的窄 seam；调用 `_validate_request`，预期同一 resolved path 的调用序列为 `[shared, shared]`，计数恰为 2。
3. 在第二次 read/load 前或第二次 loader 调用期间让该 physical file bytes 变为与 request raw SHA 不同；预期 `SUCCESSOR_INPUT_INVALID`，且不产生 controlled/stage/public API 写入。

**必须新增测试**：unit 至少覆盖同一 relative path 的 loader exact2 及第二 fold bytes/config drift；integration 以同一 physical path 跑 shared-config 双 fold，并在第二 fold closure 前 tamper 后断言 fail-closed。测试必须继续证明没有第三文件扫描。

**通过条件**：同一 physical path 的 fresh read/load/compare exact2 证据成立；第二 fold drift 稳定得到 `SUCCESSOR_INPUT_INVALID`；production/test scope 仍只在本任务 exact6 内。

### P1-F2：same-config 下 work/gate/terminal 分离的强制集成断言缺失

**现象**：任务书 §4.5 和 §6.2-2 要求 shared config 不得合并 fold execution、work/gate scope、receipt ownership、cache consumption，并要求 terminal identity 闭合两个 fold 与两个 release。`test_same_config_paths_run_two_distinct_folds_with_fresh_closure` 仅断言 `len(result.folds)==2`、fold 名、两项 raw/full 相等及 release id 不同（`tests/integration/test_m3_successor_runtime.py:944-949`），没有断言：每 fold 的两个 work key 按 fold 区分；non-shared work receipt node/path/bytes 不跨 fold alias；四个 gate identity 按完整 two-fold execution 重算；terminal `folds`/release bindings 与 two-fold identity 同时包含两个 fold 和两个 distinct release。

**根因**：新增 integration fixture 的 `_DeterministicProductionBoundary` 确实生成 fold-bound work receipt 与 work key，但测试只检查结果的浅层字段；已有默认配置 durable/replay 测试覆盖了部分共享 receipt 行为，不能替代 same-config 场景的完整 closure 断言。

**应遵循规则**：任务书 §4.5 明确规定 shared config 不能合并 execution/work/gate/receipt/terminal；§6.2-2 要求 same-config 下 experiment/work/gates/terminal 按 fold/release 闭合，且不能有 cross-fold cache/receipt alias。静态实现中 `_execution_join_payload` 仍含 fold/work identities，`_validate_global_receipt_ownership` 仍只允许列明 shared stages 的 fold-None 重用，terminal binding 仍携带 fold 与 G1 release。

**最小复现（STATIC_ONLY，未执行）**：

1. 用 `_request(tmp_path, same_config=True)` 运行最小 two-fold fixture。
2. 对两个 `FoldExecution`，断言 `work_identities` 的 `(fold, horizon, work_key)` 集合互不相同；除 `_SHARED_RECEIPT_STAGES` 且 `fold is None` 外，receipt node/path/sha/semantic owner 不得相互复用。
3. 对每个 gate 断言 `identity == compute_successor_gate_identity(gate, result.folds, prior_gates)`，并确认 gate sequence 为 summary→reproducibility→readiness→acceptance，refs 不跨 gate 重复。
4. 对 `result.attestation` 断言恰有两个 fold binding、每个 fold 的 release id/manifest SHA 与 request exact 对应，`two_fold_identity` 由两个 fold/release 输入重算一致；exact replay 仍只复用同一 terminal。

**必须新增测试**：扩展 same-config integration 测试，覆盖上述 work key、non-shared receipt ownership、gate identity/顺序、terminal fold/release binding 与 exact replay；保留现有 different raw/full + same scientific 正向。

**通过条件**：same-config 集成场景逐项证明两个 fold execution、work、gate、receipt、terminal/cache closure 未合并或弱化；任何人为跨 fold alias 都在写入 terminal 前稳定失败；测试只使用既有 monkeypatch seam，不改 bridge/verifier/public schema。

## 4. 实现者未使用的对抗审查

除上述强制证据缺口外，针对实现者未用的反例做静态控制流核对：

1. **同一 physical config + 第二次 fresh loader drift**：`_validate_request` 的 `for item in request.folds` 每轮都重新生成 `raw_path`、调用 `_read_regular_file` 和 `load_m3_config`，未发现按 raw/full/scientific identity缓存的分支；因此生产控制流方向正确，但 F1 测试缺口仍阻断 review。
2. **不同 wrapper/path、相同 release tuple**：integration `_release_alias` 创建不同 `VerifiedG1Release` wrapper 与不同 root；`verify_g1_release` 返回等值 wrapper 后，`release_identities` 的 tuple set cardinality 为 1，`_validate_request` 在任何 stage 前拒绝。该反例与任务书 §4.4 一致。
3. **相同 release object 的退化反例**：unit `test_validate_request_rejects_duplicate_release_identity` 证明 list length=2 不能单独放行，但它不是 wrapper/path 变体；integration alias 测试补足了变体。
4. **不同 raw/full、same scientific 正向**：默认 `_request` 使用 `config-a`/`config-b`，而 scientific selector 相同；原 durable test 保留该路径，说明本包不是把 config 强制改为必须相同。
5. **unbound third config**：same-config integration 在 `unbound.toml` 写入未绑定文件，request validation 只消费两个显式 relative paths；测试意图支持禁止 glob/latest/scan，但 F1 的同 physical path exact2 仍未覆盖。

## 5. 范围、字节与证据边界

- 预审 worktree 在本报告写入前仅有任务书、交付报告两个 untracked 文档，以及 exact6 中 production/unit/integration 三个预期 dirty 文件；未见 reviewer 对白名单外路径写入。
- 本轮未创建 config、request、release、controlled root、evidence 或临时探针；未读取真实 data、ignored/local、LOCKED 或 retained 产物。
- 交付报告的 `DELIVERY_READY / STATIC_ONLY / UNRUN` 边界与本轮静态观察一致；其“通过条件”不能替代本轮缺失的强制测试证据。
- 运行验证、Windows identity/focused unit/integration/Ruff/mypy/cold、exact6 scope/cache/process residue 均为 `UNRUN`，不得把本报告写成 Windows engineering validated、formal config ready、A14/A15/A17 closed、actual successor/Qlib、retained、M3 Gate 或 Linux Gate 完成。
- 本报告写入后应由父 Agent 采集本文件 SHA-256；本轮未 stage/commit。

## 6. 结论与返工闭环

当前 production diff 的最小方向正确：删除 raw/full artificial-distinct 门禁，保留 scientific exact1、每 fold fresh closure，并将 release identity 强化为 exact2/distinct；未发现新的生产 P0/P1 逻辑缺陷。但任务书把 F1/F2 对应的集成与单元证据列为强制 acceptance，当前测试不能证明 same physical path 的第二次 fresh reload，也不能证明 same-config 的完整 work/gate/terminal closure。因此结论为：

**`STATIC_REVIEW_FAIL`（P1-F1 + P1-F2；STATIC_ONLY）**。

返工必须回到同一实现链，仅在任务书 exact6 内补充测试与 delivery 证据；实现者完成后由本独立 reviewer 按同一冻结合同复验。P1 闭合前不得申请 §8 Windows validation；即使复验通过，仍不表示 actual successor/Qlib、formal config ready、A14/A15/A17、retained、M3 Gate 或 Linux Gate 完成。

## 7. STATIC_REWORK1 复验

复验输入为任务书 §10 冻结的当前文件。production SHA 仍为
`cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be`，unit、integration、delivery
分别为 `4d2cddc93e03486c98be4734f19bc93db16c82edf96be4c19a9570089a108ddc`、
`8c040c593239c2d3427490fd411adc2ee62d675c395970e29fba2a4fef3271d4`、
`8233497420a385d67458cf5c5660ea62420d3eb59a7b8a5aff8b2a657102bcb0`；taskbook 当前 SHA 为
`87ced1ee8cacd431f69297c5d3b2b32bdffd2274e6278f6d87d07a60aedad3fd`。原 review SHA 为
`5cee5a1ea9fbcf312c70c2e7d1f12fd8c94082b698f923199b12cbabf33b8a17`。上述 SHA 均由本轮
`Get-FileHash -Algorithm SHA256` 只读复核确认。

### 7.1 P1-F1 复验：same physical fresh closure

首轮 F1 已闭合。unit fixture 现在让两个 fold 都绑定
`PurePosixPath("configs/shared.toml")`（`tests/unit/test_m3_successor_runtime.py:99-115`），正向测试断言
same resolved path 的 loader 序列恰为两次（`:178-202`）；另有 second-load config drift 测试断言 read/load
均为 `[shared, shared]`、错误码为 `SUCCESSOR_INPUT_INVALID`（`:223-282`），并保留 unbound third file。

integration helper 同样支持 same physical path（`tests/integration/test_m3_successor_runtime.py:712-767`）；
第二 fold bytes tamper 测试在首次 load 后篡改该文件，断言两次 fresh read、首次 load、无 release/public/stage
写入（`:1097-1135`）。因此任务书 §10.1 的 same-path 与 drift 语义在测试结构上已覆盖。

### 7.2 P1-F2 复验：same-config 完整 closure

首轮 F2 已闭合。same-config integration 正向现在静态断言：

- 两 fold 的四个 `(fold, horizon, work_key)` 所有权及 `compute_work_key` 重算（`:978-998`）；
- shared receipt 仅限已有 `_SHARED_RECEIPT_STAGES` 且 `fold is None`，fold 间无额外 node alias（`:999-1009`）；
- 四 Gate 顺序及每个 `compute_successor_gate_identity` 重算（`:1010-1021`）；
- terminal 恰有两个 fold binding，config raw/full、G1 release id/manifest SHA 与 request 对应，
  `two_fold_identity` 重算一致（`:1022-1037`）；
- exact replay 不增加 public publication，same-config distinct-path/equal-bytes 正向仍保留（`:1041-1062`）。

与生产控制流对照，`successor_runtime.py:1947-1979` 的 per-fold config/release closure、
`_execution_join_payload` 的 fold/work identity、全局 receipt ownership 与 terminal binding 均未被 rework 改动。
该项静态证据已闭合。

### 7.3 新发现 P1-F3：integration fresh-call count 与完整运行控制流矛盾

**现象**：`test_same_config_paths_run_two_distinct_folds_with_fresh_closure` 在完整 `_run(request, boundary)`
之后断言 `load_calls` 和 `read_calls` 各只有同一 shared path 两次，且 `len(release_calls) == 2`
（`tests/integration/test_m3_successor_runtime.py:965-977`）。

**根因**：生产 `run_two_fold_successor` 先在 `successor_runtime.py:1704` 调用一次 `_validate_request`；成功发布
terminal 后又调用 `verify_terminal_attestation`，后者在 `successor_runtime.py:1868-1872` 再次调用
`_validate_request`。因此一个成功完整运行至少执行 shared path 的 config read/load 两轮，即各四次；同时
`_read_regular_file` wrapper 还会记录终端 `completion.json` 的读取（`:1875-1877`），release fresh verify
也至少发生两轮。当前 exact-two 断言与该静态调用图不相容，不能作为可通过的集成测试。

**应遵循规则**：任务书 §10.1 要求 separately record read/load 调用序列并证明每 fold fresh exact2；测试计数
必须精确标定被观察的验证轮次，不能因终端 fresh verification 而写出必然失败的总调用数，也不能将失败测试
误报为 STATIC 覆盖通过。

**最小复现（STATIC_ONLY，未执行）**：

1. 使用 `test_same_config_paths_run_two_distinct_folds_with_fresh_closure` 的 same physical `shared.toml` 正向 fixture。
2. 按 `run_two_fold_successor → _validate_request → ... → verify_terminal_attestation → _validate_request` 的源码路径观察
   `load_calls`、`read_calls`、`release_calls`。
3. 当前测试预期 `load_calls == [shared, shared]` 且 `read_calls == load_calls`，但第二次 terminal verification
   会追加第二轮 shared reads/loads，随后还会追加 completion.json read；断言因此不满足。

**通过条件**：将计数器限定在一次直接 `_validate_request` 调用（并另行断言完整运行的 terminal fresh verification），
或按完整控制流精确断言两轮 request validation 加 terminal read；不得删除 terminal fresh verification、放宽到不确定的
`>=2`，也不得修改 production 仅迁就测试。修复仍只能触及任务书 §10.3 允许的 unit/integration/delivery 文件。

## 8. STATIC_REWORK1 结论

P1-F1 与 P1-F2 的首轮阻断在当前测试结构中已闭合；production 仍未发现新的逻辑 P0/P1。可是 P1-F3 是
新增 integration 正向测试的确定性断言错误，导致冻结的 focused integration 验收无法按当前代码通过，且 fresh
调用次数证据不可信。故当前复验结论为：

**`STATIC_REWORK1_REVIEW_FAIL`（P1-F3；STATIC_ONLY）**。

本轮未运行 Python、pytest、Ruff、mypy、cold、Qlib、data/network、root/evidence、stage 或 commit；不得申请
任务书 §8 Windows validation。返工必须回到同一实现链最小修正 P1-F3 后，再由本 reviewer 复验。即使后续
`STATIC_REWORK1_REVIEW_PASS`，仍不表示 formal config ready、A14/A15/A17、actual successor/Qlib、retained、
M3 Gate 或 Linux Gate 完成。

## 9. STATIC_REWORK2 复验

本轮按当前任务书 §11 复验，输入 SHA 已只读核对如下：

| 输入 | SHA-256 |
| --- | --- |
| taskbook | `14bcc60a8088d6d7498f495726ecee2fa8080de8a2effe9d4bc79f80cc563e09` |
| production | `cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be` |
| unit | `4d2cddc93e03486c98be4734f19bc93db16c82edf96be4c19a9570089a108ddc` |
| integration | `f161c237cbd40e3bb3e8bdfbb7e0cb114b48dc8f9fadbea77aa34151fb22321e` |
| delivery | `148b6b156bef9b0c335b697bff3338fecd6158e0d02bbc9f871e895bd0ac90b2` |
| review pre-REWORK2 | `e92ad3465960c00675fb3438d1fb1dba85658fdbded1eeaeda1543c39890c8c0` |

### 9.1 §10 闭包复验

- P1-F1：已闭合。unit 同一 `shared.toml` 的正向 loader 序列为 `[shared, shared]`，second-load config drift
  仍逐次 read/load 并归一为 `SUCCESSOR_INPUT_INVALID`；integration 的 second-fold bytes drift 在任何
  `public_api_calls`、terminal、receipts 前拒绝。
- P1-F2：已闭合。same-config integration 保留 work key 重算/互斥、shared-stage-only receipt ownership、四 Gate
  顺序与 identity、两项 attestation binding、`two_fold_identity` 和 exact replay 断言；different-path/equal-bytes
  正向仍存在。
- P1-F3：已闭合。`load_calls` 现在静态要求 shared path exact 四次，`release_calls` 要求
  `[fold_001, fold_002] × 2`，聚焦 `read_calls` 为 shared 四次加 canonical terminal 一次。

### 9.2 新发现 P1-F4：`all_read_calls` 不是完整原始读取序列，且其顺序断言与 production 控制流冲突

**现象**：任务书 §11.2 要求以 `all_read_calls` 作为不可过滤、不可重排的完整原始序列，并明确不能用聚焦
`read_calls` 掩盖 public receipt fresh reads；同时冻结要求 all-read 前四项为 shared config，最后一项为
canonical `completion.json`。当前 integration helper 只在 `read_calls is not None` 时包裹
`runtime._read_regular_file`（`tests/integration/test_m3_successor_runtime.py:824-842`），将调用追加到
`all_read_calls`（`:829-830`）。它没有观测 `runtime.verify_stage_receipt_with_bytes` 的读取。

**根因**：production `_verify_receipts` 与 `_controlled_tree_sha256` 直接调用
`verify_stage_receipt_with_bytes`（`src/quant/research/m3/successor_runtime.py:2622-2625,2680-2683`）；
该 public verifier 在 `run_state.py:261-287` 内部通过 `_read_stable_regular_bytes` 读取 receipt 和输入/输出
artifact，绕过 runtime 的 `_read_regular_file` wrapper。因此当前 `all_read_calls` 不是所有真实读取的原始
序列。即使只讨论 runtime wrapper，其 `_build_attestation` 在 terminal 发布前调用
`_controlled_tree_sha256`，而 `_walk_controlled_tree` 会对 controlled tree 文件执行
`_read_regular_file`（`successor_runtime.py:2664-2692,2775`）；这些 receipt/artifact 读取发生在第二轮
shared config validation 之前，所以 `all_read_calls[:4] == [shared] * 4`（integration `:1002`）也与静态
调用顺序不符。`read_calls` 通过 tracked path 过滤、terminal 去重，只能得到派生的假绿视图，不能修复此问题。

**应遵循规则**：任务书 §11.2-3 要求保留完整 raw sequence，确认未丢失、重排、过滤真实读取；任何 public
receipt fresh read 必须可审计。若该要求与实际公开 receipt 读取顺序冲突，必须以精确调用图报告 P1 并先修正
观测合同，不能只调整过滤后的 `read_calls` 或放宽断言。

**最小复现（STATIC_ONLY，未执行）**：

1. 使用 same-physical positive fixture 调用 `_run`。
2. 第一轮 `_validate_request` 产生 shared×2；随后 build/attestation 路径对已有 controlled receipts/artifacts
   发生 public verifier 读取，且 `_controlled_tree_sha256` 发生 controlled-tree `_read_regular_file` 读取。
3. 发布 terminal 后，`verify_terminal_attestation` 再次 `_validate_request` 产生 shared×2，随后读取 canonical
   completion；其后还会重新验证 receipts/tree。
4. 当前 helper 的 `all_read_calls` 只看到 runtime `_read_regular_file` 子集，当前 `all_read_calls[:4]` 断言又
   要求四个 shared 连续，既不能证明完整性，也不能与上述顺序同时成立。

**通过条件/最小修正**：必须在 exact6 测试范围内建立不丢失的 raw recorder：至少同时包裹 runtime
`_read_regular_file` 与 public `verify_stage_receipt_with_bytes` 所在 read seam，并明确记录 receipt/artifact
读取及调用阶段；`all_read_calls` 应为该原始记录，`read_calls` 只能由它派生。然后按真实 production 调用图
逐项断言 shared×4、release 两轮稳定顺序、所有其余读取均在 controlled root、无 unbound config、terminal 的
位置及后续 receipt/tree fresh reads。若无法在不改 production/public API 的前提下使“前四项 shared、最后一项
completion”与完整 raw sequence同时成立，应按任务书冻结的 `CONTRACT_STOP / TEST_OBSERVABILITY_MISMATCH`
提交精确调用图，而不是过滤或重排 raw 序列。

## 10. STATIC_REWORK2 结论

P1-F3 的计数修正方向与 taskbook §11.2 的 shared×4、release 两轮、terminal focused 派生一致；§10 的
same-physical fresh、drift、work/receipt/gate/attestation/two-fold/replay 及 different-path 正向闭包未见
回退。可是 P1-F4 仍未闭合：`all_read_calls` 漏掉 public receipt fresh reads，且其“前四 shared”顺序断言
在 production 的 pre-publish controlled-tree reads 存在时静态不成立。故结论为：

**`STATIC_REWORK2_REVIEW_FAIL`（P1-F4；无新增 P0/P2；STATIC_ONLY）**。

本轮未运行 Python、pytest、Ruff、mypy、cold、Qlib、data/network、root/evidence、stage 或 commit；不得申请
任务书 §8 Windows validation。返工必须回到同一实现链最小修正观测层，并由本 reviewer 复验；production SHA
仍冻结不变。

## 11. STATIC_REWORK3 复验

本轮按任务书 §12 对 P1-F4 进行同一独立 reviewer 的静态复验。冻结输入经只读哈希核对：production
`cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be`、unit
`4d2cddc93e03486c98be4734f19bc93db16c82edf96be4c19a9570089a108ddc`、integration
`53498bc6be6c6aa8fdef34342a2df8e22e9a20a487fa8227a68ca580562519d6`、taskbook
`3ccc2bdb506b455c3880b7da302c5c1d32c58d8dd1c23a5940d2b2127fc6ca79`、delivery
`01beb50b78d9685ee5e61421c5f1348a44b182ba55f9b5d5734dd8152006c571`，REWORK2 review
`302515463b4ffd09fb57253ada5ad53f3364a18b6c4d21aa7ff32ad33c2eee22`。

### 11.1 §12 正确观测域与两轮 fresh closure

1. integration helper 当前只接受并追加未过滤、未去重的 `runtime_read_calls`（`tests/integration/test_m3_successor_runtime.py:788-829`）；
   静态搜索未发现 `all_read_calls`、`tracked_read_paths` 或 `dedupe_read_paths`。
2. `_observe_validation_rounds` 在 monkeypatch 前保存原始 `runtime._validate_request`，按每次调用前的三组计数
   起点调用原函数，并在成功返回后保存本轮 read/load/release slice（`:888-911`）；未吞异常、修改 request、缓存结果或
   绕过原函数。
3. same-physical 正向使用两个 fold 的 `configs/shared.toml`，并断言完整 `_run` 恰有两轮且两轮完全相同：每轮
   runtime read `[shared, shared]`、load `[shared, shared]`、release `[fold_001_release, fold_002_release]`
   （`:970-1016`）。全局窄 runtime read 日志保持原始顺序但只作位置无关的 shared exact4 计数（`:1017-1022`）；
   轮外每条 runtime read 要么是 shared，要么位于 controlled output root，canonical terminal 至少出现一次，unbound
   config 不出现（`:1023-1029`）。这与 §12 不再冻结全局首四/末一位置的更正一致。
4. production SHA 未变化；原始 `_validate_request` 仍由 `run_two_fold_successor` 的 pre-stage 调用与
   `verify_terminal_attestation` 的 post-publish 调用各执行一次，未因测试 wrapper 改变控制流。

### 11.2 §10 其余闭包与对抗反例

- same-config 的 fold/work ownership、`compute_work_key` 重算、shared-only receipt ownership、四 Gate 顺序与
  `compute_successor_gate_identity` 重算、两个 attestation bindings、`two_fold_identity` 与 terminal 临时文件闭合
  断言均仍在正向测试（`:1030-1095`）。
- different physical paths、相同 raw/full/scientific bytes 的既有正向仍保留（`:1098-1120`）；exact replay 不产生第二次
  public publication，且 shared config drift 仍拒绝（`:1122-1152`）。
- second-fold same-physical drift 仍在第二次 fresh runtime read 时拒绝，错误码为 `SUCCESSOR_INPUT_INVALID`，且无
  release/public/stage/terminal/receipt 写入（`:1154-1192`）；相同 `(release_id, manifest_sha256)` 的不同 wrapper/path
  仍在 stage 前拒绝（`:1195-1232`）。unit 的 shared exact two read/load、第二次 load drift 与 duplicate release
  负向未漂移；production 的 scientific exact1、每 fold fresh closure、release exact2 distinct 仍保持冻结。

### 11.3 结论与证据边界

P1-F4 已闭合：raw 观测已降格为诚实命名的 runtime 窄读取日志，逐轮 exact slice 由 test-owned wrapper 证明，shared
exact4 改为位置无关计数，轮外 runtime read 的 controlled-root/unbound/terminal 约束保留；没有再用过滤、去重或
重排伪造全局序列。§10 的 same physical fresh exact2、第二 fold drift fail-closed、shared/nonshared receipt ownership、
四 Gate/identity、terminal/attestation/two-fold、replay 与 different-path positive 均未发现回退。

故本轮结论为：

**`STATIC_REWORK3_REVIEW_PASS`（无 P0/P1/P2；STATIC_ONLY）**。

本轮只做静态源码/测试/任务书/交付文档映射；未运行 Python、pytest、Ruff、mypy、cold、Qlib、data/network、
root/evidence、controlled stage、Windows validation 或任何 Git stage/commit。因此该结论不等价于 runtime PASS、
Windows engineering validated、formal config ready、actual successor/Qlib、retained、M3 Gate 或 Linux Gate 完成。
实际写入范围仅为本 review 报告；production、unit、integration、taskbook、delivery 均未由本 reviewer 修改。

## 12. STATIC_REWORK4 复验

本轮按任务书 §13 对 replay fresh-verification 断言进行同一独立 reviewer 的静态复验。冻结输入经只读哈希核对：production
`cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be`、unit
`4d2cddc93e03486c98be4734f19bc93db16c82edf96be4c19a9570089a108ddc`、integration
`28b79f7276df878351c86b45b0538362547afc03f26df76470e810a703b7bf4f`（73229 bytes）、taskbook
`f932581760c9cf94c2529ed5e690b07d7c98cd1be067eed41a5a50ce7dde0be3`、delivery
`09677d1d63dbac103cdd8356edba7465dab2bb9086e8ffb88f09aa96d15e46ff`，REWORK3 review
`92c88ad0a51f12bbb513a4c3a2f2ed56d3432d30ccf62ffa35131fb7aaa63a9a`。

### 12.1 replay prefix/suffix 行为等价

`test_same_config_replay_is_exact_and_second_fold_tamper_fails_fresh`（`tests/integration/test_m3_successor_runtime.py:1122-1171`）
的修正局限于测试观测与断言，未改变 production、terminal verifier、unit 或其他反例：

1. 首次 `_run` 后保存完整 `first_public_api_calls`；replay 后对相同长度 prefix 逐字比较（`:1137-1148`），证明首次
   调用前缀未被改写或重排。
2. replay suffix 被 exact 限定为且仅为
   `summary-public-verify`、`reproducibility-public-verify`、`readiness-public-verify`、
   `acceptance-public-verify`（`:1149-1155`），不是仅断言 `+4`。同时显式排除 upstream/formal wave、`run-plan`、
   `public-run` 与 `publication`（`:1156-1162`）；exact tuple 本身也不包含这些调用。
3. replay 断言 `reused is True`、terminal path 与首次相同、attestation 完全相同且 `two_fold_identity` 不变（`:1141-1145`）。
   这保留 fresh Gate verification，同时证明没有第二次 stage/work/publication 行为。
4. 保存 `calls_after_replay` 后篡改同一 physical `shared.toml`；第三次 `_run` 预期
   `SUCCESSOR_INPUT_INVALID`，且 `public_api_calls` 长度保持不变（`:1163-1171`），因此 drift 在任何新增
   public verifier、stage 或 publication 前拒绝。

### 12.2 §10/§12 既有闭包与冻结复核

- production 与 unit SHA 仍分别为冻结值；integration 当前 diff 仅增加/修正测试观测、same-config 既有覆盖及 replay 断言，
  无 production hook、terminal schema、错误码、cache 或第二验证序列变化。
- §12 的 test-owned `_validate_request` wrapper、两轮 validation、每轮 shared read/load exact2、release
  `[fold_001, fold_002]`、未过滤 `runtime_read_calls`、controlled-root/unbound/terminal 约束保持；未恢复旧的
  `all_read_calls`/过滤/去重视图。
- §10 的 same physical fresh exact2、second-fold drift 前置拒绝、duplicate release、work ownership、shared/nonshared
  receipt ownership、四 Gate 顺序与 identity、两个 attestation bindings、`two_fold_identity`、different raw/full same
  scientific 正向均仍在当前测试结构中；本轮没有删除或弱化这些断言。

### 12.3 结论与证据边界

REWORK4 只修正了因 V3 发现而过严的 replay public-call 计数断言：允许既有四项 Gate fresh verifier suffix，同时严格保持首次
prefix、replay identity/terminal/reused、无第二 publication，以及 shared config drift 的零新增 public-call 失败语义。
未发现 P0、P1 或 P2。

故本轮结论为：

**`STATIC_REWORK4_REVIEW_PASS`（无 P0/P1/P2；STATIC_ONLY）**。

本轮未运行 Python、pytest、Ruff、mypy、cold、Qlib、data/network、root/evidence、controlled stage、Windows
validation 或任何 Git stage/commit；V3 的历史 `29 passed / 1 failed` 仅作为任务书背景，不被改写为本轮运行 PASS。
该结论不等价于 runtime PASS、Windows engineering validated、formal config ready、actual successor/Qlib、retained、
M3 Gate 或 Linux Gate 完成。实际写入范围仅为本 review 报告；production、unit、integration、taskbook、delivery 均未由
本 reviewer 修改。

## 13. EVIDENCE_REVIEW

本轮按 taskbook §14 对 V1–V5 保留证据、delivery 引用、组合范围与剩余边界进行独立只读复核。当前冻结输入经
`Get-FileHash -Algorithm SHA256` 核对：production `cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be`、
unit `4d2cddc93e03486c98be4734f19bc93db16c82edf96be4c19a9570089a108ddc`、integration
`28b79f7276df878351c86b45b0538362547afc03f26df76470e810a703b7bf4f`、taskbook
`77c235669ef37dc24341dfa58007f8ab3be3b8ff682d50b28d22c35a764f59cc`、delivery
`5dba612abc3e31c90dc9e6f34e9567e3a2ca318c5aa71e6b7a0329c952fa5371`，REWORK4 review
`4becfdd9b27366775c35e065812741f824b63b9f15add22d12a3ecc5381d5162`。

### 13.1 V1–V5 证据逐项对账

保留 evidence 文件内容与 taskbook §14 的结论一致，关键文件 SHA 对账如下：

| 轮次/文件 | 实际 SHA-256 | 对账结论 |
| --- | --- | --- |
| V1 `summary.txt` | `47755ef671684c5f915629ddba624552c7a84d65c2a083ac620e36a1cbf537b8` | carrier syntax STOP；Python 0-call，产品阶段 UNRUN |
| V2 `summary.txt` | `60501198f959b2db4383b5c71098a7f1f507eec9b9db16d1c3236313755c633b` | carrier preflight STOP；Parser errors 0、Python 0-call，产品阶段 UNRUN |
| V3 `summary.txt` | `3bc22a591a7d64d9479cd3cef5de112f65691561d1835f46d582ce39604f418f` | identity/unit 通过，integration 29 passed/1 failed |
| V3 `02_unit.stdout.txt` | `7f0c60897d815a9e0d812a5ec768f0de50134fbdb41671316b2a62c2d511a2e6` | `35 passed` |
| V3 `03_integration.stdout.txt` | `ad36fc0e781bb7bcd8a2210d2dc17d727013f390a9fe6166e3a33a5e518e569f` | 失败仅为旧 replay 计数断言；不是产品逻辑失败 |
| V4 `summary.txt` | `0165770cda42407a1eb9257d85a3e7748c23cd412a70806748906472111c4468` | identity/replay node/Ruff exact3/mypy/cold 通过；scope carrier STOP |
| V4 `02_replay_node.stdout.txt` | `27b93b41fc7fe0209fb0edde525c85c2884ce93570c953f81487fc13e272dd56` | replay 修正节点 `1 passed` |
| V4 `03_ruff.stdout.txt` | `af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af` | Ruff exact3 通过 |
| V4 `04_mypy.stdout.txt` | `94594db09076fe305d51b50210d0bc5e9d275fb814f8b42c1ed4cf3368392f9a` | production mypy 通过 |
| V5 `summary.txt` | `d52f14f869ddcfc3840ad0f6ae72738a5a3a549d8079e795022f9dc36d2c60de` | scope-only PASS；exact6/cached0/diff-check/residue 均闭合 |

V1 carrier 文件进一步明确 `parser_error_count=2`、`python_call_count=0`、资源未取得；V2 明确 Parser errors 0、
`parser_triple_created=true`、Python 0-call、资源未取得。V3 exit artifacts 为 identity=0、unit=0、integration=1，且
stdout 明确 `35 passed` 与 `29 passed, 1 failed`。V4 exit artifacts 为 identity/replay/Ruff/mypy/cold 全部 0、scope=1；
该 scope STOP 没有被合入产品绿测。V5 五个 exit 均为 0，status 文件只列出六个 exact6 路径，cached count=0，
diff-check exit=0，temp/cache 目标均 absent，process 文件为 Python=0、affinity_0xF00=0。

### 13.2 组合范围与证据根边界

delivery 的组合范围与 taskbook §14.2 一致且有效：V3 的 identity、完整 unit 与 integration 其余 29 项；V4 的修正 replay
节点、Ruff exact3、mypy production、cold；V5 的 exact6/scope/residue。该组合没有把 V3 唯一失败、V1/V2 carrier STOP 或
V4 scope carrier STOP 洗成全绿，也没有重复或虚构产品阶段。

V3 evidence root `artifacts/agent_runs/m3-r2f-v2-validation3-20260828T121638Z` 存在并包含 taskbook 引用的 summary 与
unit/integration 输出。V1、V2、V4、V5 的对应保留目录与文件也存在，但 taskbook §14 只绑定 V3 的独立 evidence root；
delivery 正确地没有猜测或宣称其他轮次的 root 语义，而仅采用明确列出的 summary/stdout SHA。该保守处理不削弱已引用
证据，也不扩大证据范围。

production/unit 当前 SHA 与冻结值一致；V5 exact6 count=6、cached=0，实际六项正是 production、unit、integration、
taskbook、delivery、review；diff-check exit=0，stderr 仅 LF→CRLF warnings，temp/cache/Python/0xF00 residue 均清零。
本轮只读检查未发现 combined-scope 或 evidence 引用矛盾。

### 13.3 结论与剩余边界

故本轮结论为：

**`EVIDENCE_REVIEW_PASS`（无 P0/P1/P2）**。

结论边界严格限定为该 shared-scientific-config 合同的 Windows engineering validation 组合证据已可采用；不声明 A14
formal scientific config/controlled root、A15 formal G1 release、A17 Windows py312/Qlib、actual successor、真实
Qlib/network、new root、retained resume、acceptance 真实运行、M3 Gate 或 Linux Gate 完成。ignored evidence 不得 stage；
SAFE_COMMIT、merge 与 archive-first retirement 仍由中央流程另行裁定。

本轮只更新本 review 报告；未运行 Python、pytest、Ruff、mypy、cold、Qlib、data/network、root/evidence、stage 或 commit，
且 production、unit、integration、taskbook、delivery 未由本 reviewer 修改。
