# M3 G1 P0E：小额分红 factor / market 精度独立初验报告

状态：**独立初验通过**（仅本轮 P0E 合同范围；**不等于** Codex 终验 / G1 / Windows publish / Linux Gate 通过）

角色：外部独立初验 Agent（全新会话，未参与 P0E 实现）  
模型：cursor-grok-4.5-high  
工作区：`F:\AI_Coding\QuantitativeTrading`  
分支：`cursor/g1-p0-rework-20260726`  
实现 commit：`6d887de`（`Fix G1 small-dividend ratio precision`）  
任务书：[`M3_G1_P0E小额分红factor与market精度返工任务单.md`](M3_G1_P0E小额分红factor与market精度返工任务单.md)  
交付报告：[`M3_G1_P0E小额分红factor与market精度返工交付报告.md`](M3_G1_P0E小额分红factor与market精度返工交付报告.md)  
首败证据：[`20260727_M3_G1_P0D后正式首败_000627小额分红精度.md`](20260727_M3_G1_P0D后正式首败_000627小额分红精度.md)

---

## 1. 结论

| 项 | 结果 |
|---|---|
| 独立初验 | **通过** |
| 返工项 | 无 |
| Codex / G1 / Gate | **未宣布通过**（本轮无权） |

---

## 2. Diff 审查（对照冻结算法）

审查范围：`6d887de` 本体（相对父提交）；并核对 `d952cc9..6d887de` 中与 recon 相关生产落点。  
冻结算法：

```text
supported_ratio(x) := x > 1.0 OR abs(x - 1.0) <= rtol
```

### 2.1 `6d887de` 白名单符合性

| 路径 | 结论 |
|---|---|
| `src/quant/data/m3_execution_facts.py` | 白名单内；算法与版本变更 |
| `src/quant/domain/schemas.py` | 白名单内；matched 行条件同步 |
| `tests/unit/test_m3_execution_facts.py` 等四测文件 | 白名单内 |
| 交付报告 | 白名单内 |
| 白名单外生产代码 | **本 commit 未改** |

说明：`d952cc9..6d887de` 区间含 P0D 等前序 commit（candidate/release 等），不属本轮 P0E 实现面；P0E 实现提交 `6d887de` 自身仅触及任务书白名单。

### 2.2 Event 路径

- `_supported_ratio` 定义为 `value > 1.0 or abs(value - 1.0) <= rtol`，与冻结式等价。
- event 分支：`denominator <= 0` 或 `not _supported_ratio(actual, rtol)` → `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`。
- 有 daily：`market = previous_close / pre_close`，须 `_supported_ratio(market, rtol)`，且 `abs(actual/market-1)<=rtol`；declared 误差决定 `MATCHED_EVENT_DECLARED_FORMULA` vs `MATCHED_EVENT_MARKET_REFERENCE`。
- 无 daily：仍仅 `FULL_DAY + declared_error<=rtol`；actual 已在分支入口受 `supported_ratio` 约束。
- **declared 仍要求 `<=1` fail-closed**（未放松）。
- 注释与结构保持：event 失败 **raise**，不回退 `NO_EVENT_STABLE_FACTOR`；保留 event_ids / cash / stock。
- 未新增 status 或列。

### 2.3 Schema

`CorporateActionReconciliationSchema` 将 matched 状态原 `actual>1` / `market>1` 改为逐行 `supported_actual` / `supported_market`（相对 `factor_ratio_rtol`），与冻结算法等价；`declared > 1`、identity、顶层正数/有限值校验保留；`NO_EVENT_STABLE_FACTOR` 语义未改。

### 2.4 版本

`G1_CORPORATE_ACTION_RECONCILIATION_VERSION`：`tushare_factor_daily_preclose_v3` → `tushare_factor_daily_preclose_v4`。  
candidate / planning / reference 经 SSOT 常量传播（测试钉住）；未见无关 mapper/manifest 结构版本抬升（本 commit 未改那些生产文件）。

### 2.5 无事件 fail-closed（未放松）

`_no_event_evidence_row` 仍：`abs(actual-1)>rtol` → `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`；仅 `event_count=0` 路径可发 `NO_EVENT_STABLE_FACTOR`。verifier 对 `NO_EVENT_STABLE_FACTOR` 的 `abs(actual-1)>rtol` 校验保留。

### 2.6 Verifier

`_assert_reconciliation_row_formulas` 对 matched 路径补强 `_supported_ratio(actual/market)` 与 `declared<=1` 拒绝，与生产路径一致。

---

## 3. Pytest 重跑

解释器：`D:\Miniforge3\python.exe`  
`PYTHONPATH=F:\AI_Coding\QuantitativeTrading\src`

```text
python -m pytest tests/unit/test_m3_execution_facts.py \
  tests/unit/test_m3_g1_candidate.py \
  tests/unit/test_m3_g1_planning.py \
  tests/unit/test_m3_reference.py -q --tb=line
```

| 项 | 值 |
|---|---|
| 退出码 | **0** |
| 摘要 | **255 passed, 5 skipped** |
| 耗时 | 1282.35s（约 21m22s） |
| 收集数 | 260（含 skip） |

与交付报告自测摘要一致。本初验未跑 ruff/mypy/正式 status（任务书将隐藏反例与零网络 status 留给主 Agent）。

---

## 4. 对抗反例（实现者未使用的构造）

脚本：`artifacts/g1_component_diag_20260722/p0e_indep_probe.py`  
符号使用 `600519.SH`（实现者矩阵用 `600000.SH` / cash=`0.005` / `0.998` / `0.9995`）。

命令：

```text
set PYTHONPATH=F:\AI_Coding\QuantitativeTrading\src
D:\Miniforge3\python.exe artifacts\g1_component_diag_20260722\p0e_indep_probe.py
```

| 探针 | 构造（相对实现者矩阵的差异） | 期望 | 结果 |
|---|---|---|---|
| A | event + cash=`0.007` + prev=`5.12` + actual=market=`1.0` | `MATCHED_EVENT_MARKET_REFERENCE`；event_count/ids/cash 保留；不回退 NO_EVENT | **PASS**（declared_error≈0.001367>rtol） |
| B | event + actual=market=`0.997`（比实现者 `0.998` 更远） | 即使相互匹配也拒绝 `UNEXPLAINED` | **PASS** |
| C | no-event actual=`1.002`（>rtol=0.001；实现者仅测 1.0 稳定与大跳） | 仍拒绝 `UNEXPLAINED` | **PASS** |
| D | 版本常量 | `…_v4` | **PASS** |

汇总：`probes=4 passed=4 failed=0`。

---

## 5. 与首败形状的对应

正式首败形状（`actual=market=1.0`、小 cash、有事件）落在 `supported_ratio` 支持域且 market 匹配 → `MATCHED_EVENT_*`，与探针 A / 任务书矩阵 1 同族。无事件路径与远离 1 的反向 ratio 仍 fail-closed（探针 B/C）。

---

## 6. 非目标与边界声明

- 未改生产/测试代码、未 reset/checkout、未删 release、未改 raw/receipt、未输出 token、未调 510300 五身份 API。
- 未处理 `000661` 配股、`600733` 重复实施行。
- **本报告通过 ≠ Codex 终验 ≠ G1 / Windows publish / Linux Gate 通过。**
- 建议主 Agent 继续：隐藏反例、定向静态检查、正式零网络 `status`。

---

## 7. 返回协调者摘要

- **结论：通过**
- **pytest：255 passed, 5 skipped，exit 0**
- **对抗探针：4/4 PASS**（A 小额 cash=0.007→MATCHED_EVENT_MARKET_REFERENCE；B 0.997 互配拒绝；C no-event 1.002 拒绝；D v4）
- **报告路径：** `docs/framework/agent/M3_G1_P0E小额分红factor与market精度独立初验报告.md`
- **返工项：无**
