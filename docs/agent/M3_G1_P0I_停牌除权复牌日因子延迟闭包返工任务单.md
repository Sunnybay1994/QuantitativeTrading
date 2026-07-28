# M3 G1 P0I：停牌除权复牌日因子延迟闭包返工任务单

状态：**设计已冻结，待外部实现 → 外部独立初验 → 主 Agent 终验**

日期：2026-07-28（Asia/Shanghai）

## 1. 目标与正式证据

P0H 主验通过后，WSL `base` 正式 `status` 的 candidate build 首错为：

```text
M3G1ExecutionFactError:G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED
```

零网络、生产等价的逐跃迁探针定位到第一条真实反例：

```text
symbol=600717.SH
ex_date=2026-06-18
cash_per_share_gross=0.102
FULL_DAY=2026-06-10,11,12,15,16,17,18,22
first_resume_session=2026-06-23
previous_close=4.31
resume_pre_close=4.21
factor(2026-06-18)=34.8547
factor(2026-06-22)=34.8547
factor(2026-06-23)=35.6826
```

计算证据：

```text
ex-date actual = 1.0
resume actual = 35.6826 / 34.8547 = 1.0237528941577463
declared = 4.31 / (4.31 - 0.102) = 1.0242395437262357
resume declared relative error = 0.0004751325717409216 < 0.001
resume market = 4.31 / 4.21 = 1.02375296912114
resume market relative error ≈ 7.32e-08 < 0.001
```

Tushare 在连续全天停牌期间保持复权因子不变，并在首个复牌交易日体现除权跃迁。现实现把 ledger
事件只绑定到精确 `ex_date`，因此在 2026-06-18 用 `actual=1.0` 强制解释完整现金分红并失败，且在
2026-06-23 又会把真实跃迁视为“无事件跳变”。根因是停牌期间事件与复牌日因子生效时点的合同缺口，
不是 raw、journal、公司行动 selector 或容差问题。

诊断产物（ignored，不进入生产身份）：

- `artifacts/g1_component_diag_20260722/formal_audit_diag_p0i.summary.json`
- `artifacts/g1_component_diag_20260722/recon_unexplained_p0i.json`

## 2. 冻结合同

### 2.1 精确日优先

每个 ledger 事件仍先尝试绑定其精确 `ex_date` 的相邻因子跃迁。以下既有行为必须保持：

- 非 `FULL_DAY` 的事件只允许在精确 `ex_date` 对账；
- 精确 `ex_date` 已有可支持的因子跃迁并满足现有 declared/market 合同，仍在原日对账；
- `FULL_DAY`、无 daily、且精确日 declared error 已在 `factor_ratio_rtol` 内的
  `MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE` 行为保持；
- 不支持的下降比例、非停牌日缺 daily、market/declared 超差等原有 fail-closed 语义不放宽。

### 2.2 唯一允许延迟的条件

仅当事件精确 `ex_date` 同时满足以下条件，才允许把该事件延迟分配：

1. `(ex_date, symbol)` 是 `FULL_DAY`；
2. 精确日没有 daily 行；
3. 精确日相邻因子比例在 `1 ± factor_ratio_rtol` 内稳定；
4. 精确日按现有 declared 公式不能在 `factor_ratio_rtol` 内解释该稳定比例。

不得把任意对账失败宽泛地重试到未来日期。

### 2.3 延迟目标

延迟目标必须是从 `ex_date` 向后、同一 symbol 的**首个非 `FULL_DAY` SH 交易日**，并满足：

- `ex_date` 至目标日前的每一个 SH 交易日均为该 symbol 的 `FULL_DAY`；
- 这些交易日在当前 factor scope 中均有因子观测，不允许跨越缺失因子日期；
- 目标日在当前 factor scope 中有因子观测、bar 和已验证 daily 投影；
- 目标必须在当前 history 与 factor scope 内；无目标时 fail closed；
- 目标日使用其相邻因子比例、daily `pre_close` 和目标日前最后一个实际 bar close 执行现有
  declared/market 对账。

600717.SH 必须唯一分配到 2026-06-23；2026-06-18 至 2026-06-22 的稳定跃迁证据保持
`NO_EVENT_STABLE_FACTOR`。

### 2.4 聚合、闭包与确定性

- 同一连续 `FULL_DAY` 区间内发生的多个事件全部且仅一次聚合到同一个首个复牌日；
- 若复牌日本身也有精确日事件，与延迟事件在该跃迁行合并对账；
- 聚合继续按 `event_id` 排序，`event_ids_json`、`event_ids_sha256`、金额、送股和配股字段沿用现有
  规范化与 `math.fsum` 规则；
- evidence 的 `effective_date` 是实际因子跃迁/复牌日；原始事件日期继续由不可变 `event_id` 回连
  ledger，不新增平行日期字段；
- 每个相邻因子跃迁仍恰好生成一行 evidence；事件不得重复、丢失或落入无事件分支；
- 输入顺序不得影响 evidence 排序、hash 或结果；
- 若首个非 `FULL_DAY` 日缺 daily/bar、因子仍稳定而无法解释累计事件、比例不支持或误差超限，
  统一保持 `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`；
- calendar/factor/suspension 结构损坏继续使用既有 `*_INVALID` 失败语义，不泄露路径或凭据。

### 2.5 身份版本与不变项

对账时点语义改变，必须将：

```text
tushare_factor_daily_preclose_v5
```

升级为：

```text
tushare_factor_daily_preclose_suspension_resume_v6
```

由此自然触发的 build code version、candidate key、REFERENCE 抽样及下游 release 身份变化是预期行为；
旧 REFERENCE/PREPARE/PUBLISH 身份不得复用。

以下保持不变：

- `CorporateActionReconciliationSchema` 字段和 status 集合；
- 公司行动 selection version `tushare_dividend_cninfo_rights_capital_iso_date_v5`；
- Tushare/CNINFO connector、raw、receipt、journal、请求计划和网络行为；
- factor ratio 容差数值及 declared/market 公式；
- CLI、配置、正式 `data/` 和不可变发布原语。

## 3. 实现白名单

外部实现 Agent 只可修改：

- `src/quant/data/m3_execution_facts.py`
- `tests/unit/test_m3_execution_facts.py`
- `tests/unit/test_m3_g1_candidate.py`（仅版本身份断言或必要的 candidate 回归）
- `docs/agent/M3_G1_P0I_停牌除权复牌日因子延迟闭包返工交付报告.md`

禁止修改 Schema、connector、CLI、配置、正式 `data/`、既有交付/验收报告和路线图。

## 4. 必须新增或修订的测试

1. 精确复现 600717 形状：连续 `FULL_DAY`、ex-date 因子稳定、首个复牌日跳变；证明事件仅绑定复牌日，
   declared/market 均在 rtol 内，verify 与 hash 自证通过。
2. 连续停牌区间内两个不同 ex-date 事件聚合到同一复牌日，event ID 集合完整且无重复。
3. 复牌日本身另有事件时，与延迟事件合并且总额/比例只计算一次。
4. `FULL_DAY` 精确日已有可解释跃迁时仍在精确日匹配，不延迟。
5. `FULL_DAY`、无 daily、稳定因子且 declared error 在 rtol 内的既有 P0E 行为不回退。
6. 非 `FULL_DAY` 事件不允许延迟。
7. 连续停牌直到 factor/history scope 结束、首个非停牌日缺 factor、缺 daily/bar、目标因子仍稳定且
   declared 超差、目标比例下降或误差超限，分别 fail closed。
8. 中间存在非 `FULL_DAY` 日时不得越过它寻找更晚跳变；首个复牌日不能解释即失败。
9. 延迟 evidence 的 `event_ids_json`、count 或 digest 被篡改时 verifier 拒绝。
10. 输入事件、停牌、bar、factor 顺序反转后结果与 digest 不变。
11. 版本常量精确等于 `tushare_factor_daily_preclose_suspension_resume_v6`，candidate 身份使用新版本。
12. 现有 dividend、rights、无事件稳定、无事件跳变、窗口边界和 P0E/P0H 回归继续通过。

## 5. 验收命令

Windows 原生反馈环：

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_execution_facts.py tests/unit/test_m3_g1_candidate.py -q
D:\Miniforge3\python.exe -m ruff check src/quant/data/m3_execution_facts.py tests/unit/test_m3_execution_facts.py tests/unit/test_m3_g1_candidate.py
D:\Miniforge3\python.exe -m mypy src/quant/data/m3_execution_facts.py
git diff --check <冻结提交> -- <白名单>
```

外部独立初验必须使用另一全新 `cursor-grok-4.5-high` 会话；生产代码和实现者测试只读，只能写自己的
唯一初验报告，并至少增加一个实现者未使用的内存对抗反例。

主验阶段：

- Windows 与 WSL `base` 定向回归；
- 用不可变正式 receipts 做零网络 production-equivalent candidate build；
- 再执行正式 `status`，确认 HISTORY/candidate 的下一真实状态；
- 本任务不自行宣称 G1 Gate、REFERENCE、PREPARE、PUBLISH 或 Linux publish Gate 通过。

## 6. 通过条件

- 600717 的真实停牌除权在首个复牌日唯一闭包；
- 延迟条件严格受限，不把一般对账失败变成未来日期搜索；
- 连续停牌、多事件、复牌日并发事件和无复牌边界满足全量闭包；
- 既有正常交易日、精确停牌日对账、失败语义、Schema 和 verifier 不回退；
- 版本身份正确升级；
- 白名单、测试、静态检查、外部独立初验和主验全部通过。
