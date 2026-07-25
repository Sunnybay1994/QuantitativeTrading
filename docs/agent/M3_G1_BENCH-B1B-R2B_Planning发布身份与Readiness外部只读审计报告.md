# M3 G1 BENCH-B1B-R2B：Planning / 发布身份 / Readiness 外部只读审计报告

| 项 | 内容 |
|---|---|
| 角色 | 外部只读审计 Agent（全新会话，`cursor-grok-4.5-high`） |
| 任务单 | [`M3_G1_BENCH-B1B-R2_分片合同审计与完成返工任务单.md`](M3_G1_BENCH-B1B-R2_分片合同审计与完成返工任务单.md) §3 R2B |
| 原合同 | [`M3_G1_BENCH-B1B_510300总回报映射与全链身份重基线任务单.md`](M3_G1_BENCH-B1B_510300总回报映射与全链身份重基线任务单.md) |
| 范围 | 只读 R2B 列出的 planning/config/release/readiness 代码与测试；唯一写入本报告 |
| 非目标 | 不修改代码/测试/配置；不联网；不跑重型全量/`test_release_identity_stable_under_row_shuffle`；**不宣布 B1B/G1 Gate** |
| 审计结论 | **存在确定合同缺口与测试证据空洞**；本分片**不得**视为可进入“实现已完成/可关 Gate”状态。下列逐项为 PASS / FAIL / 缺证据。 |

---

## 0. 验证命令（轻量、定向）

Windows Miniforge（`D:\Miniforge3\python.exe`），仅跑与本分片直接相关的轻量用例：

```text
pytest tests/unit/test_m3_backfill_requests.py::test_b1b_etf_history_plan_preserves_equity_request_ids \
  tests/unit/test_m3_backfill_requests.py::test_b1b_full_window_fund_closure_three_adj_and_equity_ids \
  tests/unit/test_m3_g1_release.py::test_b1b_manifest_v1_strict_read_v2_current_and_forged_rejected \
  tests/unit/test_m3_readiness.py::test_l0a_price_index_config_rejected \
  tests/unit/test_m3_g1_planning.py::test_static_plan_from_c0_and_forged_identity \
  tests/unit/test_m3_g1_planning.py::test_history_plan_order_invariant_and_response_set -q
```

结果：`6 passed`（约 15.8s）。未执行 `test_release_identity_stable_under_row_shuffle`（任务单已记 287s 重 fixture）。

另用只读探针（不写盘、不联网）核对 readiness 多/空 snapshot、伪造唯一 snapshot，以及 v1/v2 primary-key 字段差。

---

## 1. 逐项合同核对

### 1.1 旧证券 request identity 不变；新计划精确 3190；无 H00300

| 子项 | 判定 | 证据 |
|---|---|---|
| 玩具规模下 equity `request_id` 相对 legacy `plan_history_requests(..., H00300.CSI)` 不变 | **PASS** | 生产：`plan_g1_etf_history_requests` 先调 legacy 再剥离 `index_daily` 并换入 fund 闭包（`g1_planning.py` L643–709）。测试：`test_m3_backfill_requests.py` L2118–2158、L2161–2203；本轮定向绿。 |
| 新 plan 无 `index_daily` / 无 `H00300.CSI` | **PASS** | 同上测试断言 L2152、L2199–2203；探针：`has_index_daily=False`，`has_H00300=False`。 |
| 全配置窗 `fund_adj` 恰 3 段（2015–2018 / 2019–2022 / 2023–end） | **PASS** | 探针分段 `('20151008','20181231')…('20230101','20260710')`；测试 L2196–2198。 |
| **生产闭包精确 3185→3190** | **缺证据** | 唯一“3190”断言是算术恒真式：`assert 5 * 637 + 1 + 3 + 1 == 3190`（`test_m3_backfill_requests.py` L2204–2205），**未**用当前配置推导出的真实 `history_symbols`（声称 637）构建 plan 并 `len==3190`。短窗规划测试用 `5 * symbol_count + 3`（`test_m3_g1_planning.py` L640–641），与生产 `+5` 闭包不是同一命题。全库无 `3185` 字面回归。 |

**最小复现（3190 证据空洞）：**

```python
# 当前测试只证明 5*637+5==3190，不证明 plan 长度
assert 5 * 637 + 1 + 3 + 1 == 3190  # 恒真，与 plan_g1_etf_history_requests 无关
```

**应补通过条件：** 在冻结日历/membership 下得到 `N=len(history_symbols)`，断言 `N==637`（或权威 N）、equity 端点数 `5*N==3185`、ETF 闭包 `+5`、`len(history_batch.requests)==3190`，且 equity `request_id` 集合等于同符号 legacy 剥离 `index_daily` 后的集合。

---

### 1.2 三个 benchmark 身份显式进入 build spec / manifest / release hash

合同字段：

- `benchmark_mode = TRADEABLE_ETF_TOTAL_RETURN_PROXY`
- `benchmark_method_version = tushare_510300_fund_daily_fund_adj_hfq_v1`
- `benchmark_dividend_reconciliation_version = tushare_fund_div_implemented_cash_v1`

| 子项 | 判定 | 证据 |
|---|---|---|
| 配置字面量 + g1 selector | **PASS** | `config.py` L196–220；`configs/research/m3_qlib_example.toml` L53–56。 |
| `G1BuildSpec` 强制三字段 | **PASS** | `m3_g1_candidate.py` L235–268；planning 写入 `g1_planning.py` L605–609；`__post_init__` 校验 L368–376。 |
| static plan / primary candidate / manifest v2 JSON 含三字段 | **PASS（代码）** | `_static_plan_sha256` L1421–1425；`_primary_candidate_key` L1885–1888；`G1ManifestV2` L549–570；`_build_manifest` L1349–1353；`_manifest_to_jsonable` L2321–2326。 |
| v1 primary 路径**不含**三字段 → 与 v2 身份必然不同 | **PASS（代码探针）** | `_primary_from_manifest` v1 分支 L2136–2167 无 benchmark 键；同输入下 v2 key ≠ v1-style key（本轮探针 `differ True`）。 |
| 测试断言三字段均进入 planning build_spec | **缺证据** | `test_m3_g1_planning.py` 仅断言 `benchmark_mode`（L572）与 `mapper_version`（L573）；**零次**出现 `benchmark_method_version` / `benchmark_dividend_reconciliation_version`。 |
| 测试证明“仅改展示字符串、身份字段未进 hash”会被拒绝，或三字段参与 release_id | **缺证据** | release B1B 测解析/伪造 method（见 1.4），无“改 method → primary/release_id 变化”的显式哈希差分测试（且 `G1BuildSpec` 字面量锁死，测试也未用旁路 payload 证明 hash 输入含三字段）。 |

---

### 1.3 当前发布只生成严格 v2

| 判定 | **PASS** |
|---|---|
| 证据 | `_MANIFEST_SCHEMA = _MANIFEST_SCHEMA_V2`（`m3_release.py` L69–71）；`_build_manifest` 注解与实现均返回 `G1ManifestV2`（L1312–1360）。测试：`test_b1b_manifest_v1_strict_read_v2_current_and_forged_rejected` L930–932。定向绿。 |

---

### 1.4 历史 v1 严格可读；不得作当前发布输入；混合/缺/多字段/伪造 method fail closed

| 子项 | 判定 | 证据 |
|---|---|---|
| v1 严格按 `G1ManifestV1` 字段集读取 | **PASS** | `_parse_manifest_bytes` L2036–2038 + `_exact_field_names`；测试 L917–922。 |
| v1 + 掺入 v2 身份字段 → 拒绝 | **PASS** | 测试 L940–948（`schema=v1` + `extra={"benchmark_mode":...}`）。 |
| v2 伪造 `benchmark_method_version` → 拒绝 | **PASS** | `G1ManifestV2.__post_init__` L564–565；测试 L950–960。 |
| v2 缺身份字段 → 拒绝 | **PASS** | 测试 L962–966（删 `benchmark_dividend_reconciliation_version`）。 |
| 未知 schema → 拒绝 | **PASS** | 测试 L934–938（`v9`）。 |
| v2 多未知顶层字段 → 拒绝 | **PASS（代码+探针）** | `_exact_field_names` L1992–1995；探针 `extra_field → G1_RELEASE_JSON_INVALID`。B1B 命名测试未单列“v2+arbitrary extra”，但同一解析路径覆盖。 |
| “v1 不得作为当前 publish 输入” | **PASS（结构）/ 缺证据（专用测试）** | `publish_g1_release` / `prepare_g1_release` 输入是 `G1ReleaseInputs`（build_inputs），不接受落盘 v1 manifest 再发布；当前写出路径只建 v2。无“喂 v1 manifest 企图 republish”的专用反例测试（API 面也不暴露该入口）。 |

---

### 1.5 readiness：拒旧 benchmark、raw 510300、不完整 snapshot、身份漂移

| 子项 | 判定 | 证据 |
|---|---|---|
| 拒 `H00300.CSI` / 非 `510300.SH` 配置 | **PASS** | `readiness.py` L175–188；测试 `test_l0a_price_index_config_rejected` L588–594（含 H00300、000300）。定向绿。 |
| 拒 bars 内异基准混入 | **PASS** | `_check_benchmark_identity` L617–631；`test_l0a_mixed_benchmark_or_source_strictly_selected` L563–571。 |
| **不完整 / 非唯一 `source_snapshot_id`** | **代码 PASS / 测试缺证据** | 实现 L191–206：`len(snaps)!=1` 或空串 → `BENCHMARK_SNAPSHOT_INVALID`。探针：`multi_snap` / `empty_snap` 均产生该码。**`test_m3_readiness.py` 全文无 `BENCHMARK_SNAPSHOT_INVALID`。** |
| **raw 510300** | **缺证据（语义未钉死）** | 若指裸码 `510300`（无 `.SH`）：代码经 `!= _M3_BENCHMARK` 报 `BENCHMARK_SYMBOL_MISMATCH`（探针确认），但无对应用例。若指“未复权 raw OHLC / 探针 raw 冒充 clean 总回报代理”：readiness **不**校验 snapshot 是否为五 response 闭包哈希，也无 adj 经济门禁 → **合同意图下偏 FAIL**。 |
| **身份漂移（snapshot 内容）** | **FAIL（相对合同字面“身份不匹配/漂移”）** | 唯一且非空的伪造 `source_snapshot_id="forged-not-five-response-closure"` **不**触发 `BENCHMARK_SNAPSHOT_INVALID` 或任何 SYMBOL/IDENTITY 码（本轮探针：`forged_snap_identity_codes []`）。readiness 只保证“唯一非空字符串”，不绑定正式五 response canonical snapshot。 |

---

## 2. 未覆盖对抗性反例（至少一条；只报告，不写测试）

### 反例 A（主推）：伪造唯一 snapshot 仍过 readiness

**现象：** `benchmark=510300.SH`、OHLC 合法、`source_snapshot_id` 全局唯一但内容为任意伪造串时，`audit_m3_readiness` 不报 snapshot/身份类 ERROR。

**根因：** `readiness.py` L191–206 仅检查集合基数与非空，不对照五 `(endpoint, request_id, stable_response_sha256)` 闭包哈希。

**应遵循规则：** B1B §2.2 / §5 — clean `source_snapshot_id` 必须是五正式 response 身份的 canonical SHA-256；readiness 对不完整 snapshot **或身份不匹配** fail closed。

**最小复现：**

```python
# benchmark_bars.source_snapshot_id 全为 "forged-not-five-response-closure"
# 期望：BENCHMARK_SNAPSHOT_INVALID 或等价身份不匹配
# 实际：无 SNAPSHOT/SYMBOL/IDENTITY 类错误（本审计探针已复现）
```

**通过条件：** readiness（或上游唯一入口）在已知期望 snapshot 时拒绝漂移；至少增加“双 snapshot”“空 snapshot”“伪造唯一 snapshot”三测。

### 反例 B（3190）：恒真算术冒充生产闭包

见 §1.1；可在实现返工中用真实 `N` 替换恒真式。

### 反例 C（planning 断言缺口）：只测 mode 不测 method/div

构造/读回 `G1StaticPlanV1` 后仅 assert `benchmark_mode`；若回归中 method/div 写入被删但字面量仍由 `G1BuildSpec` 默认路径带入，planning 测试仍绿，却削弱“显式进入 static identity”的回归网。

---

## 3. 性能：既有重 fixture vs B1B 复杂度

| 类别 | 说明 |
|---|---|
| **既有重 fixture** | `test_release_identity_stable_under_row_shuffle`（及同模块 `prepared`/`happy_candidate`）依赖 `test_m3_reference._build_inputs` → `build_g1_candidate` → 公司行动选择/对账与大量 Pandera Polars coerce。任务单已记 setup≈171s、call≈111s、海量 warning。这是 P4 跨源/候选全链 fixture 成本，**不是**本分片应用“削弱 Schema/缩合同”换速度的理由。 |
| **B1B 增量** | fixture 路径已改为 `plan_g1_etf_history_requests` + fund_* 帧（`test_m3_reference.py` L375–453、L360–362）。相对旧 `index_daily` 多 3 个 `fund_adj` 分段响应，属小增量；**主耗时仍在既有 CA/Pandera 重路径**。 |
| **本轮逻辑/证据缺口（非性能）** | 3185/3190 未真实计数；readiness snapshot 身份未绑定；planning 缺 method/div 断言。这些应用测试补合同，**禁止**靠缩小业务闭包或跳过 Schema 加速。 |

---

## 4. 分项总表（R2B 必核清单）

| # | 合同点 | 判定 |
|---|---|---|
| 1 | 旧证券 request_id 不变（相对 legacy 剥离 index_daily） | **PASS**（玩具规模有测） |
| 2 | 新 plan 无 H00300 / 无 index_daily | **PASS** |
| 3 | 正式闭包精确 3190（及 3185 equity） | **缺证据** |
| 4 | 三 benchmark 身份进 build spec / manifest / hash（代码） | **PASS** |
| 5 | 同上（测试完备） | **缺证据** |
| 6 | 当前 publish 只生成严格 v2 | **PASS** |
| 7 | 历史 v1 严格读；混合/缺/伪造 method fail closed | **PASS** |
| 8 | readiness 拒旧 H00300 等 | **PASS** |
| 9 | readiness 不完整 snapshot | **代码 PASS / 测试缺证据** |
| 10 | readiness raw 510300 / snapshot 身份漂移 | **缺证据 / FAIL**（伪造唯一 snapshot 可通过） |

---

## 5. 给主 Agent 的合流提示（非 Gate 结论）

建议冻结给后续外部实现白名单的**最小缺口**（本审计不改代码）：

1. readiness：多 snapshot、空 snapshot、**伪造唯一 snapshot** 的 fail-closed 与测试；明确“raw 510300”是裸码、未复权冒充，还是非闭包 snapshot。
2. planning/backfill：用权威 `history_symbols` 证明 `3185+5=3190`，删除/降级恒真算术断言。
3. planning 测试：显式 assert `build_spec.benchmark_method_version` 与 `benchmark_dividend_reconciliation_version`；可选：manifest/primary payload 含三字段的哈希差分。

**本报告不是独立初验，也不宣布 B1B 或 G1 Gate 通过。**
