# M1 HK-HISTORY R3：02402 停复牌区间 No-Trade 证据独立复验报告

日期：2026-08-15
复验模型：`cursor-grok-4.6-high`
状态：PASS
任务书：`docs/framework/agent/M1_HK-HISTORY_R3_02402停复牌区间NoTrade证据任务单.md`
交付报告：`docs/framework/agent/M1_HK-HISTORY_R3_02402停复牌区间NoTrade证据交付报告.md`

## 独立性与范围

- 未参与实现，使用独立全新上下文：是
- 模型如实记录为 `cursor-grok-4.6-high`，不声称其他底层模型。
- 只读审查生产代码、实现测试、任务书和交付报告；未修改生产、测试、任务书、交付报告或任何业务产物。
- 本会话唯一写入：本报告。
- 未联网、未读取 ignored token、未 add/commit/push、未物化 `data/` / `artifacts`。
- 评价范围仅限 `HKNoTradeEvidenceSchema` / UA-M1-004 及相关 UA-M1-001 回归。`src/quant/domain/schemas.py` 中并发存在的 `DailyBasic1dSchema` 及其他会话脏改不计入本合同，亦未删除、格式化或改写该内容。

检查的代码、diff、测试和产物：

- `src/quant/data/hk_history_backfill.py`（UA-M1-001/004 分支、raw verifier、dataclass `__post_init__`、plan v2 公共签名）
- `src/quant/domain/schemas.py` 中 `HKNoTradeEvidenceSchema.user_approved_consensus_is_exactly_scoped`
- `tests/unit/test_hk_history_backfill.py` 新增 UA-M1-004 用例与既有 v2/v3/recover 邻接
- 任务书与交付报告合同对照
- 实现者未使用的临时对抗探针（退出前已删除）

## 目标文件 SHA256（开始 / 结束）

审查期间三份目标文件哈希未变，无并发漂移，可在固定目标上判 PASS。

| 文件 | 开始 SHA256 | 结束 SHA256 |
| --- | --- | --- |
| `src/quant/data/hk_history_backfill.py` | `AF897BF8423F1F72E3DCF296C634364FF5BF0DD2140A69343F4696C355668930` | 同左 |
| `src/quant/domain/schemas.py` | `34DEF079F1E4F473C7ED4A037BD41B33AF497BAC85B31CAE488C4768E9972A69` | 同左 |
| `tests/unit/test_hk_history_backfill.py` | `AEB51C7DE5A7DACBF17FAF1983F88537999C18751749C469EF09471814DAA5ED` | 同左 |

## 标准—证据—结论

### UA-M1-001 既有 raw / metadata / evidence identity 与 plan 行为不变

- 现象：交付将单 key 硬编码演进为两分支；须保证 01065 合同逐字不变。
- 证据：git diff 显示 UA-M1-001 canonical payload 仅被缩进进 `source_record_id == UA-M1-001` 分支，字段集合与取值未改；identity 仍为去掉 `evidence_sha256` 后的 canonical JSON SHA256。既有 `test_user_approved_no_trade_evidence_is_exactly_scoped` 仍断言 selector/record/01065@2026-05-05 与 plan 只减去该日。独立探针 `ua-m1-001-identity-formula` 与 `mix-ua-m1-001-and-004-same-set` 确认单独加载及与 UA-M1-004 同集共存时，01065 的 identity 与 `effective_expected_dates` 仍只去掉 `2026-05-05`。
- 结论：通过

### UA-M1-004 仅接受 exact 02402.HK、exact 13 日、exact selector/record/source/schema、两条 HKEX URL/观察、Tushare retained-zero-row、exact UTC；05-04 与范围外 key 拒绝

- 现象：任务书冻结 `source_record_id=UA-M1-004`、selector `user-approved-consensus/ua-m1-004-02402-2026-04-01-to-2026-05-04.record`、schema `hk-no-trade-user-approved-suspension-range-v1`、13 日 `2026-04-14,15,16,17,20,21,22,23,24,27,28,29,30`、停牌 `2026-04-01T01:00:00+00:00`、复牌 `2026-05-04T01:00:00+00:00`、两条 HKEX URL 与 `RETAINED_ZERO_ROW`；`2026-05-04` 不是 no-trade。
- 证据：生产常量与 `_user_approved_suspension_range_payload()` 重建的 canonical dict 与任务书一致。实现测试覆盖 04-13、05-04、其他 symbol/record/selector/source、URL/观察/日期增删换序、raw/metadata hash 漂移。独立探针额外拒绝 04-01、04-18 周末、`+08:00` 等价瞬时、`Z` 后缀、交换两条 HKEX URL、`source_kind` 漂移、Tushare 观察加 URL、raw 重复日期、额外字段。canonical raw 字节与 `_canonical_json(payload)` 一致。
- 结论：通过

### dataclass 与 Pandera schema 范围一致；raw verifier 重建 canonical payload；未知 record fail closed

- 现象：不得一处放宽、一处收窄；未知 `source_record_id` 必须拒绝。
- 证据：`HKNoTradeEvidence.__post_init__` 经 `_user_approved_no_trade_is_exact` 约束 UA-M1-001 单日与 UA-M1-004 的 13 个 ISO 日；`HKNoTradeEvidenceSchema` dataframe check 使用同一 13 个 `dt.date` 与同一 selector/record。探针 `date-set-sync` 核对 dataclass 常量、schema 列表与测试夹具三方一致。`_verify_user_approved_no_trade_raw` 按 record 分支重建 expected，并以 `value != expected or payload != canonical bytes` fail closed；未知 record 走 `else: raise ValueError`。探针 `unknown-record-verifier-fail-closed`、`schema-rejects-05-04`、`schema-rejects-04-01` 通过。
- 结论：通过

### evidence 少/多/重复、日期换序、URL/观察/metadata/raw/hash 漂移、hostile JSON/type/path 拒绝且公共 cause/context 为空

- 现象：任务书要求这些反例拒绝或使 plan 不能满足 exact 13 日投影；公共失败脱敏。
- 证据：少一被 loader 接受但 plan `effective_expected_dates` 仍留下最后一日（符合“拒绝或不能满足 exact projection”）；多一 05-04 与重复 key 被 loader 拒绝；raw `no_trade_dates` 换序拒绝。hostile 用例断言公共码为 `HK_HISTORY_REFERENCE_INVALID` 且 `__cause__`/`__context__` 为空。独立探针 `noncanonical-pretty-json-rehashed` 在改写 hash 后仍拒绝非 canonical 美化 JSON，证明走的是 payload 重建而非仅 hash 比对。
- 结论：通过

### 不改变 mapper/raw/plan/receipt/public API；现有 v2/v3/recover/no-clobber 邻接不回归

- 现象：只改变 expected-key 证据闭包。
- 证据：白名单 diff 仅触及 backfill 私有常量/分支、`HKNoTradeEvidence.__post_init__` 内部调用、schema 的 user-approved check，以及本任务测试。`load_hk_no_trade_evidence` / `build_hk_history_plan_v2` 等公共签名未改。focused `tests/unit/test_hk_history_backfill.py`：129 passed, 2 skipped，覆盖既有 v2/v3/recover/no-clobber 邻接。
- 结论：通过

## 新增的对抗性反例（实现者未使用）

临时探针路径：`%TEMP%\m1_r3_ua_m1_004_independent_probe.py`（及 `ua_m1_004_probe_*` 工作目录）。退出前已删除；`Test-Path` 为 `False`。

实现者测试覆盖了 04-13/05-04/symbol/record/selector/source、URL 追加 `/drift`、观察文本替换、日期增删换序、raw 追加换行 hash 漂移、metadata 替换、少一/多一/重复、hostile monkeypatch 与 list JSON。下列条目均不在实现者用例中：

| 探针 | 期望 | 结果 |
| --- | --- | --- |
| 证据 key `2026-04-01`（停牌起始日，非 13 开市日） | 拒绝 | PASS |
| 证据 key `2026-04-18`（区间内周末） | 拒绝 | PASS |
| `suspension_at=2026-04-01T09:00:00+08:00`（同一瞬时，非 exact UTC 字符串） | 拒绝 | PASS |
| `suspension_at=...Z` | 拒绝 | PASS |
| 语义相同但 pretty-print 的 raw，并重写全部 hash | 拒绝 | PASS |
| 02402 证据挂 UA-M1-001 record | 拒绝 | PASS |
| 01065@2026-05-05 挂 UA-M1-004 selector/record | 拒绝 | PASS |
| 对调两条 HKEX URL | 拒绝 | PASS |
| `source_kind` `HKEX_NEWS` → `HKEX_NOTICE` | 拒绝 | PASS |
| raw 增加 `approved_on` | 拒绝 | PASS |
| raw `no_trade_dates` 重复第一日（长度 14） | 拒绝 | PASS |
| Tushare 观察额外带 `url` | 拒绝 | PASS |
| 未知 record `UA-M1-000` 直接打 verifier | `ValueError` fail closed | PASS |
| UA-M1-001 与 UA-M1-004 同集共存并同时投影 | 加载成功；01065 只去 05-05，02402 去 13 日且保留 05-04 | PASS |
| schema 直接校验 04-14 接受、05-04/04-01 拒绝 | 与 dataclass 同范围 | PASS |

探针合计 21 PASS / 0 FAIL。拒绝路径的公共异常码均为 `HK_HISTORY_REFERENCE_INVALID`，且 `__cause__`/`__context__` 为空。

## 独立验证命令

| 命令 | 结果 | 摘要 |
| --- | --- | --- |
| `D:\Miniforge3\python.exe -m pytest tests/unit/test_hk_history_backfill.py -q --tb=short` | 通过 | 129 passed, 2 skipped, 103.39s |
| `D:\Miniforge3\python.exe -m ruff check src/quant/data/hk_history_backfill.py src/quant/domain/schemas.py tests/unit/test_hk_history_backfill.py` | 通过 | All checks passed |
| `D:\Miniforge3\python.exe -m mypy src/quant/data/hk_history_backfill.py src/quant/domain/schemas.py` | 通过 | no issues found in 2 source files |
| 临时对抗探针 | 通过 | 21 PASS / 0 FAIL；文件已删除 |

未运行 Linux/WSL Gate（任务书不要求）。Windows 绿测不等于 Linux Gate 已通过。未物化真实 evidence/plan/journal，因此正式 HK60 v2 recover/finalize 仍未关闭。

pytest 过程出现既有 Pandera `how='horizontal'` DeprecationWarning，以及 `.pytest_cache` 写入 Access denied；均不改变本任务合同结论。

## 问题

无。不进入返工。

## 结论

- 初验结果：**PASS**
- 进入主 Agent 最终验收；主 Agent 仍须用本实现的 canonical bytes 物化 02402 retained raw/metadata、13 项 evidence、新 v2 plan，并先零网络 recover 已有 raw。
- 本初验通过只是进入主验的前置，不等于 Gate 关闭。

## 剩余风险（不构成 FAIL）

- dataclass 13 日常量与 Pandera `is_in([...])` 仍是两份字面量；当前探针已核对一致，后续改日必须同步两处。
- 正式业务证据尚未落盘；identity 稳定性取决于主 Agent 物化时使用同一 canonical JSON。
- `schemas.py` 工作树仍含其他会话的 `DailyBasic1dSchema`；主验合流时须把该文件的非本任务 diff 与本任务 UA-M1-004 check 分开验收。
