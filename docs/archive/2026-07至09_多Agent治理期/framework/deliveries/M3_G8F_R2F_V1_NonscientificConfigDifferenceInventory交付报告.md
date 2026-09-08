# M3-G8F-R2F-V1 Nonscientific Config Difference Inventory 交付报告

日期：2026-08-28<br>
状态：`DELIVERY_READY / NONSCIENTIFIC_DIFFERENCE_INVENTORY_FROZEN / CONTRACT_STOP / USER_CHOICE_REQUIRED`

## 1. 身份、范围与结论

- task id：`M3-G8F-R2F-V1-NONSCIENTIFIC-CONFIG-DIFFERENCE-INVENTORY`
- exact base / HEAD：`2c2fe86ebd3eba1a77f3728414404dc8e9358ac8`
- taskbook SHA-256：`a58bdc77aa258243a6fd3399bbf8be6d10df3d03c4f8106cbbea50d7551c0eba`
- 唯一写路径：本交付报告。
- 执行类型：tracked-only `STATIC_ONLY / CPU NONE`。

审计完整覆盖 `_field_specs()` 的 `148/148` 个 field shape。结论是：存在三个有业务正当性、但仍必须由 owner
逐字段逐值决定的候选：`g1_backfill.request_rate_per_minute`、`g1_backfill.max_attempts`、
`g1_backfill.retry_base_seconds`。三者是源码明确排除于所有 derived selector 的 G1 获取执行策略，分别控制请求速率、
最大尝试次数和重试退避；它们可表达两个独立 G1 获取 lane 的真实 API 配额/可靠性策略，而不改变 config 的
scientific、snapshot、g1、provider、validation、acceptance 或 tracking-target derived identity。它们会进入
`G1StaticPlanV1` 及其 `_static_plan_sha256`，所以 future 选择还必须证明每个值与对应既存 G1 release lane 的真实获取策略
一致，不能把 formal config 写成与 release 历史不符的事后标签。当前没有任何正式值、lane 映射或 release-policy binding
SSOT，因此本 Worker 不选择值，终态严格保持：

`CONTRACT_STOP / USER_CHOICE_REQUIRED`

其余 21 个 technically variable non-scientific 字段均拒绝作为造差异来源：它们或者只是无消费语义的说明，或者会改变
数据/质量/acceptance/tracking/root 闭包，或者已有 public consumer 要求 true/shared/exact join。固定 literal 和 scientific
字段更不可能作为候选。

## 2. tracked 锚点

| 路径 | HEAD Git blob | working SHA-256 | 审计用途 |
|---|---|---|---|
| `src/quant/research/m3/config.py` | `6d60d8827a803453bb26868208929d3c31960dbd` | `7338ab6a6b959f3a8556bf8011aa6898580df434f920ae167dc8d27f966fedfa` | 148 shapes、normalization、projection/hash、cross-field |
| `src/quant/research/m3/successor_runtime.py` | `59212daf87a3b8f44052e27f1a68abe1cef8f5c9` | `272c42f63612e2ce4e927460c1885e95cdab9c17e3d13f52bd82d9734caf608b` | raw/full=2、scientific=1、shared stage root |
| `src/quant/research/m3/successor_bridge.py` | `09d8b3b267ea30fc0764d5734d4636722f5ed22b` | `64474646d671164435bddd572a9cbd9d626943d1a7242382d05bd32d8d98ea69` | fresh config、tool exact equality、root exact equality |
| `src/quant/research/m3/g1_planning.py` | `3367f05218f3441cf371e2bb8fd06de1b0ba8ad1` | `3a1a21694bfa0c451eb0d0ab2b32c068bffd3b585ccd68c6c2a18bb69e1fbadd` | G1 rate/retry、tail、reconciliation consumers |
| `src/quant/research/m3/acceptance_work.py` | `f0d838d44c286434c4468d255deb41e5dc25a169` | `61a0d496e8d3d4259ee98cfa235f4870e29543ff825119ad084dcc70cee114c9` | acceptance threshold consumers |
| `src/quant/research/m3/tracking.py` | `001516b3d5e2d32082322ffc6e6b322d0a4f8626` | `c667eaff30416be0c14cc5c088b8c4fb5f6719f051917a71df6a5ee6aafa50ef` | canonical tracking target/consumer joins |
| `src/quant/research/m3/fetch_qlib_tool.py` | `b91b63fea7cad3d5866af63ed2afc13524708a12` | `33342e5f487fab59fd760dd01fcde961df88f04e58e0e73c8a47ca26e59a15c3` | runtime Qlib tool spec consumer |

未读取 example 的具体值，也未读取 LOCKED、ignored/local 或真实 data。

## 3. projection 与 hash 证明

`load_m3_config` 对 exact UTF-8 TOML bytes 直接取 SHA-256，得到 raw identity；同一 bytes 经 strict schema、类型、
literal/range/cross-field 校验后形成 normalized document。`full` 的 payload 是整个 normalized document；其他 selector 的
payload 由 `_project` 遍历 assignment leaves，只保留 spec 含该 selector 的字段。`meta.config_version` 特殊地不重复进入
payload，但进入每个 canonical envelope 的 `config_version`。因此：

- 每个合法字段都进入 raw 与 full；只有 selector 含 `scientific` 的 88 个 shape 进入 scientific payload。
- 注释/空白只改变 raw，不改变 normalized full，无法满足 runtime 的两个 full identities。
- runtime `_validate_request` fresh reload 两 config，要求 raw set size=2、full set size=2、scientific set size=1。
- bridge 对两 config 的 `build_qlib_dump_tool_spec` 要求 exact 相等；两份 `tracking.artifact_root` 还必须解析到同一个
  既存 PROJECT-only controlled root。
- `tracking.experiment_name` 与 canonical URI 另算 `tracking_target_key`；它不是 scientific hash 的替身。

direct join 闭包如下：

| identity / consumer | public join | two-fold 含义 |
|---|---|---|
| raw/full | bridge fresh bytes+loader 校验 request SHA；runtime 再 fresh reload | 两 lane 各自 distinct，且绑定各自 config path |
| scientific | successor work/summary manifests 与 `_validate_request` | exact one shared；summary 明确以 scientific join 并取首 config |
| g1/snapshot | G1 planning、snapshot/release artifacts | 可 per-lane，但任何差异必须与各自 verified release/artifact closure 相符 |
| provider | provider build/tool inputs | Qlib dump tool spec 在 bridge 对两 config exact 相等 |
| provider-validation | provider validation manifests/stages | 不能靠不同验证样本/策略制造 lane hash；当前字段均 literal |
| label-reconciliation | label spec/result/acceptance upstream | tolerance 直接决定 pass/fail，不能 lane-specific 松紧 |
| acceptance | reproducibility/coverage/IC Gate 与 summary/downstream acceptance | aggregate Gate 必须同口径，不能 lane-specific 松紧 |
| tracking-target | canonical URI+experiment → target key；tracking stages/markers | 不同 target 会拆散 run/marker/summary 闭包，不是可替代的 lane identity |
| artifact root | `project_stage_root` + bridge set-size=1 | 两 config 必须解析到同一既存 controlled root |

selector 分类计数（字段可同时属于多个 selector）：`full/raw=148`，`scientific=88`，`g1=30`，`snapshot=14`，
`provider=5`，`provider-validation=5`，`label-reconciliation=5`，`acceptance=9`，`tracking-target=2`，
无 derived selector=`13`。按 scientific 二分为 `88 scientific + 60 non-scientific = 148`。

## 4. 148/148 field-shape / projection / consumer 矩阵

记号：`R`=required，`O`=optional；约束列的 `lit` 是 fixed literal，区间的方/圆括号表示 inclusive/exclusive；
`Sel` 是 derived selector（`—` 表示无 derived selector）；所有行 `raw=Y/full=Y`，`Sci` 单列说明 scientific；
`Eq/结论` 表示 two-fold 额外约束或候选判定。consumer 缩写：`CFG` loader/hash，`G1` planning/workflow，`SNAP` snapshot，
`PROV` provider/tool，`SCI` feature/label/model/portfolio/backtest/evaluation/cost stages，`PV` provider validation，
`LR` label reconciliation，`ACC` acceptance，`TRK` tracking，`ROOT` bridge/runtime stage root。

### 4.1 meta / data / runtime / features / labels（34/148）

| # | path | kind | R/O；literal/range | Sel | Sci | public consumers；Eq/结论 |
|---:|---|---|---|---|:---:|---|
| 1 | `meta.config_version` | string | R; lit=`1.0.0` | g1,snapshot,provider,scientific,provider-validation,label-reconciliation,acceptance | Y | CFG envelope；literal exact |
| 2 | `meta.purpose` | string | R; non-empty | — | N | CFG only；拒绝：无行为 consumer，以文字制造 lane identity 重复 request-side fold |
| 3 | `meta.enabled` | bool | R | — | N | acceptance_upstream 要求 `True`；两 fold 必须 true，拒绝 |
| 4 | `data.universe` | string | R; lit=`CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1` | snapshot,scientific | Y | SNAP/SCI；scientific exact |
| 5 | `data.benchmark` | string | R; lit=`510300.SH` | snapshot,scientific | Y | SNAP/labels/evaluation；scientific exact |
| 6 | `data.source` | string | R; lit=`tushare` | snapshot,scientific | Y | SNAP/G1；scientific exact |
| 7 | `data.start_date` | date | R | snapshot,scientific | Y | SNAP/SCI/cost coverage；scientific exact |
| 8 | `data.end_date` | date | R; `start<=end` | snapshot,scientific | Y | SNAP/SCI；scientific exact |
| 9 | `data.market` | string | R; lit=`CN` | snapshot,provider,scientific | Y | SNAP/PROV/SCI；scientific exact |
| 10 | `data.frequency` | string | R; lit=`day` | snapshot,provider,scientific | Y | SNAP/PROV；scientific exact |
| 11 | `data.minimum_train_sessions` | int | R; `[1,+inf)` | snapshot,scientific | Y | SNAP/walk-forward (`train>=minimum`)；scientific exact |
| 12 | `data.minimum_cross_section_symbols` | int | R; `[2,+inf)`; `<=expected_constituent_count` | snapshot,scientific | Y | SNAP/portfolio (`top_k<=minimum`)；scientific exact |
| 13 | `data.required_fields` | str_array | R; lit=`(open,high,low,close,volume,amount,adj_factor)` | snapshot,scientific | Y | SNAP schema；scientific exact |
| 14 | `data.provider_fields` | str_array | R; lit=`(open,high,low,close,vwap,volume,factor)` | provider,scientific | Y | PROV；scientific exact |
| 15 | `data.provider_format` | string | R; lit=`qlib_bin` | provider,scientific | Y | PROV；scientific exact |
| 16 | `data.snapshot_hash` | string | R; lit=`sha256` | snapshot,scientific | Y | SNAP identity；scientific exact |
| 17 | `runtime.qlib.version` | string | R; lit=`0.9.7` | scientific | Y | PROV/tool；scientific exact |
| 18 | `runtime.qlib.supported_python` | string | R; lit=`>=3.8,<3.13` | — | N | policy/full only；literal exact，拒绝 |
| 19 | `runtime.qlib.dump_script_url` | string | R; lit=`https://raw.githubusercontent.com/microsoft/qlib/v0.9.7/scripts/dump_bin.py` | — | N | PROV/tool spec；bridge 两 spec exact，literal exact |
| 20 | `runtime.qlib.dump_script_sha256` | string | R; lit=`b8f34c57...01fe53f` | — | N | PROV/tool spec；bridge exact，literal exact |
| 21 | `runtime.qlib.dump_script_bytes` | int | R; lit=`21847` | — | N | PROV/tool spec；bridge exact，literal exact |
| 22 | `features.handler` | string | R; lit=`Alpha158` | scientific | Y | SCI feature stage；scientific exact |
| 23 | `features.feature_version` | string | R; lit=`alpha158_v1` | scientific | Y | SCI manifests；scientific exact |
| 24 | `features.expected_feature_count` | int | R; lit=`158` | scientific | Y | SCI coverage/schema；scientific exact |
| 25 | `features.minimum_scorable_coverage` | float | R; `[0,1]` | scientific | Y | SCI readiness；scientific exact |
| 26 | `features.processor_policy` | string | R; lit=`none_raw_features` | scientific | Y | SCI feature processing；scientific exact |
| 27 | `features.missing_value_policy` | string | R; lit=`inf_to_nan_lightgbm_native` | scientific | Y | SCI feature/model；scientific exact |
| 28 | `features.authoritative_label_source` | string | R; lit=`quant_forward_return_label` | scientific | Y | SCI label join；scientific exact |
| 29 | `labels.horizons_sessions` | int_array | R; lit=`(5,10)` | scientific | Y | SCI work/summary；scientific exact |
| 30 | `labels.entry_offset_sessions` | int | R; lit=`1` | scientific | Y | SCI label；scientific exact |
| 31 | `labels.entry_field` | string | R; lit=`open` | scientific | Y | SCI label；scientific exact |
| 32 | `labels.exit_field` | string | R; lit=`close` | scientific | Y | SCI label；scientific exact |
| 33 | `labels.relative_to_benchmark` | bool | R; lit=`True` | scientific | Y | SCI label；scientific exact |
| 34 | `labels.label_version` | string | R; lit=`theoretical_next_open_to_h_close_510300_etf_hfq_proxy_excess_v3` | scientific | Y | SCI label manifests；scientific exact |

### 4.2 G1 / walk-forward（39/148；累计73）

| # | path | kind | R/O；literal/range | Sel | Sci | public consumers；Eq/结论 |
|---:|---|---|---|---|:---:|---|
| 35 | `g1_backfill.index_weight_code` | string | R; lit=`000300.SH` | g1 | N | G1 release；literal exact |
| 36 | `g1_backfill.benchmark_code` | string | R; lit=`510300.SH` | g1 | N | G1 release；literal exact |
| 37 | `g1_backfill.benchmark_mode` | string | R; lit=`TRADEABLE_ETF_TOTAL_RETURN_PROXY` | g1 | N | G1 benchmark；literal exact |
| 38 | `g1_backfill.benchmark_method_version` | string | R; lit=`tushare_510300_fund_daily_fund_adj_hfq_v1` | g1 | N | G1 benchmark；literal exact |
| 39 | `g1_backfill.benchmark_dividend_reconciliation_version` | string | R; lit=`tushare_fund_div_implemented_cash_v1` | g1 | N | G1 benchmark；literal exact |
| 40 | `g1_backfill.membership_method_version` | string | R; lit=`tushare_monthly_observed_next_session_close_v1` | g1 | N | G1 membership；literal exact |
| 41 | `g1_backfill.session_market` | string | R; lit=`SH` | g1 | N | G1 calendar；literal exact |
| 42 | `g1_backfill.expected_constituent_count` | int | R; lit=`300` | g1 | N | G1/readiness cross-field；literal exact |
| 43 | `g1_backfill.membership_warmup_months` | int | R; lit=`1` | g1 | N | G1 coverage；literal exact |
| 44 | `g1_backfill.feature_warmup_sessions` | int | R; lit=`60` | g1,snapshot | N | G1/SNAP coverage；literal exact |
| 45 | `g1_backfill.label_tail_sessions` | int | R; `[1,+inf)`; `>=max(horizons)` | g1,snapshot | N | G1/SNAP coverage；拒绝：改变数据尾部闭包/derived identities，不是纯 lane 执行策略 |
| 46 | `g1_backfill.request_rate_per_minute` | int | R; `[1,+inf)` | — | N | G1 rate limiter/static-plan SHA；**候选 C1**：仅当与对应 release lane 的真实 API 配额一致 |
| 47 | `g1_backfill.max_attempts` | int | R; `[1,+inf)` | — | N | G1 retry loop/static-plan SHA；**候选 C2**：仅当与对应 lane 的可靠性/失败预算一致 |
| 48 | `g1_backfill.retry_base_seconds` | float | R; `[0,+inf)` | — | N | G1 retry backoff/static-plan SHA；**候选 C3**：仅当与对应 lane 的限频退避策略一致 |
| 49 | `g1_backfill.endpoint_row_limits.daily` | int | R; lit=`6000` | g1 | N | G1 endpoint closure；literal exact |
| 50 | `g1_backfill.endpoint_row_limits.adj_factor` | int | R; lit=`6000` | g1 | N | G1 endpoint closure；literal exact |
| 51 | `g1_backfill.endpoint_row_limits.index_daily` | int | R; lit=`5000` | g1 | N | G1 endpoint closure；literal exact |
| 52 | `g1_backfill.endpoint_row_limits.index_weight` | int | R; lit=`5000` | g1 | N | G1 endpoint closure；literal exact |
| 53 | `g1_backfill.endpoint_row_limits.suspend_d` | int | R; lit=`5000` | g1 | N | G1 endpoint closure；literal exact |
| 54 | `g1_backfill.endpoint_row_limits.stk_limit` | int | R; lit=`5800` | g1 | N | G1 endpoint closure；literal exact |
| 55 | `g1_backfill.endpoint_row_limits.dividend` | int | R; lit=`5000` | g1 | N | G1 endpoint closure；literal exact |
| 56 | `g1_backfill.endpoint_row_limits.fund_daily` | int | R; lit=`5000` | g1 | N | G1 endpoint closure；literal exact |
| 57 | `g1_backfill.endpoint_row_limits.fund_adj` | int | R; lit=`2000` | g1 | N | G1 endpoint closure；literal exact |
| 58 | `g1_backfill.endpoint_row_limits.fund_div` | int | R; lit=`5000` | g1 | N | G1 endpoint closure；literal exact |
| 59 | `g1_backfill.reconciliation.reference_source` | string | R; lit=`baostock` | g1 | N | G1 validation；literal exact |
| 60 | `g1_backfill.reconciliation.sample_symbols` | int | R; lit=`30` | g1 | N | G1 validation sample；literal exact |
| 61 | `g1_backfill.reconciliation.dates_per_symbol` | int | R; lit=`20` | g1 | N | G1 validation sample；literal exact |
| 62 | `g1_backfill.reconciliation.price_atol` | float | R; `[0,+inf)` | g1 | N | G1 quality Gate；拒绝：lane-specific tolerance 会改变质量准入 |
| 63 | `g1_backfill.reconciliation.price_rtol` | float | R; `[0,+inf)` | g1 | N | G1 quality Gate；拒绝：同上 |
| 64 | `g1_backfill.reconciliation.volume_rtol` | float | R; `[0,+inf)` | g1 | N | G1 quality Gate；拒绝：同上 |
| 65 | `g1_backfill.reconciliation.max_mismatch_rate` | float | R; `[0,1]` | g1 | N | G1 quality Gate；拒绝：同上 |
| 66 | `g1_backfill.corporate_action_reconciliation.factor_ratio_rtol` | float | R; `[0,0.01]` | g1 | N | G1 corporate-action Gate；拒绝：改变质量准入 |
| 67 | `walk_forward.train_sessions` | int | R; `[1,+inf)`; `>=minimum_train` | scientific | Y | SCI split；scientific exact |
| 68 | `walk_forward.validation_sessions` | int | R; `[1,+inf)` | scientific | Y | SCI split；scientific exact |
| 69 | `walk_forward.test_sessions` | int | R; `[1,+inf)` | scientific | Y | SCI split；scientific exact |
| 70 | `walk_forward.step_sessions` | int | R; `[1,+inf)`; `>=test` | scientific | Y | SCI split；scientific exact |
| 71 | `walk_forward.embargo_sessions` | int | R; `[1,+inf)`; `>=max(horizons)` | scientific | Y | SCI split/PIT；scientific exact |
| 72 | `walk_forward.selection_metric` | string | R; lit=`validation_l2` | scientific | Y | SCI model selection；scientific exact |
| 73 | `walk_forward.test_overlap_policy` | string | R; lit=`ERROR` | scientific | Y | SCI split Gate；scientific exact |

### 4.3 model / portfolio / backtest / evaluation（42/148；累计115）

| # | path | kind | R/O；literal/range | Sel | Sci | public consumers；Eq/结论 |
|---:|---|---|---|---|:---:|---|
| 74 | `model.lightgbm.model_version` | string | R; lit=`alpha158_lgb_v1` | scientific | Y | SCI model/manifests；scientific exact |
| 75 | `model.lightgbm.objective` | string | R; lit=`regression` | scientific | Y | SCI model；scientific exact |
| 76 | `model.lightgbm.metric` | string | R; lit=`l2` | scientific | Y | SCI model；scientific exact |
| 77 | `model.lightgbm.device_type` | string | R; lit=`cpu` | scientific | Y | SCI model/runtime；scientific exact |
| 78 | `model.lightgbm.learning_rate` | float | R; `(0,+inf)` | scientific | Y | SCI model；scientific exact |
| 79 | `model.lightgbm.num_leaves` | int | R; `[2,+inf)` | scientific | Y | SCI model；scientific exact |
| 80 | `model.lightgbm.max_depth` | int | R; `-1 or >0` | scientific | Y | SCI model；scientific exact |
| 81 | `model.lightgbm.feature_fraction` | float | R; `(0,1]` | scientific | Y | SCI model；scientific exact |
| 82 | `model.lightgbm.bagging_fraction` | float | R; `(0,1]` | scientific | Y | SCI model；scientific exact |
| 83 | `model.lightgbm.bagging_freq` | int | R; `[0,+inf)` | scientific | Y | SCI model；scientific exact |
| 84 | `model.lightgbm.num_boost_round` | int | R; `[1,+inf)` | scientific | Y | SCI model；scientific exact |
| 85 | `model.lightgbm.early_stopping_rounds` | int | R; `[1,+inf)`; `<num_boost_round` | scientific | Y | SCI model；scientific exact |
| 86 | `model.lightgbm.early_stopping_min_delta` | float | R; `[0,+inf)` | scientific | Y | SCI model；scientific exact |
| 87 | `model.lightgbm.seed` | int | R; `[0,+inf)` | scientific | Y | SCI determinism；scientific exact |
| 88 | `model.lightgbm.data_random_seed` | int | R; `[0,+inf)` | scientific | Y | SCI determinism；scientific exact |
| 89 | `model.lightgbm.feature_fraction_seed` | int | R; `[0,+inf)` | scientific | Y | SCI determinism；scientific exact |
| 90 | `model.lightgbm.bagging_seed` | int | R; `[0,+inf)` | scientific | Y | SCI determinism；scientific exact |
| 91 | `model.lightgbm.deterministic` | bool | R; lit=`True` | scientific | Y | SCI determinism；scientific exact |
| 92 | `model.lightgbm.force_col_wise` | bool | R; lit=`True` | scientific | Y | SCI determinism；scientific exact |
| 93 | `model.lightgbm.num_threads` | int | R; `[1,+inf)` | scientific | Y | SCI execution/reproducibility；scientific exact |
| 94 | `portfolio.strategy` | string | R; lit=`topk` | scientific | Y | SCI portfolio；scientific exact |
| 95 | `portfolio.strategy_version` | string | R; lit=`m3_topk_v1` | scientific | Y | SCI portfolio identity；scientific exact |
| 96 | `portfolio.top_k` | int | R; `[1,+inf)`; `<=minimum_cross_section_symbols` | scientific | Y | SCI portfolio；scientific exact |
| 97 | `portfolio.cash_buffer` | float | R; `[0,1)` | scientific | Y | SCI portfolio；scientific exact |
| 98 | `portfolio.max_weight` | float | R; `(0,1]` | scientific | Y | SCI portfolio；scientific exact |
| 99 | `portfolio.rebalance` | string | R; lit=`daily_signal_next_session_open` | scientific | Y | SCI portfolio/time semantics；scientific exact |
| 100 | `backtest.a_share.initial_cash` | float | R; `(0,+inf)` | scientific | Y | SCI backtest；scientific exact |
| 101 | `backtest.a_share.price_tick` | float | R; `(0,+inf)` | scientific | Y | SCI backtest；scientific exact |
| 102 | `backtest.a_share.target_omission_means_zero` | bool | R; lit=`True` | scientific | Y | SCI backtest；scientific exact |
| 103 | `backtest.a_share.cash_entitlement_fallback` | string | R; lit=`ERROR` | scientific | Y | SCI fail-closed；scientific exact |
| 104 | `backtest.a_share.stock_entitlement_fallback` | string | R; lit=`ERROR` | scientific | Y | SCI fail-closed；scientific exact |
| 105 | `backtest.a_share.unexplained_factor_change` | string | R; lit=`ERROR` | scientific | Y | SCI fail-closed；scientific exact |
| 106 | `backtest.a_share.partial_suspension_open_policy` | string | R; lit=`REQUIRE_EXPLICIT_OPEN_TRADABLE` | scientific | Y | SCI market rule；scientific exact |
| 107 | `backtest.a_share.dividend_tax_policy` | string | R; lit=`GROSS_IGNORE_PERSONAL_HOLDING_PERIOD_TAX` | scientific | Y | SCI market rule；scientific exact |
| 108 | `backtest.a_share.rights_policy` | string | R; lit=`ERROR_IF_RELEVANT` | scientific | Y | SCI fail-closed；scientific exact |
| 109 | `backtest.a_share.force_liquidation` | bool | R; lit=`False` | scientific | Y | SCI backtest；scientific exact |
| 110 | `backtest.a_share.friction_multipliers` | float_array | R; lit=`(0.5,1.0,2.0)` | scientific | Y | SCI scenarios；scientific exact |
| 111 | `backtest.a_share.execution_price_rounding` | string | R; lit=`BUY_CEIL_SELL_FLOOR_TICK_V1` | scientific | Y | SCI rounding；scientific exact |
| 112 | `backtest.a_share.fee_rounding` | string | R; lit=`EACH_COMPONENT_HALF_UP_CENT_V1` | scientific | Y | SCI rounding；scientific exact |
| 113 | `backtest.a_share.cash_settlement_rounding` | string | R; lit=`HALF_UP_CENT_V1` | scientific | Y | SCI rounding；scientific exact |
| 114 | `backtest.a_share.annualization_sessions` | int | R; lit=`252` | scientific | Y | SCI metrics；scientific exact |
| 115 | `evaluation.minimum_ic_symbols` | int | R; `[2,+inf)` | scientific | Y | SCI evaluation；scientific exact |

### 4.4 validation / costs / tracking / acceptance（33/148；累计148）

| # | path | kind | R/O；literal/range | Sel | Sci | public consumers；Eq/结论 |
|---:|---|---|---|---|:---:|---|
| 116 | `validation.provider.sample_symbols` | int | R; lit=`3` | provider-validation | N | PV sample closure；literal exact |
| 117 | `validation.provider.sample_dates_per_symbol` | int | R; lit=`20` | provider-validation | N | PV sample closure；literal exact |
| 118 | `validation.provider.gap_dates_per_symbol` | int | R; lit=`5` | provider-validation | N | PV sample closure；literal exact |
| 119 | `validation.provider.sampling_policy_version` | string | R; lit=`provider_market_stratified_hash_first_last_v1` | provider-validation | N | PV sampling identity；literal exact |
| 120 | `validation.labels.reconciliation_version` | string | R; lit=`qlib_raw_plus_independent_benchmark_v1` | label-reconciliation | N | LR identity；literal exact |
| 121 | `validation.labels.qlib_expression_atol` | float | R; `[0,+inf)`; `<=label_return_atol` | label-reconciliation | N | LR quality Gate；拒绝：lane-specific tolerance 改变准入 |
| 122 | `validation.labels.benchmark_return_atol` | float | R; `[0,+inf)`; `<=label_return_atol` | label-reconciliation | N | LR quality Gate；拒绝：同上 |
| 123 | `validation.labels.label_return_atol` | float | R; `[0,+inf)` | label-reconciliation | N | LR quality Gate；拒绝：同上 |
| 124 | `costs.schedule_version` | string | R; lit=`a_share_research_cost_schedule_v1` | scientific | Y | SCI cost identity；scientific exact |
| 125 | `costs.stamp_tax_source` | string | R; lit=`https://www.mof.gov.cn/jrttts/202308/t20230828_3904235.htm` | scientific | Y | SCI cost provenance；scientific exact |
| 126 | `costs.transfer_fee_source` | string | R; lit=`https://www.xinhuanet.com/2022-04/28/c_1128605983.htm` | scientific | Y | SCI cost provenance；scientific exact |
| 127 | `costs.scaled_components` | str_array | R; lit=`(commission_rate,commission_min,slippage)` | scientific | Y | SCI cost scenarios；scientific exact |
| 128 | `costs.a_share_periods[].effective_from` | date | R; first covers data start; consecutive | scientific | Y | SCI cost schedule；scientific exact |
| 129 | `costs.a_share_periods[].effective_to` | date | O; non-final required, final forbidden; `>=from` | scientific | Y | SCI cost schedule；scientific exact |
| 130 | `costs.a_share_periods[].commission_rate` | float | R; `[0,+inf)` | scientific | Y | SCI cost；scientific exact |
| 131 | `costs.a_share_periods[].commission_min` | float | R; `[0,+inf)` | scientific | Y | SCI cost；scientific exact |
| 132 | `costs.a_share_periods[].stamp_tax_sell` | float | R; `[0,+inf)` | scientific | Y | SCI cost；scientific exact |
| 133 | `costs.a_share_periods[].transfer_fee` | float | R; `[0,+inf)` | scientific | Y | SCI cost；scientific exact |
| 134 | `costs.a_share_periods[].slippage` | float | R; `[0,+inf)` | scientific | Y | SCI cost；scientific exact |
| 135 | `tracking.experiment_name` | string | R; non-empty | tracking-target | N | TRK target/run/summary；拒绝：改变 target key，aggregate 使用共享 scientific config/first config |
| 136 | `tracking.tracking_uri` | string | R; canonical relative SQLite or HTTP(S) | tracking-target | N | TRK client + target key；拒绝：不同 backend 破坏 aggregate tracking closure |
| 137 | `tracking.artifact_root` | string | R; canonical project-relative POSIX | — | N | ROOT；bridge/runtime 要求两 fold 解析到同一 controlled root，必须 exact shared |
| 138 | `tracking.log_model` | bool | R; lit=`True` | — | N | TRK output policy；literal exact |
| 139 | `tracking.log_predictions` | bool | R; lit=`True` | — | N | TRK output policy；literal exact |
| 140 | `tracking.log_dataset_manifest` | bool | R; lit=`True` | — | N | TRK output policy；literal exact |
| 141 | `acceptance.reproducibility_score_atol` | float | R; `[0,+inf)` | acceptance | N | ACC reproducibility Gate；拒绝：lane-specific tolerance 改变准入 |
| 142 | `acceptance.reproducibility_metric_atol` | float | R; `[0,+inf)` | acceptance | N | ACC reproducibility Gate；拒绝：同上 |
| 143 | `acceptance.required_metrics` | str_array | R; lit=`(evaluation.test_rank_ic,evaluation.test_rank_icir,backtest.1p0x.test_net_excess_return,backtest.1p0x.test_turnover,backtest.1p0x.test_max_drawdown)` | acceptance | N | ACC required metrics；literal exact |
| 144 | `acceptance.minimum_feature_coverage` | float | R; `[0,1]` | acceptance | N | ACC coverage Gate；拒绝：不同阈值弱化/改变 aggregate Gate |
| 145 | `acceptance.minimum_prediction_coverage` | float | R; `[0,1]` | acceptance | N | ACC coverage Gate；拒绝：同上 |
| 146 | `acceptance.minimum_label_coverage` | float | R; `[0,1]` | acceptance | N | ACC coverage Gate；拒绝：同上 |
| 147 | `acceptance.minimum_evaluation_coverage` | float | R; `[0,1]` | acceptance | N | ACC coverage Gate；拒绝：同上 |
| 148 | `acceptance.minimum_computable_ic_date_ratio` | float | R; `[0,1]` | acceptance | N | ACC IC Gate；拒绝：同上 |

矩阵计数为 `34 + 39 + 42 + 33 = 148`；没有省略 loop-expanded shape。

## 5. technically variable non-scientific 字段逐项裁定（24/24）

| 字段/组 | 数量 | 裁定 | consumer closure / 理由 |
|---|---:|---|---|
| `meta.purpose` | 1 | 拒绝 | 不被生产行为消费；以描述文字区分 hash 是无意义 identity，fold 已由 request 显式绑定 |
| `meta.enabled` | 1 | 拒绝 | acceptance upstream 明确要求 `True`，不能一 lane disabled |
| `g1_backfill.label_tail_sessions` | 1 | 拒绝 | 进入 g1+snapshot，改变采集尾部和 derived identities，不是纯执行 lane 参数 |
| `g1_backfill.request_rate_per_minute` | 1 | 候选 C1 | 实际 G1 rate limiter；无 config derived selector，但进入 static-plan SHA；须与 release lane 的真实 quota 证据一致 |
| `g1_backfill.max_attempts` | 1 | 候选 C2 | 实际 retry budget；无 config derived selector，但进入 static-plan SHA；须与 release lane 策略一致 |
| `g1_backfill.retry_base_seconds` | 1 | 候选 C3 | 实际 backoff；无 config derived selector，但进入 static-plan SHA；须与 release lane 策略一致 |
| `g1_backfill.reconciliation.{price_atol,price_rtol,volume_rtol,max_mismatch_rate}` | 4 | 拒绝 | 直接改变 G1 cross-source quality Gate，并进入 g1 identity |
| `g1_backfill.corporate_action_reconciliation.factor_ratio_rtol` | 1 | 拒绝 | 直接改变 corporate-action quality Gate，并进入 g1 identity |
| `validation.labels.{qlib_expression_atol,benchmark_return_atol,label_return_atol}` | 3 | 拒绝 | 直接改变 label reconciliation pass/fail；且有内部 tolerance ordering |
| `tracking.{experiment_name,tracking_uri}` | 2 | 拒绝 | 改变 canonical tracking target；fold artifacts/summary/acceptance tracking 需闭合到一致 target 语义 |
| `tracking.artifact_root` | 1 | 拒绝 | bridge 逐 config 求 stage root，要求 set size=1 且 exact controlled root |
| `acceptance.reproducibility_{score,metric}_atol` | 2 | 拒绝 | 直接改变 reproducibility Gate；aggregate 不能采用 lane-specific 松紧 |
| `acceptance.minimum_{feature,prediction,label,evaluation}_coverage` | 4 | 拒绝 | 直接改变 coverage Gate |
| `acceptance.minimum_computable_ic_date_ratio` | 1 | 拒绝 | 直接改变 evaluation computability Gate |
| **合计** | **24** | **3 candidate / 21 rejected** | coverage complete |

候选排序：C1 `request_rate_per_minute`（最清晰的外部配额语义）→ C3 `retry_base_seconds`（限频退避）→
C2 `max_attempts`（可靠性/失败预算）。排序不是值选择，也不授权三项都不同；future owner 应优先选择恰好一个能由真实 lane
资源合同证明的字段，并明确两个精确值、owner、API quota/调度依据和两 lane 对应关系。若没有真实差异依据，则这三个候选
也必须全部拒绝，并进入 `NO_JUSTIFIED_DIFFERENCE / ARCHITECTURE_REVIEW_CANDIDATE`，不能为了满足 runtime 人造差异。

## 6. 强制反例复核

1. 只改 TOML 注释/空白：raw 可不同，normalized full 相同；runtime 因 full identity set size=1 拒绝。
2. 改日期/window/model 等任一 scientific 字段：raw/full 不同，但 scientific set size=2；runtime 拒绝。
3. 改 fixed literal 或加 unknown field：strict loader 在 runtime 前拒绝。
4. 改 reconciliation/label/acceptance tolerance 只为 hash：虽 non-scientific，但改变质量/准入 Gate，候选判据不通过。
5. 改 tracking experiment/URI：另算 tracking target key，且 downstream tracking/aggregate 闭包不再共享；不准入。
6. 改 artifact root：bridge 要求两个 `project_stage_root` 相同并等于 controlled root，直接拒绝。
7. example/fixture 展示两个不同 rate/retry 值：仍不是正式 SSOT；本轮未读取其具体值，也不构成 USER_CHOICE。

## 7. 边界、未决项与交付状态

本轮未运行 Python、pytest、Ruff、mypy 或 Qlib；未创建 config、request、root、evidence；未修改 runtime/schema/tests/
taskbook/review；未 stage/commit。唯一新增文件是本 delivery。

仍需 user/研究及运行资源 owner 决定：是否确有两个 G1 获取 lane 的不同配额/重试合同；若有，选择 C1/C2/C3 中的
具体字段、两个精确值及 lane 映射，并证明不借此弱化 fail-closed 行为。该决定之前不得创建 formal config。

交付上限：

`NONSCIENTIFIC_DIFFERENCE_INVENTORY_FROZEN / CONTRACT_STOP / USER_CHOICE_REQUIRED`

本包不关闭 A13/A14/A16/A19，不推进 actual successor、Qlib 或 M3 Gate；下一步仅允许不同独立 reviewer 静态复核
148/148 coverage、候选的 consumer 闭包和“无真实业务依据则架构重审”的 fail-closed 分支。
