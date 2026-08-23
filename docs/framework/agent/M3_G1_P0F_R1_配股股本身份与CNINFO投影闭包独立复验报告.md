# M3 G1 P0F-R1：配股股本身份与 CNINFO 投影闭包独立复验报告

状态：**PASS**（不等于主验 / G1 Gate / Windows publish / Linux Gate）

日期：2026-07-28（Asia/Shanghai）  
审查对象：实现提交 `f943e41`（相对冻结基线 `022d3ef`）；上一轮初验 FAIL `48ce457`  
审查模型：`cursor-grok-4.5-high`（外部独立复验全新会话；与 R1 实现者不同）  
角色：生产代码 / 配置 / 实现者测试 / 实现交付报告全部只读；唯一写入本报告

冻结合同：
- [`M3_G1_P0F_R1_配股股本身份与CNINFO投影闭包返工任务单.md`](M3_G1_P0F_R1_配股股本身份与CNINFO投影闭包返工任务单.md)
- 实现交付：[`M3_G1_P0F_R1_配股股本身份与CNINFO投影闭包返工交付报告.md`](M3_G1_P0F_R1_配股股本身份与CNINFO投影闭包返工交付报告.md)
- 上游初验 FAIL：[`M3_G1_P0F_CNINFO配股事件全链独立初验报告.md`](M3_G1_P0F_CNINFO配股事件全链独立初验报告.md)

## 1. 审查范围与方法

- `git diff --stat` / 语义 diff / `git diff --check 022d3ef f943e41`（退出码 0）
- 提交范围严格白名单：6 生产 + 6 测试 + 1 交付报告；未见白名单外生产改动
- 合同逐项独立重放；补充实现者未覆盖的对抗性反例（分别篡改 pre/post、一致股本替换保留旧 ID、manifest v5 无 CNINFO / table v2、BuildSpec 旧 selection/mapper）
- 禁止机械重跑 candidate/release 全文件长 fixture；改用最小函数/manifest 探针 + 精确 pytest node id

## 2. 合同逐项证据表

| 合同项 | 独立证据 | 结论 |
|---|---|---|
| R1-P1：`(100,1000,1100)` vs `(200,1000,1200)` event/candidate 不同 | 独立探针：`event_id`/`candidate_id` 均不同；ledger/evidence 三项股本精确对应 | 通过 |
| R1-P1：篡改 actual/pre/post + 重算 digest，selection verify 拒绝 | 独立探针分别篡改三字段；另构造一致股本替换但保留旧 ID → 均 `M3G1ExecutionFactError` | 通过 |
| R1-P1：candidate/release 身份传播闭合 | candidate concat schema 含三项股本且调用 `verify_corporate_action_selection_result`；BuildSpec 拒旧 selection v3 / mapper v4；manifest v5 绑定 mapper v5/table v3/完整 CNINFO 列 | 通过 |
| R1-P1：dividend 三字段全 null；rights finite/正/post>pre/post-pre≈actual；非法 Schema 拒绝 | dividend 探针 null；Schema 拒 null 股本、坏 delta、post≤pre、dividend 带股本 | 通过 |
| R1-P1：rights-event/candidate-v2 重建参数顺序一致；无 v1 旁路 | 重建 ID 与 select 输出一致；源码无 `rights-*-v1` 标签 | 通过 |
| R1-P2：CNINFO 少列/多列/乱序拒绝；精确 57 列接受 | `G1ReceiptProjectionV1` 独立构造；`len(FIELDS)==57` | 通过 |
| R1-P2：non-CNINFO 不回退 | tushare/baostock 截断 columns 仍可构造 | 通过 |
| R1-P2：57 列只 import SSOT | candidate/release 自 `connectors.cninfo` import；无第二份 `("SECCODE","SECNAME"...` 字面量 | 通过 |
| manifest v5/mapper v5/table v3 current 闭合 | `_MANIFEST_SCHEMA=v5`、`_TABLE_SCHEMA_VERSION=v3`；合法 v5 payload 可解析 | 通过 |
| v4/current 混搭、v5 截断 CNINFO、v5 无 CNINFO、v5+table v2 拒绝 | 独立 manifest 探针均拒绝；历史一致 v4 仍可解析 | 通过 |
| selection capital_v4 / mapper v5 / planning schema v3 传播 | 常量探针 + BuildSpec/planning 锁；旧 selection/mapper 拒 | 通过 |
| rights/P0E/no-event/同日 dividend+rights 定向回归 | 精确 pytest node id，退出码 0 | 通过 |
| `git diff --check 022d3ef f943e41` | 退出码 0 | 通过 |
| 提交白名单 | 13 路径均在任务单白名单内 | 通过 |

## 3. 新增对抗性反例（实现者未覆盖或加强）

环境：Windows `D:\Miniforge3\python.exe`；`PYTHONPATH=src;.`；零网络。

| # | 反例 | 结果 |
|---|---|---|
| A1 | 固定 SUBID/日期/price/ratio，股本 `(100,1000,1100)` vs `(200,1000,1200)` | event_id 与 candidate_id 均不同；三项股本精确写入 ledger/evidence |
| A2 | 分别篡改 actual / pre / post 并重算 clean digest | selection verify 均拒绝 |
| A3 | 替换为另一组合法一致股本但保留旧 event/candidate id | selection verify 拒绝（ID 重建失配） |
| A4 | Schema：rights 股本 null / 坏 delta / post≤pre；dividend 非 null 股本 | 均拒绝 |
| A5 | CNINFO projection 少列/多列/乱序；tushare/baostock 短列 | CNINFO 拒；非 CNINFO 接受 |
| A6 | manifest v5 截断 CNINFO columns；v5 无 CNINFO；v5+table v2；v4+mapper v5 | 均拒绝；一致历史 v4 仍解析 |
| A7 | BuildSpec 旧 selection `...implemented_v3` / 旧 mapper v4 | 均 `ValueError` |
| A8 | 重建 `_rights_event_id_sha256` / `_rights_candidate_id_sha256` 与 select 输出比对 | 一致；无 v1 标签残留 |

## 4. 定向验证命令与退出码

| 命令 | 退出码 |
|---|---|
| 独立探针脚本（33 项，含 A1–A8） | 0 |
| `pytest` R1 + rights/P0E/同日顺序 + manifest 锁（14 node ids） | 0 |
| `pytest tests/unit/test_schemas.py`（27） | 0 |
| `pytest` planning version drift + package exports + reference build_spec（3） | 0 |
| `pytest` rights failed/dup/conflict + P0E disguised + candidate exports（5） | 0 |
| `git diff --check 022d3ef f943e41` | 0 |

## 5. 明确未运行

- 正式 637 证券 / 13-request CNINFO 网络抓取
- `test_m3_g1_candidate` / `test_m3_g1_release` / `test_m3_reference` 全文件长 fixture
- five_stage / self_proof / Windows publish / VerifiedG1Release
- WSL Miniforge base Gate / Linux flock 平台终验
- Codex 主验

## 6. 残留风险（不构成 FAIL）

- `G1BuildSpec.__post_init__` 仍不强制 `schema_version==m3-g1-schema-v3`（任意非空字符串可构造）；planning 路径强制 v3，属既有模式，非本轮 P1/P2 回退。
- Artifact entry 允许历史 `table_schema_version=v2` 读取；current writer / manifest v5 强制 v3。
- 独立复验 PASS ≠ 主验 ≠ G1 Gate。

## 7. 最终结论

**PASS**

R1-P1 / R1-P2 最小复现与身份/投影传播闭包均有独立零网络证据；rights/P0E/no-event/同日顺序定向回归未见新回归；提交卫生与白名单清洁。可进入主 Agent 终验。
