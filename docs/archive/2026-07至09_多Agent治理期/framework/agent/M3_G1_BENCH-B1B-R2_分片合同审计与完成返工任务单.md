# M3 G1 BENCH-B1B-R2：分片合同审计与完成返工任务单

## 1. 背景与目标

BENCH-B1B 已有两轮超时会话留下的部分实现，R1 workflow 基金 fake 已完成外部返工与独立复验；但原 B1B
正式实现交付报告仍缺失，主 Agent 的分组回归又暴露出大 fixture 的分钟级耗时。为避免新的单一外部会话在
大 diff 中空转，本轮先由两个全新外部 Cursor 会话并行做严格只读分片审计，再由一个新的外部实现会话按
合并后的确定缺口完成最小返工和正式交付报告。

两个审计会话都必须显式使用 `cursor-grok-4.5-high`，不得修改生产代码、配置或测试，不得联网、调用真实
API、写正式 raw/journal/receipt 或 publish。审计报告不是独立初验，也不得宣布 B1B/G1 Gate 通过。

## 2. R2A：mapper、candidate 与分红经济语义审计

只读代码/测试范围：

- `src/quant/data/m3_mappers.py`
- `src/quant/data/m3_g1_candidate.py`
- `tests/unit/test_m3_g1_mappers.py`
- `tests/unit/test_m3_g1_candidate.py`
- `tests/unit/test_m3_labels.py`

唯一可写文件：

- `docs/framework/agent/M3_G1_BENCH-B1B-R2A_Mapper与分红语义外部只读审计报告.md`

必须逐项核对：五份正式响应精确闭包；`fund_adj` 分段唯一/完整/稳定排序；daily-factor 一一覆盖；调整 OHLC；
五 response 的 `source_snapshot_id`；实施分红核心投影去重与冲突；两个冻结对账公式、窗口首日边界、无事件
跳变/事件无跳变；label 的 entry 前、entry 日、持有期、exit 后边界以及禁止二次加现金。至少给出一个当前
测试未覆盖的对抗性反例；只报告，不写测试。

## 3. R2B：planning、release identity 与 readiness 审计

只读代码/测试范围：

- `src/quant/research/m3/config.py`
- `src/quant/research/m3/g1_planning.py`
- `src/quant/data/m3_release.py`
- `src/quant/research/m3/readiness.py`
- `tests/unit/test_m3_backfill_requests.py`
- `tests/unit/test_m3_contracts.py`
- `tests/unit/test_m3_g1_planning.py`
- `tests/unit/test_m3_g1_release.py`
- `tests/unit/test_m3_readiness.py`
- `tests/unit/test_m3_reference.py`

唯一可写文件：

- `docs/framework/agent/M3_G1_BENCH-B1B-R2B_Planning发布身份与Readiness外部只读审计报告.md`

必须逐项核对：3185 个旧证券 request identity 不变、新计划精确 3190、无 H00300；三个 benchmark 身份显式
进入 build spec/manifest/release hash；当前发布只生成严格 v2；历史 v1 严格读取但不能作为当前发布输入；
v1/v2 混合、缺/多字段和伪造 method fail closed；readiness 拒绝旧 benchmark、raw 510300、不完整 snapshot
和身份漂移。至少给出一个当前测试未覆盖的对抗性反例；只报告，不写测试。

## 4. 性能证据与审计边界

Windows 原生单测
`test_release_identity_stable_under_row_shuffle` 已通过，但耗时 287 秒（setup 171.64 秒、call 111.62 秒）并
产生 91,985 条 warning；faulthandler 显示 setup 位于
`build_g1_candidate -> verify_corporate_action_selection_result -> Pandera Polars coercion`。审计者不得用
削弱 fixture、跳过 Schema 或缩小业务合同来换取速度；只需判断是否存在明显重复构造或 B1B 新增的复杂度
回归，并在报告中区分“既有重 fixture”与“本轮逻辑缺口”。

## 5. 后续完成条件

主 Agent 合并 R2A/R2B 证据后冻结唯一外部实现白名单。实现者完成最小修复、定向自测并写原 B1B 正式交付
报告；随后必须由另一个未参与实现的全新外部会话独立初验。只有外部初验通过且主 Agent 完成 Windows
反馈、WSL base 定向/回归、Ruff、mypy、whitespace 与未公开反例后，B1B 才可关闭。
