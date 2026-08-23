# M3 G1-P4A 候选与主审计交付报告

日期：2026-07-14  
角色：外部实现 Agent（非独立初验）  
实际模型标识：`cursor-grok-4.5-high`  
任务书：[`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md) §4 / §8 / §9  
上游主验：[`M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md`](M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md)、
[`M3_G1_P3_B2C执行事实主Agent最终验收报告.md`](M3_G1_P3_B2C执行事实主Agent最终验收报告.md)  
状态：**实现与自测完成，待独立初验**（不得视为 P4A / B4 / G1 / Gate 通过）

## 1. 范围与边界

本交付只实现 G1-P4A：

- 从冻结 `G1BuildInputs`（plan / `VerifiedRawResponse` / calendar / instrument）重建 primary candidate；
- 严格调用现行 P2 membership 与 P3 price-limit / corporate-action 公开纯函数（含 `event_ids_json` 身份闭包）；
- 14 张表 content digest、`price_limit_required_keys` digest、唯一 `primary_candidate_key`；
- `verify_g1_candidate(inputs=...)` 与 `audit_g1_candidate` 全局主源审计；
- `apply_adjustment_factors_strict` 与 `AdjustmentFactorMatchSchema`。

未实现 P4B/P4C；未勾选路线图；未修改 connector、RawStore、P2/P3 算法、配置 parser；未读取 `_old/`
或 token；未联网；无文件/网络 IO。

## 2. 修改文件清单

| 文件 | 变更 |
|---|---|
| `src/quant/data/m3_g1_candidate.py` | **新增** P4A 类型、build/verify/audit、因子严格匹配 |
| `src/quant/domain/schemas.py` | **新增** `AdjustmentFactorMatchSchema` |
| `src/quant/data/__init__.py` | 仅导出冻结公共接口 |
| `src/quant/domain/__init__.py` | 仅导出新 Schema |
| `tests/unit/test_m3_g1_candidate.py` | **新增** happy path + §4.6 必测反例 |
| `docs/M3_G1_P4A候选与主审计交付报告.md` | 本报告 |

未写入独立初验报告。

## 3. 冻结签名与行为要点

公开接口：

- `M3G1CandidateError`（四稳定码，`from None`，四观察面脱敏）
- `G1BuildSpec` / `G1BuildInputs` / `G1ReceiptProjectionV1` / `G1Candidate`
- `G1QualityIssue` / `G1PrimaryAuditResult` / `AdjustmentApplicationResult`
- `apply_adjustment_factors_strict` / `build_g1_candidate` / `verify_g1_candidate` / `audit_g1_candidate`
- `G1_MEMBERSHIP_METHOD_VERSION = "tushare_monthly_observed_next_session_close_v1"`

关键不变量：

1. build 只接受 `G1BuildInputs`；不接受调用方自报 P2/P3 result / candidate / PASS；
2. request/response 精确多重集合；每 response 重建 `VerifiedRawResponse` 证明 spec/receipt/frame/digest；
3. P2 使用完整 `verify_observed_membership_result(batch/responses/...)`，不用 result-only verifier；
4. P3 selection/reconciliation 从 verified raw 重算；reconciliation 传入完整 daily responses + suspensions，
   消费现行 `event_ids_json`；
5. 因子精确 `(symbol,trade_date/effective_date,source)` 连接，注入 bar/factor request lineage；无默认 1.0；
6. 14 表名集合与字典序 digest 固定；identity envelope 绑定四日期、receipts、digests、required-keys；
7. audit 收集全部可检查跨表 ERROR；`passed` 当且仅当 issues 为空；不含 `CROSS_SOURCE_*`。

## 4. 实现者自测覆盖

`tests/unit/test_m3_g1_candidate.py` 覆盖任务书 §4.6：

1. 少/多/重复/cross-plan response；frame/receipt/spec 漂移；
2. response 与 clean 行序变化 identity 不变；price / list_date 变化 identity 改变；
3. 缺/重复/非正 factor；lineage/stable digest 自证失败；
4. eligible：缺 bar、bar+FULL_DAY 冲突、PARTIAL 无 bar；
5. 299 成员、SH/SZ calendar 分歧、未知证券、benchmark 缺 history 日；
6. price-limit 缺行；corporate-action digest 漂移；
7. wholesale 替换另一套合法 candidate：`verify_g1_candidate(inputs=原输入)` 失败；
8. 异常四观察面脱敏；
9. monkeypatch `open`（数据路径）/`socket`/`RawStore` 证明零文件 IO、零网络。

## 5. 验证结果（WSL Miniforge `base`）

全部经 `wsl.exe` 进入 `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，使用
`/home/mabw/miniforge3/bin/python`（即 base 环境解释器）；禁止 Windows Python/conda。

| 命令 | 结果 |
|---|---|
| 定向 `PYTHONPATH=src python -m pytest -q tests/unit/test_m3_g1_candidate.py` | **16 passed**（约 6–7 min；300 成分夹具） |
| 全量 `PYTHONPATH=src python -m pytest -q` | **625 passed**，既有 Pandera/Polars deprecation warnings |
| `python -m ruff check src tests` | **All checks passed** |
| `python -m mypy src` | **77 source files，0 issues** |

## 6. Import 隔离、联网与脱敏

- `m3_g1_candidate.py` 无 `quant.research`、无 connector 调用、无 RawStore 写入、无配置/时钟/随机数；
- 本次未联网、未读 token/ignored 凭据、未写 raw/clean/release；
- `str/repr/__cause__` 仅为稳定错误码。

## 7. 已知限制与合同备注

- 未实现 P4B 跨源 / P4C 不可变发布；不得开始下游包；
- SSOT §4.10 写明 `G1QualityIssue` 定义在 `m3_backfill`，但 P4A §4.1 允许文件不含
  `m3_backfill.py`；本包将 `G1QualityIssue` 落在 `m3_g1_candidate.py` 并导出，供 audit 使用。请主
  Agent 在终验前决定是否迁回 `m3_backfill` 或修订 SSOT 位置表述；实现者未改 P2/P3 算法文件；
- 自测夹具为 300 成分最小 history（2 个 SH session）；全量回归耗时主要来自该夹具重建；
- 不宣称价格完备、真实 Tushare 抓取或 B4/G1 Gate 通过。

## 8. 交付声明

本报告只证明：冻结范围内 P4A 实现已完成，且实现者自测与验证命令通过。

**待未参与实现的独立初验 Agent 审查并出具**
`docs/M3_G1_P4A候选与主审计独立初验报告.md`。

**不宣称 P4A / B4 / G1 / 任一 Gate 通过。**
