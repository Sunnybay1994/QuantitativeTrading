# M1 HK-HISTORY-R2 开发实现报告

日期：2026-08-02（Asia/Shanghai）

状态：**本地工程合同与合成 fixture 验证通过；真实权威 evidence、正式 v2 plan/journal、后续真实请求与 HK60 finalize 均未执行。**

## 1. 边界

- 未联网，未调用 Tushare/BaoStock/HKEX。
- 未读取或修改正式 `data/`、R1 plan/journal、正式候选和正式发布目录。
- 未创建 `01065.HK@2026-05-05` 的真实 PASS evidence。测试中的 HKEX 字节均明确为 synthetic fixture。
- HKEX Historical Data Services/Data Marketplace 的许可原文格式仍未取得和冻结，因此本轮只实现来源封装、raw/metadata 字节摘要闭包和 fail-closed 投影；没有猜测原文解析规则。

## 2. 实现

1. 新增严格的 `HKNoTradeEvidenceSchema`、单 key evidence 与 canonical evidence-set identity：
   - 固定 `symbol/trade_date/market/reason/source/source_record_id/source_as_of/raw_selector`；
   - `evidence_sha256`、集合 SHA、raw 文件 SHA、canonical metadata SHA 全闭包；
   - selector 越界、字段漂移、摘要漂移、重复 key、非冻结 reason/source 均返回 `HK_HISTORY_REFERENCE_INVALID`。
2. 保留 v1 on-disk JSON 形态与 request wire identity，新增独立 `hk-history-plan-v2`：
   - 同时绑定 original expected 与 effective expected；
   - effective 只减去精确 evidence key；
   - request ID 仍只绑定实际 `hk_daily` wire 参数；
   - plan SHA 绑定 evidence、original/effective expected、requests 和独立 journal identity。
3. 新增 v2 journal binding 与 `recover_existing_hk_history_requests`：
   - 只验证 seed、已有 receipt 与 COMPLETE raw；
   - COMPLETE raw 可在新 journal 写 v2 receipt，不要求迁移 R1 intent；
   - 首个 ABSENT raw 稳定返回 `HK_HISTORY_INCOMPLETE`；
   - 不构造 connector，不写 intent/attempt/failure/clean/finalize，不修改 raw；
   - 旧/未绑定 journal 或 plan/evidence 漂移返回稳定冲突/引用错误。
4. CLI 新增互斥执行路径 `--recover-existing-only`。分支在 `TushareConnector` 构造前完成，测试证明 connector 构造次数为 0。
5. available-history Gate 与回填共用同一严格 evidence loader：
   - 只从 required bar keys 排除被精确证明的 `(symbol, trade_date)`；
   - 输出 `exempted_session_count`、`exemption_reason_counts` 与 evidence-set SHA；
   - evidence 日仍出现 bar 时计入 unexpected 并 fail closed；raw/evidence 漂移返回 `BAR_WINDOW_REFERENCE_INVALID`。

## 3. 验证

Windows 原生 `D:\Miniforge3\python.exe`：

```text
python -m pytest tests/unit/test_hk_history_backfill.py tests/unit/test_backfill_hk_history.py tests/unit/test_query.py tests/unit/test_query_universe.py tests/unit/test_schemas.py -q
121 passed, 1 skipped（Windows symlink 权限用例）

python -m ruff check <上述白名单源码与测试>
All checks passed!

python -m mypy src/quant/domain/schemas.py src/quant/data/hk_history_backfill.py src/quant/data/backfill_hk_history.py src/quant/data/query.py src/quant/data/query_universe.py
Success: no issues found in 5 source files
```

WSL Miniforge `base`：

```text
python -m pytest <同组五个测试文件> -q
122 passed

python -m ruff check <同组白名单源码与测试>
All checks passed!

python -m mypy <五个白名单源码文件>
Success: no issues found in 5 source files
```

`git diff --check` 通过；共享 worktree 中其他 Agent 的 execution/portfolio/research 改动保持未触碰。

## 4. 仍待正式关闭

1. 取得并留存许可允许的 2026-05-05 HKEX Daily Quotations（或同等级官方历史产品）原始字节，冻结真实来源解析器，再生成 `01065.HK@2026-05-05` evidence。
2. 由正式 expected/seed/evidence 生成全新 v2 plan 和全新 journal root，并在字节审计下离线恢复前三批。
3. batch 4–8 仍按每次最多一个请求、间隔至少 3,600 秒执行。
4. `02983.HK@2026-07-10` 的合规真实行情来源尚未闭合；在该独立缺口关闭前不得 finalize 或宣称 HK60 Gate 通过。
