# M3 G1-P3 B2C 执行事实：初验一次返工任务单

日期：2026-07-14  
状态：主 Agent 已复核并冻结返工设计；交回原实现 Agent，完成后须由未参与返工的全新外部 Agent 独立复验  
原任务书：[`M3_G1_P3_B2C执行事实外部闭环任务单.md`](M3_G1_P3_B2C执行事实外部闭环任务单.md)  
原交付：[`M3_G1_P3_B2C执行事实交付报告.md`](M3_G1_P3_B2C执行事实交付报告.md)  
不通过报告：[`M3_G1_P3_B2C执行事实独立初验报告.md`](M3_G1_P3_B2C执行事实独立初验报告.md)

## 1. 返工结论与边界

只修复阻断项 P1-1，不启动 P4，不修改 B2A/B2B/P2 已验收实现，不勾选 B2/P3/G1/Gate。允许修改：

- `src/quant/data/m3_execution_facts.py`；
- `src/quant/domain/schemas.py`；
- `tests/unit/test_m3_execution_facts.py`、`tests/unit/test_schemas.py`；
- 本轮返工交付报告。

若包根导出不因本修订变化，不修改 `__init__.py`。不得联网、读取 token、访问 `_old/` 或写 raw/clean 数据。

## 2. 现象、根因与被破坏的不变量

### 现象

在合法 MATCHED reconciliation 行中，只把 `event_ids_sha256` 换成另一合法 64 hex，并同步重算整表
`evidence_sha256` 后，`CorporateActionReconciliationResult(...)` 构造与
`verify_corporate_action_reconciliation_result(...)` 都错误地通过。

### 根因

结果行只保存 `event_count` 和 `event_ids_sha256`，没有保存可供自包含 verifier 独立重算 event-set hash 的事件
ID 集合；`_assert_reconciliation_row_formulas` 也没有校验该 hash。整表 digest 只能证明“hash 字段属于这张表”，
不能证明“hash 字段由声称的事件集合计算而来”。

### 应遵循规则

identity closure 不能依赖待验证字段自证。自包含 result 必须保留计算派生身份所需的最小规范证据，并从该证据
重算派生值；从冻结原始输入证明整个 result 没被替换，仍由后续 B4 重执行关闭。不得把两种信任边界混为一谈。

## 3. 已冻结的最小设计

按已同步更新的原任务书 §8.3、§10 执行：

1. 在 `CorporateActionReconciliationSchema` 的 `event_count` 与 `event_ids_sha256` 之间新增必需列
   `event_ids_json: Utf8`；其他列和公开函数签名不变。
2. `event_ids_json` 精确保存排序、去重后的 event ID 数组，不含 namespace；每个 ID 必须为小写 64 hex。
3. 规范序列化固定为
   `json.dumps(ids, ensure_ascii=False, separators=(",", ":"), allow_nan=False)`；空集合精确为 `[]`。
4. `event_count == len(parsed_ids)`；`event_ids_sha256` 从
   `["m3-g1-corporate-action-event-set-v1", *parsed_ids]` 的同一规范 JSON 独立重算。
5. 生产 reconciliation 生成 NO_EVENT 与所有 MATCHED 行时都写入该列。
6. `CorporateActionReconciliationResult.__post_init__` 与公开 verifier 共用的验证体必须严格解析规范文本并重算
   count/hash；非数组、非字符串元素、大写/非 64 hex、重复、非升序、非规范空白/转义均拒绝为稳定
   `G1_CORPORATE_ACTION_RECONCILIATION_INVALID`，异常 `__cause__ is None`，不得泄露输入内容或路径。
7. 不增加第二套 event-set hash 算法；复用现有 canonical JSON/hash helper。

不要新增 result sidecar、caller 参数或另一张 event-members 表；本轮选择单列规范证据是为了保持公开 Result API 与
B4 重执行边界不变。

## 4. 最小复现与新增测试

必须新增独立测试，不能只改旧 fixture：

1. MATCHED：只改 `event_ids_sha256` 并同步整表 digest，构造和公开 verifier 均失败。
2. MATCHED：只改 `event_ids_json`、只改 `event_count`，分别同步整表 digest，均失败。
3. NO_EVENT：`event_ids_json == "[]"`、count=0、hash 等于空事件集规范 hash；任一漂移并同步 digest 仍失败。
4. 双 event：JSON 内 ID 排序稳定，count=2，hash 重算一致；输入顺序变化不改变 JSON/hash/digest。
5. 拒绝 ` ["..."]`、含空格的 JSON、大写 hex、重复 ID、逆序 ID、对象/数字/null/嵌套数组，以及同步后的整表 digest。
6. 保留 dtype coercion 写回语义；合法 Utf8 frame 构造后 result 暴露的 frame 与 digest 一致。
7. 失败码、`str/repr/__cause__/traceback` 脱敏回归。

最小攻击复现：从合法 MATCHED result 复制 evidence，仅将 `event_ids_sha256` 改为 `"c" * 64`，再用
`clean_table_content_sha256(table_name="corporate_action_reconciliation", frame=evidence)` 同步外层 digest；返工后构造
和 verify 都必须失败。

## 5. 验证与交付条件

全部命令只允许通过 Windows `wsl.exe` 进入项目，再用
`/home/mabw/miniforge3/bin/conda run -n base` 执行；禁止 Windows Python/conda。至少运行：

1. P3 定向测试及其上游回归矩阵；
2. 全量 `python -m pytest -q`；
3. `python -m ruff check src tests`；
4. `python -m mypy src`。

生成 `docs/M3_G1_P3_B2C执行事实初验一次返工交付报告.md`，逐项映射本任务单并报告真实命令/结果。只可声明
“返工已交，待独立复验”，不得声明 P3/B2/G1/Gate 通过。实现完成后停止，必须换一个全新
`cursor-grok-4.5-high` 会话进行只读复验。
