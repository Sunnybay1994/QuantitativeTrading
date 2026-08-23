# M3 G1 P0F：CNINFO 配股事件全链独立初验报告

状态：**FAIL**（不等于主验 / G1 Gate / Windows publish / Linux Gate）

日期：2026-07-28（Asia/Shanghai）  
审查对象：实现提交 `db3b944`（相对基线 `d1f944b`）  
审查模型：`cursor-grok-4.5-high`（外部独立初验全新会话；与实现者不同）  
角色：只读生产代码 / 实现者测试 / 交付报告；唯一写入本报告

冻结合同：
- [`M3_G1_P0F_CNINFO配股事件全链返工任务单.md`](M3_G1_P0F_CNINFO配股事件全链返工任务单.md)
- [`20260728_M3_G1_P0F_000661配股真实证据与设计裁定.md`](20260728_M3_G1_P0F_000661配股真实证据与设计裁定.md)
- 实现交付：[`M3_G1_P0F_CNINFO配股事件全链返工交付报告.md`](M3_G1_P0F_CNINFO配股事件全链返工交付报告.md)

## 1. 审查范围与方法

- `git diff --stat` / `git diff -w` / `git diff --check d1f944b db3b944`
- `g1_workflow.py`：全量 diff 大面积行尾重写；`-w` 后真实语义约 `+148/-3`，均落在 CNINFO journal/HISTORY 预算/inspect 闭包，未见无关行为改写
- 合同逐项对照代码与最小证据；补充实现者未覆盖的对抗性反例
- 对实现报告未全绿的 candidate/release/five_stage/self_proof：**禁止机械重跑长 fixture**；改用定向 workflow 测试 + 直接函数探针。candidate 全量 fixture 在本机启动后超过 ~3 分钟仍无输出，已中止，不以“绿测”冒充排除

## 2. 合同逐项证据表

| 合同项 | 证据 | 结论 |
|---|---|---|
| CNINFO 独立 source/endpoint/adapter/request id | `connectors/cninfo.py` + `m3_backfill.CninfoRequestSpec`；探针 `adv5_not_tushare` | 通过 |
| 官方 57 字段精确集合；字段漂移拒绝 | `CNINFO_STOCK_ALLOTMENT_FIELDS`；`test_schema_failures` 丢列拒绝；生产投影 57 列 | 通过（见 §4 P2：manifest/projection 侧未强制 57） |
| resultcode=200 / success / count==total==len(records) | connector 校验；对抗 adv1 截断用例全拒 | 通过 |
| SECCODE 范围、SUBID 唯一、row_limit | connector + selection；既有单测 | 通过 |
| 空响应完整 schema，不冒充截断 | `empty_cninfo_allotment_frame`；截断≠空（adv1） | 通过 |
| 50/批、637→13、顺序稳定、不复制 Tushare 3190 identity | `batch_cninfo_symbol_groups` + `plan_cninfo_rights_requests`；adv5 | 通过 |
| raw-first intent→candidate→receipt、journal 锁/路径 | `execute_cninfo_batch` 镜像 Tushare journal；Windows 反馈环可导入 | 通过（Linux flock 终验未跑） |
| plan/manifest/primary 绑定 CNINFO batch | request plan v2；manifest v4 `any(cninfo)`；v4 primary 使用 tushare+cninfo receipts | 部分通过（见 P2 列完整性） |
| dividend+rights 统一 ledger/evidence | schema 分支 + selection/reconciliation v3/v5 | 通过 |
| 通式 + market reference；000661 形状不硬编码 | `test_rights_market_reference_happy_path` / declared；adv7 | 通过 |
| no-event 大跳 fail closed；P0E `supported_ratio` | `test_rights_same_shape_without_event_fails_closed` 等；adv8 | 通过 |
| status/inspect 零网络；缺 CNINFO receipt → HISTORY incomplete | `_recover_cninfo_batch`；HISTORY 仅 `cninfo_status==complete` 时追加；`test_fresh_inspect_zero_network_zero_write` 等退出码 0 | 通过 |
| 旧 plan/spec/schema/manifest 降级拒绝 | plan v1 拒；v4 无 cninfo 拒；v3+v4 mapper 拒；adv4 | 通过 |
| **event/candidate id 含 action type、SUBID、日期、rights price/ratio、actual/pre/post** | `_rights_event_id_sha256` / `_rights_candidate_id_sha256` **未纳入股本**；adv2 探针证明不同股本同 event_id | **失败（P1）** |
| rights_price/ratio/SUBID 篡改 + 重算 digest 拒绝 | adv2：`verify_corporate_action_selection_result` 拒绝 | 通过 |
| 同日 dividend+rights 顺序不变量 | `test_dividend_and_rights_same_day...` / adv3 | 通过 |
| example.toml / config 白名单 | 仅注释；未声明 `[g1_backfill.cninfo]`；workflow 冻结 `row_limit=5000` | 通过（正式 TOML 旋钮仍待白名单外扩展） |
| 版本升级 selection v3 / recon v5 / mapper v4 / schema v2 / manifest v4 | 常量与解析锁已核 | 通过 |
| `git diff --check` | 交付报告尾空格；`cninfo.py` EOF 空行 | 见 P2，不单独构成语义返工 |

## 3. 新增对抗性反例

环境：Windows `D:\Miniforge3\python.exe`；`PYTHONPATH=src;.`；零网络。

| # | 反例 | 命令/方式 | 退出码/结果 |
|---|---|---|---|
| 1 | resultcode/success 正常但 count/total/records 截断或不一致 | 临时探针：`count=0,total=0,records=[row]`；`count=2,total=2,records=[1]`；既有 `count!=total` | 均 `CNINFO_RESPONSE_SCHEMA_INVALID`；**通过** |
| 2 | 改 rights_price / rights_ratio / SUBID 并重算 digest | `replace` selection result + `clean_table_content_sha256` 后 `verify_corporate_action_selection_result` | 拒绝（`G1_CORPORATE_ACTION_RESULT_INVALID` 等）；**通过** |
| 2b | 合同要求的股本身份（扩展） | 同 SUBID/日期/price/ratio，F017N/F024N/F025N 两组均合法一致但不同 | **同一 `event_id`**；合同违规 |
| 3 | 同日 dividend+rights 输入顺序打乱 | `test_dividend_and_rights_same_day_formula_and_order_invariant_digest` | 退出码 0；digest 稳定；**通过** |
| 4 | 旧 plan/manifest 降级 | plan v1 构造；v4 去掉 cninfo；v3+mapper v4 | 均拒绝；**通过** |
| 5 | 637→13 批边界与稳定性 | `batch_cninfo_symbol_groups` + `plan_cninfo_rights_requests` 正反序 | 13 批、`[50]*12+[37]`、hash 稳定、source=cninfo；**通过** |
| 6 | status 零网络；缺 receipt incomplete | `_recover_cninfo_batch` missing/partial；`test_fresh_inspect_zero_network_zero_write` + history 定向 | recover≠complete；pytest 退出码 0；**通过** |
| 7 | 000661 通式 vs market-reference | `test_rights_market_reference_happy_path` / `test_rights_declared_formula_match` | 退出码 0；无硬编码证券特判；**通过** |
| 8 | no-event fail closed；P0E supported_ratio | `test_rights_same_shape_without_event...` / unsupported ratio / `test_p0e_small_dividend...` | 退出码 0；**通过** |

定向回归（节选，均退出码 0）：
- `test_cninfo_connector` + rights/P0E/manifest 锁相关 `test_m3_execution_facts` / `test_m3_g1_release` 子集
- `test_schemas`（27 passed）
- `test_m3_g1_workflow::{test_fresh_inspect_zero_network_zero_write,test_history_bounded_incomplete_then_resume_success,test_history_max_new_rejects_illegal_before_side_effects}`

## 4. 发现项与严重度

### P1 — rights event/candidate 身份未绑定 actual/pre/post 股本

- **现象**：两组 CNINFO 行仅实际/前/后总股本不同（且各自 `post-pre==actual`），`select_g1_cninfo_rights_actions` 产出**相同** `event_id`。
- **根因**：`_rights_event_id_sha256` / `_rights_candidate_id_sha256` 只绑定 RIGHTS、symbol、SUBID、record/ex、rights_price/ratio；ledger 也不持久化 F017N/F024N/F025N。
- **应遵循规则**：任务单 §4「economic event / candidate / event id 必须包含 … rights price/ratio、actual/pre/post」；攻击者同步重算 digest 也不能替换经济参数。
- **最小复现**：构造两行相同 SUBID/日期/价格/比例，`F017N/F024N/F025N` 分别为 `(100,1000,1100)` 与 `(200,1000,1200)`，比较 `ledger["event_id"]`。
- **新增测试**：上述复现必须断言 `event_id`（及 candidate_id）不同；篡改股本并重算表 digest 后 selection/candidate/audit/release 身份闭包拒绝。
- **通过条件**：event/candidate 身份与 ledger/evidence 闭包包含实际/前/后总股本（或等价规范化股本字段）；旧身份版本显式升级，旧产物不得冒充。

### P2 — manifest/receipt projection 未强制 CNINFO 57 列完整绑定

- **现象**：`G1ReceiptProjectionV1` 与 manifest v4 解析接受 `columns=["SECCODE"]` 的 cninfo receipt；v4 仅检查 `any(source==cninfo)`。
- **根因**：投影校验未按 source=cninfo 锁定官方字段元组。
- **规则**：任务单要求发布/磁盘复验完整绑定 CNINFO receipt，而非只校验版本字符串。
- **最小复现**：`_b1b_minimal_manifest_payload(v4)` 可解析且 cninfo columns 非 57。
- **新增测试**：cninfo projection/manifest 必须 `columns==CNINFO_STOCK_ALLOTMENT_FIELDS`；缺列/裁剪列拒绝。
- **通过条件**：生产写出与只读复验均强制完整列集合（生产路径目前写出 57 列，属加固缺口）。

### P2 — `git diff --check` 空白问题

- `cninfo.py`：new blank line at EOF
- 交付报告：若干行尾空格（文档，非生产语义）
- **通过条件**：生产文件 `--check` 清洁；文档可选清理，不阻塞语义合同（本项不单独升级）。

### 残留风险（未独立绿确认）

- `test_m3_g1_candidate` 全文件、`test_m3_g1_release` 大 fixture、`test_five_stage_*`、`self_proof`：实现报告未全绿；初验以函数探针 + 定向 history/inspect 代替，**未**宣称这些长测已通过。
- 正式 637 证券 CNINFO 网络 HISTORY、WSL/Linux Gate、Windows publish、VerifiedG1Release：**明确未运行**。

## 5. `g1_workflow.py` 行尾重写审查

- 含空白：`+1986/-1841`
- 忽略空白：`+148/-3`
- 语义变更限于：导入 CNINFO、`cninfo_responses` 状态字段、HISTORY 共享 `max_new_requests` 预算、`execute_cninfo_batch`、inspect 缺 receipt 不标记 HISTORY complete、journal 路径 `data/run_state/m3_g1/cninfo`
- **结论**：大面积 diff 为行尾/换行噪声；未见无关业务改写。

## 6. 明确未运行

- 正式 637 证券 / 13-request CNINFO 网络补抓
- WSL Miniforge base 全量 Gate / Linux flock 平台终验
- Windows publish / VerifiedG1Release
- candidate/release/five_stage/self_proof 长 fixture 全量绿确认
- 主 Agent 终验

## 7. 最终结论

**FAIL**

阻断项：P1 rights 事件身份未绑定 actual/pre/post。其余强制对抗性反例（截断伪装空、price/ratio/SUBID 篡改、同日顺序、旧版本降级、637→13、inspect incomplete、000661 双路径、no-event/P0E）在零网络下通过；workflow 行尾噪声无无关语义回退证据。

返工后须再次由未参与该轮实现的外部初验会话复验，不得由实现者自测代替。
