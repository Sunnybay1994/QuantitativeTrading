# M3 G1-P3 B2C 执行事实：初验一次返工交付报告

日期：2026-07-14  
角色：外部实现 Agent（原实现者返工）  
实际模型标识：`cursor-grok-4.5-high`  
返工任务：[`M3_G1_P3_B2C执行事实初验一次返工任务单.md`](M3_G1_P3_B2C执行事实初验一次返工任务单.md)  
不通过初验：[`M3_G1_P3_B2C执行事实独立初验报告.md`](M3_G1_P3_B2C执行事实独立初验报告.md)  
状态：**返工已交，待独立复验**（不宣称 P3/B2/G1/Gate 通过）

## 1. 返工范围

只关闭阻断项 **P1-1**（reconciliation event-set 身份闭包）。未启动 P4；未修改 B2A/B2B/P2
已验收实现；未勾选路线图/Gate；未联网、未读 token、未访问 `_old/`。

允许并已修改的文件：

| 文件 | 变更 |
|---|---|
| `src/quant/domain/schemas.py` | `CorporateActionReconciliationSchema` 在 `event_count` 与 `event_ids_sha256` 之间新增 `event_ids_json` |
| `src/quant/data/m3_execution_facts.py` | 生产行写入 `event_ids_json`；verifier 从规范 JSON 重算 count/hash |
| `tests/unit/test_m3_execution_facts.py` | 新增 P1-1 独立测试矩阵 |
| `tests/unit/test_schemas.py` | reconciliation fixture 补 `event_ids_json` |
| `docs/M3_G1_P3_B2C执行事实初验一次返工交付报告.md` | 本报告 |

未改 `__init__.py`（导出签名未变）。

## 2. 现象—根因—修复映射

| 项 | 内容 |
|---|---|
| 现象 | 只改 `event_ids_sha256` 并同步整表 digest 后，构造与公开 verify 仍通过 |
| 根因 | 结果只存 count/hash，自包含 verifier 无法从独立证据重算 event-set hash |
| 规则 | identity closure 不得依赖待验证字段自证；须保留最小规范证据并重算派生值 |
| 修复 | 新增必需列 `event_ids_json`（排序去重的小写 64 hex 数组规范 JSON）；构造/verify 严格解析后重算 `event_count` 与 `event_ids_sha256` |

冻结序列化：`json.dumps(ids, ensure_ascii=False, separators=(",", ":"), allow_nan=False)`；空集合精确为
`[]`；hash 仍为 `["m3-g1-corporate-action-event-set-v1", *parsed_ids]`。

## 3. 新增测试与最小攻击复现

新增测试覆盖返工任务单 §4：

1. MATCHED：只改 `event_ids_sha256` 并同步 digest → 构造与公开 verify 均
   `G1_CORPORATE_ACTION_RECONCILIATION_INVALID`
2. MATCHED：只改 `event_ids_json` / 只改 `event_count` 并同步 digest → 均失败
3. NO_EVENT：`event_ids_json == "[]"`、count=0、hash=空事件集规范 hash；hash 漂移失败
4. 双 event：JSON 升序稳定；输入行序变化不改变 JSON/hash/digest
5. 拒绝前导/尾随空白、大写 hex、逆序、重复、对象/null/数字/嵌套数组
6. dtype coercion 写回后公开 frame 与 digest 一致
7. 失败码与 `str/repr/__cause__` 脱敏

最小攻击复现（任务单 §4）：合法 MATCHED 行将 `event_ids_sha256` 改为 `"c"*64` 并
`clean_table_content_sha256(...)` 同步外层 digest → **现已失败**。

## 4. 验证结果（WSL Miniforge `base`）

全部经 `wsl.exe` → `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` →
`/home/mabw/miniforge3/bin/conda run -n base`。

| 命令 | 结果 |
|---|---|
| 定向 pytest（execution_facts/schemas/config/backfill/mappers/membership/identity） | **319 passed** |
| 全量 `python -m pytest -q` | **609 passed**，5451 条既有 deprecation warnings |
| `python -m ruff check src tests` | **All checks passed** |
| `python -m mypy src` | **76 source files，0 issues** |

## 5. 交付声明

P1-1 按冻结最小设计已修复并自测通过。

**待未参与本轮返工的全新外部 Agent（`cursor-grok-4.5-high`）独立复验。**

**不宣称 P3 / B2 / G1 / 任一 Gate 通过。**
