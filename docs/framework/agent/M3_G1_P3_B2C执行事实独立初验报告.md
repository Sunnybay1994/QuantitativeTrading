# M3 G1-P3 B2C：执行事实独立初验报告

日期：2026-07-14  
角色：**外部独立初验 Agent**（从未参与 G1-P3 B2C 实现）  
实际模型标识：`cursor-grok-4.5-high`  
权威任务书：[`M3_G1_P3_B2C执行事实外部闭环任务单.md`](M3_G1_P3_B2C执行事实外部闭环任务单.md)  
实现线索（不作唯一证明）：[`M3_G1_P3_B2C执行事实交付报告.md`](M3_G1_P3_B2C执行事实交付报告.md)  
主契约：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.10  
上游已验收：[`M3_G1_B2A主Agent最终验收报告.md`](M3_G1_B2A主Agent最终验收报告.md)、[`M3_G1_P1主Agent最终验收报告.md`](M3_G1_P1主Agent最终验收报告.md)、[`M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md`](M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md)

## 结论

**外部独立初验不通过，退回实现 Agent 返工。**

本报告不宣称 B2 / P3 / G1 / 任一 Gate 完成。唯一仓库写入为本报告；未修改生产代码、Schema、配置、实现者测试、任务书或原交付报告；未联网、未读 token、未访问 `_old/`。临时对抗脚本仅位于 WSL `/tmp`，验收后已清理。

阻断项：**P1-1**（`CorporateActionReconciliationResult` / `verify_corporate_action_reconciliation_result` 未按任务书 §10/§14 重算并校验 `event_ids_sha256`；仅改 event-set hash 并同步 content digest 时构造与公开 verify 均接受）。identity closure 不得降为 P2。

---

## 1. 修改范围核对

| 文件 | 是否在任务书 §12 允许范围 | 独立核验 |
|---|---|---|
| `src/quant/data/m3_execution_facts.py` | 允许新增 | 存在；版本常量与六函数/两 result/错误类型签名与 §4 一致 |
| `src/quant/domain/schemas.py` | 允许收紧/新增 Schema | ledger 收紧；新增 selection/reconciliation Schema |
| `src/quant/data/__init__.py` | 仅追加导出 | 三个版本常量、两 result、错误类型、六函数均导出 |
| `src/quant/domain/__init__.py` | 仅追加导出 | 两新 Schema 已导出 |
| `src/quant/research/m3/config.py` | 仅收紧 rtol 上限 | `factor_ratio_rtol` `maximum=0.01` |
| `tests/unit/test_m3_execution_facts.py` | 允许新增 | 24 个测试函数 |
| `tests/unit/test_schemas.py` / `test_m3_config.py` | 允许回归 | 已覆盖 |
| `docs/M3_G1_P3_B2C执行事实交付报告.md` | 允许 | 已读；未宣称 Gate |

未见对 B2A/B2B/P2 已验收生产代码、路线图勾选或配置示例数值的越权修改（只读审查范围内）。digest 调用为生产 `clean_table_content_sha256`（P2 已验收），未见复制 canonicalizer。

---

## 2. 冻结接口与不变量证据映射

| 冻结项 | 源码证据 | 结果 |
|---|---|---|
| 版本常量三字符串 | `G1_*_VERSION` 与任务书 §4 精确一致 | 通过 |
| 读值前重建 `VerifiedRawResponse` | `_consume_verified` → `_prepare` 后才 `iter_rows`；daily 全量重建 | 通过（对抗 C1） |
| sentinel null/zero 不进 clean；永不发 `has_price_limit=False` | `map_g1_price_limit_response` continue；输出恒 `True` | 通过（对抗 C4） |
| coverage：next session 起算；FULL_DAY 豁免；PARTIAL/无 suspension 必有 limit | `require_g1_price_limit_coverage` | 通过（对抗 C2/C3/C4） |
| dividend 先裁 `ex_date` 再验结算；空窗合法 | `select_g1_corporate_actions` | 通过（对抗 C5） |
| null ann/imp total order；同 rank 重复折叠；pay 冲突失败 | `_version_rank_key` / `_fold_identical_candidates` | 通过（对抗 C6） |
| 同 ex-date 多 economic group 分别选版，对账时聚合 `math.fsum` | selection 分组键 + reconcile 按 event_id 排序 fsum | 通过（对抗 C7） |
| factor gap 事件不得挪到下一观测 | ex_date 必须是 factor date | 通过（对抗 C8） |
| previous close 可早于 previous factor | `_previous_close` | 通过（对抗 C9） |
| declared 超 rtol 且 raw `pre_close` 闭合 → `MATCHED_EVENT_MARKET_REFERENCE`；caller 自算 pre_close 失败 | reconcile 分支 | 通过（对抗 C10） |
| FULL_DAY 缺 daily → `NO_MARKET_REFERENCE`；PARTIAL/跨源失败 | reconcile 缺行分支 | 通过（对抗 C11） |
| Result Schema 写回 + digest；frame/hash 局部漂移失败 | `__post_init__` + `object.__setattr__` | 通过（对抗 C12 hash-only / dtype） |
| rtol∈[0,0.01]；1.0/NaN 不能放绿；脱敏 | `_validate_rtol` / `_sanitize` | 通过（对抗 C13） |
| **verify 重算 event-set hash** | `_assert_reconciliation_row_formulas` **未**校验 `event_ids_sha256` | **失败 → P1-1** |
| 无网络/research/Qlib 反向 import | 生产模块静态阅读 | 通过 |

信任边界（任务书 §10）：全套内部自洽替换须由 B4 从原输入重算关闭——本报告确认；**但**「只改 event-set hash」被明确要求自包含 verify 拒绝，不属于该 B4 边界豁免。

---

## 3. 实现者未使用的对抗性反例（任务书 §14）

临时脚本 `/tmp/b2c_adv_verify.py`（已清理）。fixture 使用 `000001.SZ` + `2024-05-06..10`，未复用实现者 `600000.SH` / `2026-01` 精确组合。覆盖 §14 所列类别 **≥10 类**（超过最低 6 类）。

| ID | 类别 | 对抗要点（相对实现者差异） | 结果 |
|---|---|---|---|
| C1 | Verified 自洽伪造 | frame+content+stable 自洽重算，外层 `receipt_sha256` 陈旧 | **PASS**（`RESPONSE_INVALID`） |
| C2 | 持仓延续域 | 仅覆盖 next-buy 附近，缺调出后非 FULL_DAY 的 D3 | **PASS**（`PRICE_LIMIT_UNPROVEN`） |
| C3 | Schema false vs G1 | `has_price_limit=false` 过 Schema，coverage 拒绝 | **PASS** |
| C4 | sentinel×FULL_DAY/PARTIAL/无 | zero/null `pre_close`；仅 FULL_DAY 豁免 | **PASS** |
| C5 | 1991 OOW 缺 pay vs 窗内 | 同形缺 pay | **PASS** |
| C6 | null total order + dup + pay 冲突 | 四候选混排；同 rank 仅 pay 不同 | **PASS** |
| C7 | 双 economic group 同 ex-date | 现金+送转分别选版，对账 `event_count=2` | **PASS** |
| C8 | gap 内事件 + 可解释 jump | ex=D1，factor 仅 D0/D2 | **PASS**（`FACTOR_INVALID`） |
| C9 | previous_close ≠ previous_factor | 停牌缺 bar；close 自 D0，factor prev=D1 | **PASS** |
| C10 | MARKET_REFERENCE + caller pre_close | declared 超 0.001；换 daily pre_close 为通式残差 | **PASS** |
| C11 | NO_MARKET_REFERENCE / PARTIAL / 跨源 | FULL_DAY 闭合；超差/PARTIAL/`baostock` | **PASS** |
| C12 | result identity / event-set / dtype | hash-only 漂移拒绝；**只改 `event_ids_sha256` 并同步 digest 被接受**；Utf8→Date 写回 | **FAIL（P1-1）** / cash 与 dtype **PASS** |
| C13 | rtol=1.0/NaN + 脱敏 | 无法放绿 unexplained；`token=` 不进 repr/traceback | **PASS** |

---

## 4. 返工项 P1-1

### 现象

对合法 `CorporateActionReconciliationResult` 的 MATCHED 行，仅将 `event_ids_sha256` 改为另一合法 64 hex，并用 `clean_table_content_sha256` 重算 `evidence_sha256` 后：

- `CorporateActionReconciliationResult(...)` 构造成功；
- `verify_corporate_action_reconciliation_result(...)` 通过。

cash 单字段篡改（不同步公式）仍被拒绝；hash-only 漂移仍被拒绝。说明 digest/公式门禁存在，但 **event-set hash 未被独立重算**。

### 根因

`_assert_reconciliation_row_formulas` 校验 declared/market 公式与 status，**不**根据 `event_count` 与规范空集合/事件集合重算或约束 `event_ids_sha256`。公开 verify 因此无法满足任务书 §10「必须重算 … event-set hash」。

### 应遵循规则

- 任务书 §10：构造与公开 verify 必须重算 event-set hash 与全部 digest；
- 任务书 §14：`event-set hash/event_count/cash sum` 中只改一项，verify 必须失败；
- 任务书 §8.3 / §9.2：`event_ids_sha256 = SHA256(["m3-g1-corporate-action-event-set-v1", *sorted_event_ids])`；空集合即只含 namespace 的数组；
- AGENTS.md：identity closure 与返工项不得降为 P2。

### 最小复现

1. 构造任一合法 MATCHED reconciliation result（可用独立对抗 C12 路径：`000001.SZ`，`2024-05`，纯现金事件）；
2. `evidence = evidence.with_columns(... event_ids_sha256 = "c"*64 ...)`（仅 MATCHED 行）；
3. `digest = clean_table_content_sha256(table_name="corporate_action_reconciliation", frame=evidence)`；
4. `CorporateActionReconciliationResult(evidence=evidence, evidence_sha256=digest)` 与随后 `verify_corporate_action_reconciliation_result` **当前均成功**（缺陷）；预期均失败。

### 新增测试

实现者测试必须新增（不得只改 fixture 一个数）：

1. MATCHED 行只改 `event_ids_sha256` 并同步 digest → 构造/verify 均 `G1_CORPORATE_ACTION_RECONCILIATION_INVALID`；
2. `NO_EVENT_STABLE_FACTOR` 行 `event_ids_sha256` 必须等于空事件集规范 hash；偏离且同步 digest → 失败；
3. （建议）若 verify 无法从行内恢复 event id 列表，则最小修复为：对 `event_count==0` 强制空集 hash；对 `event_count>0` 在 result 中保留可重算证据或在 verify 合同中显式绑定 ledger event id 集合——以任务书「重算 event-set hash」为准，不得仅依赖整表 digest。

### 通过条件

- 上述反例稳定拒绝，且 `__cause__ is None`、无凭据泄露；
- 原 C1–C11、C13 与实现者矩阵不回归；
- 定向 + 全量 pytest、Ruff、mypy 仍通过；
- 独立初验复跑 C12 event-set 篡改项为 PASS 后，方可再交主 Agent 终验。

---

## 5. WSL 工具链验证

全部经 `wsl.exe` → `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` → `/home/mabw/miniforge3/bin/conda run -n base`；禁止 Windows Python/conda。

| 命令 | 结果 |
|---|---|
| 定向 pytest（execution_facts/schemas/config/backfill/mappers/membership/identity） | **305 passed** |
| 全量 `python -m pytest -q` | **595 passed**，3921 条既有 Pandera/Polars deprecation warnings |
| `python -m ruff check src tests` | **All checks passed** |
| `python -m mypy src` | **76 source files，0 issues** |
| 独立对抗脚本 | **C12a FAIL（P1-1）**；其余对抗项 PASS |

绿测不能掩盖 identity 反例失败。

---

## 6. Import 隔离、联网与脱敏

- `m3_execution_facts.py` 无 `quant.research`、无 qlib、无网络客户端、无配置路径读写；
- 本次初验未联网、未读 token/ignored 凭据、未写 raw/clean；
- 对抗 C13：恶意 `/home/secret/token=` 不进入 `str`/`repr`/traceback 公开消息。

---

## 7. 交付声明

**独立初验不通过。** 请主 Agent 形成返工任务交回外部实现 Agent；返工交付后须由**未参与该轮实现**的另一外部初验 Agent 复验。

**不得宣称 B2 / P3 / G1 / 任一 Gate 通过。** 本报告即使在工具链全绿时，也只证明发现阻断项，不关闭本包。
