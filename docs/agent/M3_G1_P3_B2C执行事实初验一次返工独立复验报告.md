# M3 G1-P3 B2C 执行事实：初验一次返工独立复验报告

日期：2026-07-14  
角色：**外部独立复验 Agent**（从未参与 M3 G1-P3 B2C 实现或本轮返工）  
实际模型标识：`cursor-grok-4.5-high`  
返工任务：[`M3_G1_P3_B2C执行事实初验一次返工任务单.md`](M3_G1_P3_B2C执行事实初验一次返工任务单.md)  
更新后任务书：[`M3_G1_P3_B2C执行事实外部闭环任务单.md`](M3_G1_P3_B2C执行事实外部闭环任务单.md)  
原交付：[`M3_G1_P3_B2C执行事实交付报告.md`](M3_G1_P3_B2C执行事实交付报告.md)  
不通过初验：[`M3_G1_P3_B2C执行事实独立初验报告.md`](M3_G1_P3_B2C执行事实独立初验报告.md)  
返工交付：[`M3_G1_P3_B2C执行事实初验一次返工交付报告.md`](M3_G1_P3_B2C执行事实初验一次返工交付报告.md)

## 结论

**独立复验通过（P1-1 返工可交主 Agent 终验）。**

本报告不宣称主验 / P3 / B2 / G1 / 任一 Gate 完成。唯一仓库写入为本报告；未修改生产代码、Schema、配置或实现者测试；未联网、未读 token、未访问 `_old/`。临时探针仅位于 WSL `/tmp`（及 Windows 中转临时文件），验收后已清理。

---

## 1. 范围与只读边界

| 核对项 | 结果 |
|---|---|
| 返工仅触及允许文件（`m3_execution_facts.py` / `schemas.py` / 相关单测 / 返工报告） | 与返工交付一致；未改 `__init__.py`、B2A/B2B/P2 生产代码、路线图勾选 |
| 冻结列 `event_ids_json` 位于 `event_count` 与 `event_ids_sha256` 之间 | Schema 列序 `8→9→10` 独立确认 |
| 公开函数签名未变 | `CorporateActionReconciliationResult` / `verify_corporate_action_reconciliation_result` 签名与任务书 §4 一致 |
| 构造与公开 verifier 共用验证体 | `__post_init__` 与 `verify_*` 均调用 `_verify_reconciliation_result_body` → `_assert_event_ids_identity` |

---

## 2. 源码证据：规范解析与 count/hash 重算

独立阅读 `src/quant/data/m3_execution_facts.py` 与 `schemas.py`，不依赖交付报告作为唯一证明：

1. **生产写入**：NO_EVENT 行写 `event_ids_json=_event_ids_json([])`（精确 `[]`）与空集 hash；MATCHED 行对排序后的 `event_id` 写规范 JSON 与 `_event_set_sha256`。
2. **解析门禁** `_parse_event_ids_json`：
   - 必须为 `str`；`json.loads` 后必须为 `list`；
   - 元素必须为小写 64 hex（`_HEX64.fullmatch`）；
   - 拒绝重复、非升序；
   - **要求** `_canonical_json(ids) == value`（固定 `ensure_ascii=False, separators=(",", ":"), allow_nan=False`），从而拒绝空白/转义/非规范序列化。
3. **重算** `_assert_event_ids_identity`：`event_count == len(parsed_ids)`；`event_ids_sha256 == SHA256(["m3-g1-corporate-action-event-set-v1", *parsed_ids])`；异常统一为 `G1_CORPORATE_ACTION_RECONCILIATION_INVALID` 且 `from None`。
4. **Schema**：`CorporateActionReconciliationSchema` 新增必需 `event_ids_json: str`；不把整表 digest 当作 event-set 自证。

身份闭包边界（任务书 §10）：自包含 verifier 证明「行内 json↔count↔hash 一致」；**全套自洽来源替换**仍须由 B4 从冻结输入重执行关闭（见对抗 ADV_R5）。

---

## 3. 原初验阻断项 C12a / 任务单最小攻击复现

独立 fixture：`000001.SZ` + `2024-05-06..10`（非实现者 `600000.SH` / `2026-01`）。

对合法 MATCHED 行仅将 `event_ids_sha256` 改为 `"c"*64`，再用 `clean_table_content_sha256(table_name="corporate_action_reconciliation", ...)` 同步外层 digest：

| 路径 | 结果 |
|---|---|
| `CorporateActionReconciliationResult(...)` 构造 | **拒绝** `G1_CORPORATE_ACTION_RECONCILIATION_INVALID`；`__cause__ is None` |
| `__new__` 绕过构造后 `verify_corporate_action_reconciliation_result` | **拒绝** 同上 |

原初验 P1-1 现象已关闭。同步验证：只改 `event_ids_json→[]`、只改 `event_count`、NO_EVENT 只改 hash，并同步 digest 后，构造与公开 verify **均拒绝**。

---

## 4. 实现者未使用的对抗变体（≥2）

对照实现者 `test_p1_1_*`（前导/尾随空白、大写 hex、逆序、重复、`{}`/`null`/`[1]`/`[[]]` 等），本复验新增：

| ID | 变体（实现者未用） | 构造 | 公开 verify |
|---|---|---|---|
| **ADV_R1** | 双 ID 数组逗号后空格 `["id0", "id1"]`（非规范 separators） | 拒绝 | 拒绝 |
| **ADV_R1b** | 同上，并按 `json.loads` 结果同步 hash/count/digest | 拒绝 | 拒绝 |
| **ADV_R2** | `\u0061`×64 转义；`json.loads` 可得 `a*64` 且 hash 自洽，但文本非规范 | 拒绝 | 拒绝 |
| ADV_R3 | NO_EVENT：`\ufeff[]` BOM 前缀 | 拒绝 | 拒绝 |
| ADV_R4 | `""` / `[true]` / 63 hex / tab 分隔 | 拒绝 | 拒绝 |
| ADV_R6 | JSON 含 `/home/secret/token=LEAKED_MARKER...`；`str/repr/traceback` 无泄露 | 拒绝 | 拒绝 |

**ADV_R5（B4 边界，非失败）**：将 MATCHED 的 `event_ids_json/count/hash` 换成另一合法 ID 集合并同步整表 digest 后，自包含构造与 verify **接受**。这与任务书「同步替换 json/count/hash/digest 的全套自洽来源替换留给 B4」一致；**不得**据此宣称来源闭包完成。

---

## 5. 身份闭包相关回归（原初验 C1–C13 子集）

本轮返工只改 reconciliation event-set 证据；复验聚焦身份闭包相关不变量，而非复述整份 C1–C11 业务对抗：

| 原项 | 身份相关核对 | 本轮结果 |
|---|---|---|
| C12a | 只改 `event_ids_sha256` + 同步 digest | **PASS（现拒绝）** |
| C12 | 外层 hash-only 漂移 | PASS（拒绝） |
| C12 | cash 单字段篡改 + 同步 digest | PASS（拒绝） |
| C12 | dtype coercion 写回后 frame 与 digest 一致 | PASS（`event_count`→Int64 写回） |
| C7/双事件 | JSON 升序、count=2、hash 重算；输入行序不变 JSON/hash/digest | PASS |
| NO_EVENT | `event_ids_json=="[]"`、count=0、空集规范 hash | PASS |
| C13 | 失败码稳定；恶意路径/token 不进 `str/repr/traceback`；`__cause__ is None` | PASS |

独立探针合计 **34/34 PASS**（含上述对抗与生产不变量）。

---

## 6. WSL 工具链验证

全部经 `wsl.exe` → `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` → `/home/mabw/miniforge3/bin/conda run -n base`；禁止 Windows Python/conda。

| 命令 | 结果 |
|---|---|
| 定向 pytest（execution_facts/schemas/config/backfill/mappers/membership/identity） | **319 passed** |
| 全量 `python -m pytest -q` | **609 passed**，5451 条既有 deprecation warnings |
| `python -m ruff check src tests` | **All checks passed** |
| `python -m mypy src` | **76 source files，0 issues** |
| 独立对抗探针 `/tmp/b2c_p1_1_reverify.py` | **34/34 PASS**（已清理） |

绿测与独立对抗一致指向 P1-1 已关闭；绿测本身不代替上述身份反例。

---

## 7. Import 隔离、联网与脱敏

- `m3_execution_facts.py` 静态检索未见 `requests` / `quant.research` / `qlib` / 网络客户端 / 配置路径读写；
- 本复验未联网、未读 token/ignored 凭据、未写 raw/clean；
- 对抗 ADV_R6：恶意 `token=` / 绝对路径不进入公开错误消息。

---

## 8. 交付声明

**独立复验通过。** P1-1（reconciliation event-set 身份证据不完备）已按冻结 `event_ids_json` 设计关闭，可交主 Agent 执行第 4 步最终验收。

**不得宣称主验 / P3 / B2 / G1 / 任一 Gate 通过。**  
全套内部自洽来源替换仍须由后续 B4 从冻结输入重执行关闭。
