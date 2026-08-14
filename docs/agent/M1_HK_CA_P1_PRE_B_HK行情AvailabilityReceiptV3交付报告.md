# M1-HK-CA-P1-PRE-B：HK 行情 Availability Receipt v3 交付报告

日期：2026-08-09  
角色：实现 Agent  
状态：实现与自测完成，等待独立初验；本报告不宣布 Gate

## 1. 交付边界

本轮只实现开发合同与临时 fixture 路径，没有读取、迁移或修改正式 02983/01065 plan、journal、data 或
artifact，也没有发起网络请求。legacy `hk-history-finalize-v1/v2` 保持原字节与行为；仅 raw bytes 的 HKEX
调用仍生成 v2，且 `load_verified_hk_bar_bundle` 明确返回
`HK_HISTORY_AVAILABILITY_UNSUPPORTED`。

## 2. 实现摘要

- 新增 strict `HkBarAvailabilityEvidenceSchema`：exact HK key、UTC availability、三类 retained source、
  request nullable 互斥、逐行 SHA-256 与唯一键。
- 新增 canonical `HKEXDailyQuotationRetainedMetadata` 与 exact-type
  `VerifiedHKEXDailyQuotationRetainedBundle`。verifier fresh 绑定 retained raw、metadata canonical bytes、
  report date、HK market、source record、raw hash 与 metadata identity；旧 raw-only verified 类型不能进入 v3。
- `finalize_hk_history` 新增与 legacy 参数互斥的 `hkex_retained_bundle` 窄入口。v3 fresh 投影 seed/request
  metadata `fetched_at` 与 HKEX `source_observed_at`，建立 exact key→source availability；来源重叠、缺失、
  receipt/raw/metadata drift 均 fail closed。
- v3 journal 固定独占留存 `hkex-retained.raw`、`hkex-retained.metadata.json`、`availability.json`、
  `finalize.json`。四文件 no-clobber 写入失败会回滚本进程已创建文件；竞争者已创建文件不会被误删。
  finalize v3 绑定 clean、availability、seed、全部 request receipts 与 HKEX bundle 的 exact digest/identity。
- 新增 `load_verified_hk_bar_bundle` / `verify_hk_bar_bundle`：只接受 v3，fresh 重验所有 retained source、
  clean exact partitions/keys、availability 与 as-of；拒绝非 HK、`adj_factor != 1`、future availability、
  whole-rehash、复制/替换/symlink/reparse root。capability exact-type、final、不可 pickle，使用进程内 HMAC，
  public verifier 不信缓存并完整重建。

## 3. 测试覆盖

新增或扩展的反例包括：

- metadata non-canonical、market/source/date/raw identity 漂移；
- legacy v1/v2 capability 签发、future availability、request metadata drift；
- seed/request/HKEX exact source 映射、跨来源重复、缺失与 nullable 互斥；
- whole-rehashed clean、普通对象冒充 capability、root copy/replacement；
- v3 中途写失败的 rollback/no half receipt；
- 两证券连续三日、01065 no-trade 与 02983 HKEX supplement 的 7-bar 最小全链 fixture。

## 4. 验证证据

Windows 原生 Miniforge：

- 定向 Ruff：通过；
- 定向 mypy：`Success: no issues found in 4 source files`；
- 定向 pytest：`109 passed, 1 skipped`。skip 是既有 official retained raw 条件，不影响 synthetic v3 合同矩阵。

WSL Miniforge `base`：

- 定向 Ruff：通过；
- 定向 mypy：`Success: no issues found in 4 source files`；
- 定向 pytest：`110 passed`。

WSL worktree 位于 `/mnt/f` DrvFS；以上只证明双平台开发合同，不表述为 ext4/Linux Gate。

## 5. 变更文件

严格位于任务白名单：

- `src/quant/domain/schemas.py`
- `src/quant/domain/__init__.py`
- `src/quant/data/hkex_daily_quotations.py`
- `src/quant/data/hk_history_backfill.py`
- `tests/unit/test_schemas.py`
- `tests/unit/test_hkex_daily_quotations.py`
- `tests/unit/test_hk_history_backfill.py`
- 本报告

没有 add/commit。worktree 中 P0、02983、P1-PRE 及 U0C 的既有脏文件均原样保留。

## 6. 剩余边界

- 本包没有为正式 02983 journal 生成 v3；正式 migration/finalize 必须另立授权并使用新 journal/release identity。
- `bar_available_at` 仅表示 retained-observation time，不表示官方最早发布时间，也不替代信号/成交时序。
- 本包只解锁后续 P1 total-return 输入的开发 capability；不证明 01065、真实 HK 公司行动、HK60、ext4
  或 M1 Gate。
