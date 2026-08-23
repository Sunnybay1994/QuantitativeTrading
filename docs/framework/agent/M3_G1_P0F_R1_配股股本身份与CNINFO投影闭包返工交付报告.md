# M3 G1 P0F-R1：配股股本身份与 CNINFO 投影闭包返工交付报告

状态：**外部实现自测完成**（不等于独立初验 / 主验 / Gate）

日期：2026-07-28（Asia/Shanghai）
实现基线：`022d3ef`（Freeze G1 P0F R1 identity closure）
实现模型：`cursor-grok-4.5-high`（外部实现全新会话）
任务书：[`M3_G1_P0F_R1_配股股本身份与CNINFO投影闭包返工任务单.md`](M3_G1_P0F_R1_配股股本身份与CNINFO投影闭包返工任务单.md)

## 1. 现象—根因—规则—最小复现—新增测试—通过条件

### R1-P1：股本替换可碰撞 rights 身份

- **现象**：仅 `F017N/F024N/F025N` 不同的合法配股记录曾生成相同 `event_id` / `candidate_id`。
- **根因**：rights ID v1 与 ledger/evidence 未持久化三项股本。
- **规则**：经济事件身份必须绑定全部官方经济参数；同步重算 digest 后仍不能替换股本。
- **最小复现**：固定 SUBID/日期/price/ratio，`(100,1000,1100)` vs `(200,1000,1200)`。
- **新增测试**：
  - `test_p0f_r1_rights_capital_identity_collision_and_tamper`
  - `test_p0f_r1_dividend_capital_fields_null`
  - Schema 分支扩展（dividend 三项 null；rights 有限正数且 `post-pre≈actual`）
- **通过条件**：ledger/evidence 含三项股本；ID 标签升级为 rights-event/candidate-v2 并按固定顺序追加 `_float_token`；selection `...cninfo_rights_capital_v4`、mapper v5、schema v3、manifest v5、table v3；篡改股本并重算 digest 后 verify 拒绝。

### R1-P2：CNINFO projection 可裁剪列集合

- **现象**：`G1ReceiptProjectionV1` / manifest 可接受 `columns=("SECCODE",)` 的 CNINFO receipt。
- **根因**：projection 未按 source/endpoint 锁定官方字段 tuple。
- **规则**：发布身份必须绑定完整原始证据投影。
- **最小复现**：`source=cninfo, endpoint=stock_allotment, columns=("SECCODE",)`。
- **新增测试**：`test_p0f_r1_cninfo_projection_columns_exact_lock`（少列/多列/乱序拒绝；精确 57 列接受；非 CNINFO 不回退；磁盘 v5 解析同约束）；manifest v5/mapper v5/table v3 与 v4/current 混搭拒绝。
- **通过条件**：内存构造与磁盘 JSON 解析均 `columns == CNINFO_STOCK_ALLOTMENT_FIELDS`（import SSOT，不复制列表）；current writer 只生成 manifest v5。

## 2. 改动文件（白名单）

生产：

- `src/quant/data/m3_execution_facts.py`
- `src/quant/domain/schemas.py`
- `src/quant/data/m3_g1_candidate.py`
- `src/quant/research/m3/g1_planning.py`
- `src/quant/data/m3_release.py`
- `src/quant/data/connectors/cninfo.py`（仅 EOF 提交卫生）

测试：

- `tests/unit/test_m3_execution_facts.py`
- `tests/unit/test_schemas.py`
- `tests/unit/test_m3_g1_candidate.py`
- `tests/unit/test_m3_g1_planning.py`
- `tests/unit/test_m3_g1_release.py`
- `tests/unit/test_m3_reference.py`（版本字面量）

文档：本报告（唯一新文档）

未修改 workflow / CLI / backfill / connector 行为 / 配置 / 其他文档。

## 3. 验证命令与退出码

环境：Windows `D:\Miniforge3\python.exe`；`PYTHONPATH=src;.`；零网络。

| 命令 | 退出码 |
|---|---|
| `pytest -q tests/unit/test_schemas.py` + R1 capital/rights 定向子集 | 0（含 schema 全文件） |
| `pytest ... test_p0f_r1_rights_capital_identity_collision_and_tamper` / `dividend_capital_fields_null` | 0 |
| `pytest ... -k "rights or p0e or no_event or dividend_and_rights or capital or version_constants"`（execution_facts） | 0（27 passed） |
| `pytest -q tests/unit/test_m3_g1_planning.py` | 0（17 passed, 1 skipped） |
| `pytest ... test_b1b_manifest_*` / `test_b1b_r4_*` / `test_p0f_r1_cninfo_projection_*` | 0（3 passed） |
| `pytest ... test_p0d_versions_and_scoped_projection_bounds` | 0 |
| `pytest ... test_p0e_reconciliation_version_propagates_in_build_spec` + package exports | 0 |
| 直接探针：mapper v5 / schema v3 / selection capital_v4 | 0 |
| `ruff check` 白名单生产+测试 | 0 |
| `mypy` 改动生产 6 文件 | 0 |
| `git diff --check 022d3ef -- <白名单>` | 0 |

## 4. 明确未运行

- 正式 637 证券 / 13-request CNINFO 网络抓取
- `test_m3_g1_candidate` / `test_m3_g1_release` / `test_m3_reference` 全文件长 fixture（已知超慢；以定向用例 + 直接探针代替，**不宣称全文件绿**）
- five_stage / self_proof / Windows publish / VerifiedG1Release 终验
- WSL Miniforge base Gate / Linux flock 平台终验
- 独立外部初验与 Codex 主验

## 5. 残留风险

- 历史磁盘 manifest 若仍带截断 CNINFO columns，现因 projection 合同加固而无法再解析（符合 P2 通过条件）。
- Artifact entry 允许历史 `table_schema_version=v2` 读取；current writer/v5 强制 `v3`。
- 自测通过 ≠ 独立初验 PASS ≠ G1 Gate。

## 6. 结论

R1-P1 / R1-P2 已在白名单内按冻结字段、ID v2、版本传播与 57 列精确约束实现，并完成最小确定零网络自测。请另一全新外部会话独立复验后再进入主验。
