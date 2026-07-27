# M3 G1 P0E：小额分红 factor / market 精度独立初验报告

状态：**PASS（独立初验）**

角色：外部独立初验 Agent（全新会话，未参与实现；本轮只读，仅写入本报告）  
模型：Cursor Grok 4.5（`cursor-grok-4.5-high` 语义；本会话为 Cursor IDE Agent）  
基线：`5c790b7`  
待审：`6d887de33da8790f944f63583571de0976cad4b8`（`Fix G1 small-dividend ratio precision`）  
任务书：[`M3_G1_P0E小额分红factor与market精度返工任务单.md`](M3_G1_P0E小额分红factor与market精度返工任务单.md)  
交付报告：[`M3_G1_P0E小额分红factor与market精度返工交付报告.md`](M3_G1_P0E小额分红factor与market精度返工交付报告.md)  
首败证据：[`20260727_M3_G1_P0D后正式首败_000627小额分红精度.md`](20260727_M3_G1_P0D后正式首败_000627小额分红精度.md)

环境：Windows 原生 `D:\Miniforge3\python.exe`  
未运行：WSL/Linux Gate、正式 `status` / reference / prepare / publish、000661 配股、600733 重复实施行

---

## 0. 审查方法

1. 完整阅读任务书、首败证据、交付报告、废止合同文档与 `5c790b7..6d887de` diff。  
2. 独立核对 `m3_execution_facts` / Schema / verifier / `G1BuildSpec` 版本钉，不以交付报告为唯一证据。  
3. 定向 pytest / ruff / mypy / `git diff --check`。  
4. 在 `%TEMP%` 内联脚本构造实现者未使用的对抗反例（未写入仓库）。

白名单外生产代码无改动；无关结构版本（selection / price_limit / mapper / schema）未提升。

---

## 1. 冻结合同逐项

### 1.1 `supported_ratio(x) := x > 1.0 OR abs(x - 1.0) <= rtol`

- **合同**：事件分支 actual/market 支持域。  
- **代码证据**：`_supported_ratio`；reconcile 用 `not _supported_ratio(actual/market, rtol)` 替代原 `<= 1.0`；Schema `supported_actual` / `supported_market` 等价。  
- **测试/反例**：实现者矩阵 1–2；独立反例 A1（见 §2）。  
- **结论**：PASS

### 1.2 有 daily 时 market 须 supported，且 `actual/market` 相对误差 ≤ rtol

- **代码证据**：`market = prev_close/ex_ref` 后 `_supported_ratio(market)` + `market_error > rtol` → `FACTOR_UNEXPLAINED`；verifier 同步校验。  
- **测试**：矩阵 1、2、4。  
- **结论**：PASS

### 1.3 保留 MATCHED_* / 无 market 声明状态；event ids/cash/stock 闭合，不得伪装 NO_EVENT

- **代码证据**：事件分支仍写 MATCHED_* 并保留 ids/cash/stock；注释禁止回退 NO_EVENT；Schema `no_event` 要求 `event_count==0` 等。  
- **测试**：矩阵 1、8（status 伪装 Schema 拒；清 ids / 改 cash 拒）。  
- **独立反例 A3/A4**：见 §2（验证层级说明）。  
- **结论**：PASS（生成路径与不完整伪装）；完整字段抹成合法 NO_EVENT 形状属 recon 单表层残留风险，见 §4

### 1.4 无 daily 仅 FULL_DAY 且 declared error ≤ rtol；actual 仍须 supported

- **代码证据**：缺 daily 分支仍要求 FULL_DAY + `declared_error<=rtol`；入口已要求 `_supported_ratio(actual)`。  
- **测试**：矩阵 5、6；额外 FULL_DAY tiny declared → `NO_MARKET_REFERENCE`。  
- **结论**：PASS

### 1.5 no-event 仅稳定因子；大跳 fail-closed

- **代码证据**：`_no_event_evidence_row` 仍 `abs(actual-1)>rtol` → `FACTOR_UNEXPLAINED`。  
- **测试**：矩阵 7。  
- **结论**：PASS

### 1.6 远低于 1 且超 rtol 的反向 ratio，即使 actual==market 也拒

- **代码证据**：`supported_ratio` 先于 mutual match。  
- **测试**：矩阵 3；独立 A2。  
- **结论**：PASS

### 1.7 reconciliation version v3→v4，经 candidate/planning/reference 传播；旧 v3 拒；无关版本不升

- **代码证据**：常量 `tushare_factor_daily_preclose_v4`；`G1BuildSpec` / planning 钉 SSOT；selection=`…_v2`、price_limit=`…_v2`、mapper=`…-v3` 未改。  
- **测试**：四文件版本钉 + 旧 v3 `ValueError`；独立 A6。  
- **结论**：PASS

### 1.8 非目标遵守

- **证据**：diff 无 000661/600733/正式 Gate；本轮未跑正式 status。  
- **结论**：PASS

---

## 2. 独立对抗反例（实现者未明确使用）

| ID | 反例 | 结果 | 层级说明 |
|---|---|---|---|
| A1 | `rtol=0.001`，用 `1.0-rtol` 再 `nextafter` 向 1 修正到 `abs(x-1)<=rtol` 的精确浮点边界（避免字面量 `0.999` 二进制超界） | reconcile → `MATCHED_EVENT_MARKET_REFERENCE` | 字面量 `0.999` 的 `abs(·-1)=0.001000…>0.001`，**不能**当验收输入 |
| A2 | `actual=market=0.998` | `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED` | 支持域优先于相互匹配 |
| A3 | 篡改 event ids 并重算 `event_ids_sha256`；或改 cash 并重算 declared/error | **行公式/Schema 接受** | `CorporateActionReconciliationResult` 只做行内 identity+公式；ledger/selection 闭包在 `CorporateActionSelectionResult`，不在 recon 单表 |
| A4 | 仅改 status→NO_EVENT | Schema 拒绝 | 事件字段仍在时不得伪装 |
| A4b | 抹成完整合法 NO_EVENT 行并重算 digest | recon verifier **接受** | 见 §4 残留风险 |
| A5 | `cash==prev_close` / `cash>prev_close` 走 reconcile；零分母走 public rebuild | `FACTOR_UNEXPLAINED` / `RECONCILIATION_INVALID` | 公共 API 不泄露 `ZeroDivisionError`；内部 `_assert_reconciliation_row_formulas` 直调会 ZDE，但 `__post_init__`/verify 外层吞并映射 |
| A6 | v4 钉、旧 v3 拒、selection/price_limit/mapper 不变 | 通过 | — |

---

## 3. 验收命令结果

解释器：`D:\Miniforge3\python.exe`

| 命令 | 退出码 | 摘要 |
|---|---|---|
| `pytest` 四定向文件 `-q --tb=line -p no:cacheprovider` | **0** | 255 passed, 5 skipped（约 1263s） |
| `ruff check` 六白名单文件 | **0** | All checks passed |
| `mypy` 两生产文件 | **0** | no issues found |
| `git diff --check 5c790b7..6d887de`（全范围） | **2** | 仅交付报告 markdown 行尾空白 |
| `git diff --check` 六代码/测试文件 | **0** | 通过 |

---

## 4. 残留风险（不构成本轮 FAIL）

1. **完整 NO_EVENT 结构抹除**：P0E 使 `actual≈1` 的 MATCHED 行更易被改写成合法 NO_EVENT 形状；recon 单表与 candidate topology（只绑 factor 键/比率）不检查 ledger 事件↔recon status。生成路径仍 fail-closed；不完整伪装由 Schema 拒绝。主验可考虑 ledger↔recon 事件存在性闭包。  
2. **交付报告 trailing whitespace**：全范围 `git diff --check` 非零；代码白名单干净。  
3. **未跑** Linux/ext4 Gate、正式零网络 `status`、隐藏反例主验。  
4. 内部公式助手对零分母可抛原生 ZDE；公共构造/verify 已映射为项目错误码。

---

## 5. 总结论

**PASS**

冻结合同 1–8 在生产代码、Schema、verifier 与版本传播上成立；定向测试与关键独立反例（含浮点安全边界、反向 ratio、公共零分母路径、v4 传播）通过。不得据此宣布 G1 / Windows publish / Linux Gate 通过。
