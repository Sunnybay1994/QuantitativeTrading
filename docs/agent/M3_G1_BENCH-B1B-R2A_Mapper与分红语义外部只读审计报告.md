# M3 G1 BENCH-B1B-R2A：Mapper 与分红语义外部只读审计报告

| 字段 | 值 |
|---|---|
| 角色 | 外部只读审计 Agent（全新会话，未参与实现） |
| 任务 | `docs/agent/M3_G1_BENCH-B1B-R2_分片合同审计与完成返工任务单.md` §2 R2A |
| 权威合同 | `docs/agent/M3_G1_BENCH-B1B_510300总回报映射与全链身份重基线任务单.md` §2.2–2.3 |
| 只读范围 | `src/quant/data/m3_mappers.py`、`src/quant/data/m3_g1_candidate.py`、`tests/unit/test_m3_g1_mappers.py`、`tests/unit/test_m3_g1_candidate.py`、`tests/unit/test_m3_labels.py`；标签语义核对时只读依赖 `src/quant/research/m3/labels.py`（未改写） |
| 唯一写入 | 本报告 |
| 约束遵守 | 未改代码/测试/配置；未联网；未跑全量/重 fixture；仅定向轻量 `pytest -k b1b`（见 §5） |
| Gate 声明 | **不得**、亦未宣布 B1B / G1 Gate 通过；本报告不是独立初验 |

---

## 1. 总判

R2A 合同项中，分红对账两公式、实施分红投影去重/冲突、事件无跳变/无事件跳变、HFQ OHLC=`raw×adj_factor`、label 禁止二次加现金等**核心实现与现有 B1B 单测大体对齐**。但「五份正式响应（1+3+1）精确闭包」「窗口首日除息不可判定」「source_snapshot 对五个身份任一变化」「label 持有期边界」等仍以**缺证据**为主；测试夹具普遍使用短窗 **1** 个 `fund_adj` 段，未锁住当前 G1 配置下的三段/五响应字面合同。

**审计结论：R2A 证据未闭合（有缺证据 + 未覆盖对抗反例）。不构成初验通过，不关闭 B1B。**

---

## 2. 逐项核对

### 2.1 五份正式响应精确闭包

| 判定 | **缺证据**（实现部分到位；字面 1+3+1 未锁测） |
|---|---|

**实现证据**

- Mapper 入口消费 `fund_daily` + `fund_adj_segments` + `fund_div`：`m3_mappers.py:174–218`。
- 空分段 / 非 list|tuple：`186–190`；`fund_adj` request_id 重复：`499–501`；分段须覆盖 daily 的 `[start,end]` 且日历相邻：`512–519`。
- Candidate 要求恰好 1×`fund_daily`、1×`fund_div`、至少一个 `fund_adj`，拒绝 `index_daily`：`m3_g1_candidate.py:1400–1412`、`1761–1767`；plan↔response 多集相等：`1703–1724`。

**测试证据**

- `test_b1b_benchmark_closure_fail_closed`：`drop_adj`/`dup_adj`/`wrong_code`/`bad_segment`：`test_m3_g1_mappers.py:837–897`。
- Happy 夹具 `_etf_happy` 对 `2026-01-15..21` 调用 `plan_fund_adj_requests` 后**只取 `specs[0]`**，构造 **1** 段 adj：`792–822`（短窗实际只有 1 段）。
- Candidate 短窗 `_D0.._D1` 同样只有 1 个 `fund_adj`：`test_m3_g1_candidate.py:418–441`。

**缺口**：无任何测试构造「全区间三个 `fund_adj` + 合计五份响应」并断言少/多/错段 fail closed。Mapper/candidate **不**硬编码 `len(fund_adj)==3`（段数依赖 planner；属 R2B 交叉面）。

**最小复现（缺证据）**

```text
plan_fund_adj_requests(510300.SH, 2015-01-05, 2026-06-30) → 3 段
当前 unit 夹具从未把这 3 段一齐喂给 map_g1_benchmark_response / build_g1_candidate
```

---

### 2.2 `fund_adj` 分段唯一 / 完整 / 稳定排序

| 判定 | **PASS**（实现）+ **缺证据**（多段乱序稳定性单测） |
|---|---|

**实现**

- request_id 唯一：`m3_mappers.py:499–501`。
- 按 `(start,end)` 排序后检验首尾对齐与 `seg_start == prev_end + 1 day`：`512–519`。
- 跨段交易日重复 → `DUPLICATE_KEY`：`547–561`。
- Candidate 先按 `request_id` 排序再交 mapper：`1413–1416`、`1507–1512`；mapper 再按日期校验，输出按 `trade_date` 排序：`252–254`。

**测试**：`dup_adj`、`bad_segment`（`end_date` 截断）已覆盖：`848–883`。

**缺证据**：≥2 段时输入逆序，断言 OHLC 与 `source_snapshot_id` 不变。

---

### 2.3 daily–factor 一一覆盖；因子有限且 >0

| 判定 | **PASS** |
|---|---|

- 日期集合必须相等：`m3_mappers.py:570–577`。
- 因子有限且 >0：`578–581`（`_parse_positive` 亦拒 ≤0/NaN/Inf：`435–460`）。
- 测试：`date_mismatch`、`zero_factor`：`884–897`。

---

### 2.4 调整 OHLC = raw OHLC × 同日 `adj_factor`（不加现金、不用 raw 收益旁路）

| 判定 | **PASS**（close 有断言；O/H/L 靠代码） |
|---|---|

- 写出：`m3_mappers.py:224–237`（仅 `raw[ohlc]*factor`，无 `+div_cash`，不把 `pre_close` 写入 clean）。
- 测试：`test_b1b_map_510300_hfq_happy_path` 断言 `2026-01-19` close ≈ `4.738*1.2671`：`825–834`。
- **轻度缺口**：未显式断言同日 open/high/low 的乘积（代码路径相同）。

---

### 2.5 五 response 的 `source_snapshot_id`

| 判定 | **PASS**（实现）+ **缺证据**（测试名 overclaim） |
|---|---|

- Canonical 身份：`(endpoint, request_id, stable_response_sha256)` 排序后 SHA-256：`m3_mappers.py:734–759`；写入每行：`220–237`。
- 测试 `test_b1b_source_snapshot_changes_with_any_response_identity`：**仅**改 `fund_div.ann_date`：`1061–1079`。
- **缺证据**：改 `fund_daily` 或任一 `fund_adj` 的 `stable_response_sha256` 亦须改变 snapshot（实现会，单测未证）。

---

### 2.6 实施分红核心投影：去重与冲突

| 判定 | **PASS** |
|---|---|

- 仅 `div_proc == "实施"`：`m3_mappers.py:26`、`603–605`。
- 投影字段后按 `(ts_code,ann_date,imp_anndate,record_date,pay_date)` 归并，`(ex_date,div_cash)` 必须唯一：`635–661`。
- `net_ex_date`/`base_unit` 不在冲突键内 → 不双计。
- 测试三类：`exact`/`net_ex_only` 接受；`cash_conflict`/`ex_date_conflict` → `G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED`：`900–923`。

---

### 2.7 两个冻结对账公式；`rtol=0.001`；无绝对容差

| 判定 | **PASS** |
|---|---|

- 公式 1：`ex_pre ~= prev_close - div_cash`：`699–704`。
- 公式 2：`ex_factor/prev_factor ~= prev_close/ex_pre`：`705–714`。
- `_relative_close(..., abs_tol=0.0)`：`664–669`；默认 `_FACTOR_RATIO_RTOL = 0.001`：`27`。
- 正例夹具对齐 B0：`4.859-0.123=4.736`，`1.2671/1.2350` vs `4.859/4.736`：`_etf_daily_rows`/`_etf_adj_rows`/`_etf_div_rows`：`670–785`；`test_b1b_r2_positive_and_jump_failures`：`926–931`。
- 错误公式 `ex_pre/(ex_pre-div_cash)` 拒绝，正确比通过：`948–1058`。

---

### 2.8 窗口首日边界（窗外历史跳变不可判定）

| 判定 | **缺证据**（实现有，测试无） |
|---|---|

- `idx == 0` 时跳过该事件的因子跳变强制，且不猜失败：`m3_mappers.py:694–697`。
- **无**单测：窗口起始日 == `ex_date` 时映射成功（不得因窗外不可见 prev_factor 而失败）。

---

### 2.9 无事件因子跳变 / 事件存在但因子不跳变

| 判定 | **PASS** |
|---|---|

- 事件路径要求 ratio 不得≈1：`715–716`。
- 相邻日扫描：无解释跳变 / 已解释却无跳变：`719–731`。
- 测试：`no_jump`（除息日因子不跳）与 `unexplained`（无事件日跳变）：`932–945`。

---

### 2.10 Label：entry 前 / entry 日 / 持有期 / exit 后；禁止二次加现金

| 判定 | entry 前 **PASS**；entry 日 **PASS**；exit 后 **PASS**；持有期 **缺证据**；禁止二次加现金 **PASS** |
|---|---|

**实现**（`labels.py`，只读）

- `benchmark_return = bench_exit.close / bench_entry.open - 1.0`：`107–110`（无 `div_cash`、无 benchmark `adj_factor` 再乘）。
- 股票侧才用 `adj_factor`：`107–109`。
- entry/exit 会话：`as_of+1` open → `as_of+h` close：`101–102`。

**测试** `test_b1b_dividend_boundaries_no_double_count_on_hfq_prices`：`test_m3_labels.py:387–489`

| 边界 | 做法 | 判定 |
|---|---|---|
| 基线（声称持有期内除息） | 固定 HFQ `105/100-1`，`label_version=v3` | 证明纯价比、无 `+cash`；**未**构造持有期内 ex-date 相对无分红对照 → **持有期缺证据** |
| entry 前 | 改 `2026-01-05` OHLC，收益不变 | **PASS** `404–430` |
| exit 后 | 改 `2026-01-19` OHLC，收益不变 | **PASS** `432–457` |
| entry 日 | 改 `2026-01-06` open→110，收益变 `105/110-1` | **PASS** `459–489` |

`LABEL_VERSION` 常量：`test_m3_labels.py:17` 与合同 `..._excess_v3` 一致。

---

### 2.11 Candidate 对 mapper/benchmark 身份的衔接（R2A 范围内）

| 判定 | **PASS**（短窗烟雾）+ **缺证据**（三段闭包） |
|---|---|

- `G1BuildSpec` 冻结 mapper-v2 与三项 benchmark 身份：`m3_g1_candidate.py:57–61`、`241–268`；测试 `_build_spec`：`310–325`。
- `build_g1_candidate` 调用 `map_g1_benchmark_response`：`1507–1515`。
- `happy_path` 可构建含 `benchmark_bars` 的 candidate（模块 fixture）；审计未跑 300 标的重 fixture 全路径计时（属 R2 性能备注，非本分片逻辑 FAIL）。

---

## 3. 未覆盖对抗性反例（至少一条；只报告，不写测试）

### 反例 R2A-ADV-1（优先）：三分段窗口上的「伪完整、真缺中段」

**现象假设**：攻击者提供 `fund_daily` 全窗 + **两段** `fund_adj`（仅首段 `start=history.start`、末段 `end=history.end`），中间日历缺口（例如缺 `20190101..20221231`），但把缺口交易日的因子行非法塞进首段或末段 frame（或干脆缺失）。

**期望（合同）**：分段参数必须相邻完整（`m3_mappers.py:515–519`）或 daily/factor 日期集不等（`570–577`）→ fail closed。

**当前测试**：`bad_segment` 只截断**单段** `end_date`（`870–883`）；**从未**在 3 段几何上测「缺中段」。

**最小复现草图**

```text
segments = plan_fund_adj_requests(510300.SH, 2015-01-05, 2026-06-30)  # 3
feed map_g1_benchmark_response with (segments[0], segments[2]) only
# 期望: G1_MAPPER_BENCHMARK_CLOSURE_INVALID
# 今日单测: 无
```

### 反例 R2A-ADV-2：窗口首日 == ex_date（不可判定）

```text
window_start = ex_date = 2026-01-19
daily/adj 仅含 01-19..01-21；因子已为 1.2671 平台
div 含实施事件 ex_date=2026-01-19, div_cash=0.123
# 合同: 不得因窗外 prev_factor 不可见而失败
# 代码: idx==0 continue（694-697）
# 今日单测: 无
```

### 反例 R2A-ADV-3：label「持有期」中间会话 OHLC 扰动

```text
as_of=2026-01-05, h=5 → entry=01-06, exit=01-12
向 benchmark_bars 插入/修改 01-08 OHLC（entry/exit 不变）
# 期望: benchmark_return 仍为 exit.close/entry.open-1，且绝不出现 +div_cash
# 今日单测: 无中间会话行，也无持有期对照
```

### 反例 R2A-ADV-4：snapshot 声称 “any response” 但只测了 div

```text
保持对账成立，仅改 fund_adj 某非跳变日的无关列或等价改写 stable_response_sha256
# 期望: source_snapshot_id 变化
# 今日: 仅 fund_div.ann_date（1061-1079）
```

---

## 4. 性能与复杂度（R2 §4 范围内备注）

- R2A 定向 `b1b` 单测约 **2.5s / 12 passed**，未见 mapper 分红路径引入分钟级耗时。
- Candidate 模块级 300 标的 `happy_candidate` 与 `verify_corporate_action_selection_result`/Pandera 重 fixture 属于**既有重 fixture**，不在本分片用削弱 Schema 换速度；亦未发现 B1B 分红对账逻辑本身是该耗时的主因（主因在 candidate 全表构建，属既有复杂度）。

---

## 5. 定向验证命令（轻量，非 Gate）

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_g1_mappers.py -k b1b tests/unit/test_m3_labels.py -k "b1b or dividend_boundaries" -q
# 结果: 12 passed, 34 deselected, ~2.5s（Windows Miniforge）
```

未跑 WSL base 全量、未跑 `test_release_identity_stable_under_row_shuffle` 等重测。

---

## 6. 建议返工输入（供主 Agent 合并 R2B 后冻结；本 Agent 不实现）

1. 增加 **1+3+1** 五响应 mapper 夹具：缺中段 / 多一段 / 三段乱序稳定性 / 五身份任一改写 snapshot。
2. 增加 **窗口首日 == ex_date** 成功路径。
3. 补强 label：**持有期**中间会话扰动 + 与无分红基线对照；保持禁止 `+div_cash`。
4. 可选：happy path 断言 open/high/low 同乘；`fund_adj` 负/NaN/Inf；`fund_div` 带 `start_date` 拒绝。
5. 测试卫生：`test_m3_g1_mappers.py:36` 仍留 `_BENCHMARK = "H00300.CSI"` 旧助手常量（B1B 路径用 `_ETF`，非功能 FAIL，但易误导后续改测）。

---

## 7. 明确非结论

- 本报告 **不是** 独立初验，**不是** 主验。
- **不得**将「12 passed」解读为 B1B 或 G1 Gate 通过。
- 初验仍须另起未参与实现的外部会话，并在实现者补齐缺口之后进行。
