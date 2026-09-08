# M3 G1 P0F-R1：配股股本身份与 CNINFO 投影闭包返工任务单

状态：**冻结，待外部实现 → 外部独立复验**

日期：2026-07-28（Asia/Shanghai）  
实现基线：`48ce457`（P0F 独立初验 FAIL 报告）  
上游实现：`db3b944`  
上游初验：[`M3_G1_P0F_CNINFO配股事件全链独立初验报告.md`](M3_G1_P0F_CNINFO配股事件全链独立初验报告.md)

## 1. 目标与系统不变量

只修复 P0F 初验确认的两个身份闭包缺口和提交卫生：

1. 配股 `event_id`、`candidate_id`、ledger、evidence 必须绑定 CNINFO 的实际配售股数、配售前总股本、配售后总股本；
2. 任意 `source=cninfo`、`endpoint=stock_allotment` 的 receipt projection 必须精确绑定官方 57 列；
3. 身份语义升级后，旧 selection / mapper / schema / manifest / table schema 不能冒充当前产物；
4. dividend、P0E、小额分红精度、factor 通式、no-event fail-closed、637→13、零网络 status/HISTORY 行为不得改变。

不扩展到其他公司行动、G2、正式网络抓取、性能重构或 config TOML 新旋钮。

## 2. 现象—根因—规则—最小复现—通过条件

### R1-P1：股本替换可碰撞 rights 身份

- **现象**：两条记录仅 `F017N/F024N/F025N` 不同且各自满足 `post-pre==actual`，会生成相同 `event_id` / `candidate_id`。
- **根因**：rights ID v1 只绑定 SUBID、日期、price、ratio；ledger/evidence 丢弃三项股本。
- **规则**：经济事件身份必须绑定所有影响事件真实性的官方经济参数；攻击者同步重算低层 digest 后仍不能替换。
- **最小复现**：固定 symbol/SUBID/record/ex/price/ratio，以 `(100,1000,1100)` 和 `(200,1000,1200)` 构造两条合法记录。
- **新增测试**：
  - 两组记录的 `event_id` 和 `candidate_id` 必须不同；
  - 任意修改 actual/pre/post 并重算 clean/result digest，selection verify、candidate verify/audit、release/manifest verify 至少在相应边界稳定拒绝；
  - dividend 行三字段必须为空；rights 行三字段必须有限、正数，且 `post-pre` 与 `actual` 按现有严格数值语义一致。
- **通过条件**：ledger/evidence、Schema、哈希重建和所有验证路径完整绑定三项股本；旧 ID 版本拒绝。

### R1-P2：CNINFO projection 可裁剪列集合

- **现象**：`G1ReceiptProjectionV1` / manifest v4 可接受 `columns=("SECCODE",)` 的 CNINFO receipt。
- **根因**：projection 只验证字符串 tuple，未按 source/endpoint 锁定官方字段集合。
- **规则**：发布身份必须绑定完整原始证据投影，不能只绑定版本字符串或 source 存在性。
- **最小复现**：构造 `source=cninfo, endpoint=stock_allotment, columns=("SECCODE",)` 的 projection / manifest。
- **新增测试**：
  - CNINFO columns 少列、多列、乱序均拒绝；
  - 精确 `CNINFO_STOCK_ALLOTMENT_FIELDS` 接受；
  - Tushare/Baostock 等既有 projection 行为不变；
  - 磁盘 JSON v5 解析与内存构造均执行同一约束。
- **通过条件**：生产写出和只读复验都强制 57 列精确有序 tuple；旧 manifest v4 只作为历史格式读取，不得冒充当前 v5。

## 3. 冻结字段与数值语义

在 `CorporateActionLedgerSchema` 与 `CorporateActionSelectionEvidenceSchema` 增加：

- `rights_actual_shares: float | null`
- `rights_pre_shares: float | null`
- `rights_post_shares: float | null`

语义：

- dividend：三字段必须全部 `null`；
- rights：三字段必须 finite 且 `>0`；
- rights：`rights_post_shares > rights_pre_shares`；
- rights：`rights_post_shares - rights_pre_shares` 与 `rights_actual_shares` 使用当前 CNINFO selection 已采用的严格 `math.isclose(rel_tol=1e-9, abs_tol=1e-6)` 一致；
- 不改变 `rights_ratio=F004N/10`、价格、日期或 factor 通式。

rights ID：

- `_rights_event_id_sha256` 标签升级为 `m3-g1-corporate-action-rights-event-v2`；
- `_rights_candidate_id_sha256` 标签升级为 `m3-g1-corporate-action-rights-candidate-v2`；
- 两者都按固定顺序追加三项股本的 `_float_token`；
- 任何 verify/rebuild 路径必须使用相同字段和顺序。

## 4. 冻结版本传播

当前产物版本升级为：

| 合同 | P0F | P0F-R1 |
|---|---|---|
| corporate action selection | `...cninfo_rights_v3` | `...cninfo_rights_capital_v4` |
| mapper | `m3-g1-tushare-mapper-v4` | `m3-g1-tushare-mapper-v5` |
| planning schema | `m3-g1-schema-v2` | `m3-g1-schema-v3` |
| manifest | `m3-g1-manifest-v4` | `m3-g1-manifest-v5` |
| manifest mapper | `m3-g1-tushare-mapper-v4` | `m3-g1-tushare-mapper-v5` |
| table schema | `v2` | `v3` |

约束：

- reconciliation v5、request plan v2、derived history plan v2 不变；
- manifest v1-v4 可保持严格历史解析，但 current writer/prepare/publish 只能生成 v5；
- v5 必须要求至少一个完整 57 列 CNINFO receipt，并绑定 mapper v5/table v3；
- build spec、planning、candidate、release、tests 中所有受影响字面量同步升级；
- 旧 v4/current-version 混搭必须 fail closed。

## 5. 实现约束

- `G1ReceiptProjectionV1` 对 CNINFO 做 source/endpoint/columns 联合约束；不能把通用 projection 改成只支持 CNINFO。
- 可以从 `quant.data.connectors.cninfo` import 官方字段 tuple；不得复制 57 字段第二份列表。
- 三项股本必须进入 ledger/evidence 的 canonical table content digest，因此不另建旁路摘要。
- 不硬编码 000661、SUBID、日期、价格、比例或股本。
- 不放宽任何容差；不改变 no-event、P0E supported_ratio 或同日 dividend+rights 顺序语义。
- 清理 `src/quant/data/connectors/cninfo.py` EOF 多余空行；交付报告不得留下 `git diff --check` 问题。
- 默认测试零网络；禁止正式 637 证券 / 13-request 抓取。

## 6. 文件白名单

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
- `tests/unit/test_m3_reference.py`（仅版本/投影传播）

文档：

- 唯一新交付报告：`docs/framework/agent/M3_G1_P0F_R1_配股股本身份与CNINFO投影闭包返工交付报告.md`

禁止修改 workflow、CLI、backfill、connector 行为、配置和其他文档。若真实接口要求白名单外生产文件，停止扩大并在报告给出证据。

## 7. 必须验证

优先使用最小、确定、零网络用例，避免机械运行已知超慢大 fixture：

1. 新增股本碰撞/篡改、Schema 分支、CNINFO projection 57 列、v4→v5 降级测试；
2. rights + P0E + no-event + 同日 dividend/rights 定向回归；
3. planning / release 的版本与最小 b1b 测试；
4. 对改动生产文件与测试运行 Ruff；
5. 对改动生产文件运行 mypy；
6. `git diff --check 48ce457 HEAD` 必须退出码 0。

若 candidate/release 大 fixture 超过合理反馈窗口，改用直接函数/最小 manifest 探针并如实记录，不得宣称全文件绿。

## 8. 交付与结论边界

外部实现者提交白名单代码、测试与唯一交付报告；自测通过不等于独立初验。随后必须由另一全新外部会话复验 P1/P2 最小复现及旧版本降级，初验 PASS 后才进入 Codex 主验和正式 CNINFO HISTORY。

