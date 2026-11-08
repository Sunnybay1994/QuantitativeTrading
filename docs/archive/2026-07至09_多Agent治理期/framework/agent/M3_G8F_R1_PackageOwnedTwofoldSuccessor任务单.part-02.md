- 现象：VALIDATION7 外部反馈为 unit `15 passed`、focused integration `14 passed / 1 STOP`，stdout trace SHA 为 `a6977c70b7c00f1471d848d1af348ac6d76db4345800ff51df6c147e36296b58`。唯一失败落在 receipt-bytes tamper 反例的测试定位段：测试没有使用首轮结果的 canonical attestation receipt，而是硬编码替代文件名。
- 根因：旧 integration 测试先调用 `_run(request, boundary)` 丢弃 `SuccessorRunResult`，随后自构造 `controlled_output_root/receipts/snapshot/shared-snapshot.json`。该名字不由当前 `first.attestation.receipts` 提供，因而不能证明篡改的是已认证 receipt，也可能在真实 receipt 之外失败或误指向。
- 应遵循规则：必须保留 `first = _run(...)`；从 `first.attestation.receipts` 筛选 `stage == "snapshot"` 且 `fold is None`、`horizon is None`，强制恰有一项并校验其 scope/scope_key/relative path shape；再用 `request.project_root / ref.relative_path` 定位实际文件，校验原始 bytes 的 ref sha 后实施既有 tamper。禁止硬编码替代文件名、自构造 receipt 路径或弱化 `SUCCESSOR_TERMINAL_INVALID` fail-closed 断言。

### 最小复现、新测试与通过条件

- 最小复现：首轮 `_run` 已返回 canonical attestation，但旧测试丢弃 `first`，直接拼接 `shared-snapshot.json`；当 attestation 的 snapshot ref 不是该名字时，tamper 不再绑定已认证 receipt。
- 新测试：integration `test_terminal_rejects_receipt_bytes_and_unknown_tree_entry` 使用 `first.attestation.receipts` 的唯一 snapshot/fold-none/horizon-none ref，断言 `SNAPSHOT` scope、`boundary.snapshot_id` scope_key、`output/stage/receipts/snapshot/*.json` shape 和原始 sha，再通过 `request.project_root / snapshot_ref.relative_path` 写入 bytes drift；随后仍断言 `verify_terminal_attestation` 返回 `SUCCESSOR_TERMINAL_INVALID`。unknown-tree 分支保持原有独立覆盖。
- 通过条件：篡改目标必为当前 attestation 的唯一 canonical snapshot receipt；合法原始 receipt 可被定位，任意 bytes drift 仍 fail closed 为 `SUCCESSOR_TERMINAL_INVALID`，且不引入硬编码文件名或第二套 receipt 解析规则。

### REWORK10 验证边界

VALIDATION7 的 unit/integration 结果与 stdout SHA 是外部提供证据；本轮未运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python。未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。修复后的 integration 结果待后续授权验证，不能将本轮静态交付表述为 Gate 通过。

## 16. REWORK11 VALIDATION8 dependency typing 与 canonical bytes 闭环

本轮只修正生产模块的静态 typing 表达，并补 unit 对抗测试；不改变 runtime 行为、字段顺序、receipt/terminal schema、canonical bytes 排序或编码规则。integration test 与独立初验报告保持只读。

### 现象、根因与类型规则

- 现象：VALIDATION8 外部证据为 focused unit `15 passed`、focused integration `15 passed`、Ruff exact3 PASS；mypy 首次执行 STOP，stdout SHA 为 `ee7073f019c91a27530390b3f6da8e52a44733c7f93e62d9515b6fd0c5bfbf5b`。报告归因 13 个类型错误：必需 dependency callback 被注解为 Optional、局部 `expected`/`digest` 重名及 `asdict(object)` 未形成安全的 dataclass typing 收窄。
- 根因：`SuccessorProductionDependencies` 的 13 个必需 callable 字段虽然由 `__post_init__`/adapter 做 runtime fail-closed 检查，却在静态类型层保留 `| None`；同一函数的不同语义局部变量名又触发 mypy 重定义/类型冲突；`hasattr` 分支没有让 `asdict` overload 得到 dataclass 类型。
- 应遵循的类型规则：13 个字段使用原有 Callable Protocol 类型、去除 Optional，字段顺序不变；`__post_init__` 与 adapter 的全部 callable/StageRunner identity 检查、None 拒绝与构造行为保留。`expected` 只等价改名为 `expected_work_key`/`expected_receipts`，tree entry 的 `digest` 只等价改名为 `entry_digest`。canonical bytes 只允许最窄桥接 `asdict(cast(Any, value))`，不得 `type: ignore`，且必须保持 `sort_keys`、紧凑 separators、ASCII、`allow_nan=False` 和 schema/bytes 完全不变。

### 最小复现、新测试与通过条件

- 最小复现：对 `SuccessorProductionDependencies` 任一必需字段传 `None`，构造仍必须返回 `SUCCESSOR_INPUT_INVALID`；对同一 `_validate_fold_execution` 同时使用 work-key expected 与 receipt-shape expected，或在 controlled-tree digest 语义中复用 `digest`，会触发静态重定义；对 dataclass 值调用 `_canonical_bytes` 时，直接 `asdict(value)` 无法满足静态 overload。
- 保留/新增测试：保留 `test_production_dependencies_fail_closed_when_any_boundary_is_missing`；新增 `test_each_production_dependency_none_fails_closed`，逐项验证 13 个字段的 None 反例；新增 `test_canonical_bytes_dataclass_matches_asdict_form`，断言 dataclass 与其 `asdict` mapping 的 canonical bytes 完全相等。
- 通过条件：13 个字段在静态层为非 Optional callable，runtime 仍拒绝任一 None/非 callable/错误 StageRunner identity；三个局部重命名不改变值、排序或输出；canonical bytes 等价测试通过且无 `type: ignore` typing 绕过，receipt/terminal schema 与 bytes 不漂移。

### REWORK11 验证边界

VALIDATION8 的 unit/integration/Ruff 与 mypy stdout SHA 是外部提供的失败前证据；本轮只做 STATIC_ONLY 编辑，未运行 focused unit/integration、pytest、Ruff、mypy、cold import、CPU 或任何 Python。未运行 actual worker、retained、真实 acceptance、Linux、network；未提交、未 stage；独立初验报告保持只读。修复后的 post-fix 检查待后续授权，不能将本轮静态交付表述为 Gate 通过。
