# M3 G1 P0K-C：601016 混合配股腿主 Agent 最终验收报告

日期：2026-07-31（Asia/Shanghai）

状态：**两项主验阻断已返工；最终双平台回归及正式 Windows `status` 待完成**

## 1. 验收结论

P0K-C 已按冻结任务单实现“配股上市 + 可转债转股”混合股本增量证明。旧严格 rights 支路保持
`post_total-pre_total ~= actual` 的既有合同；只有严格支路不成立时，才要求同证券、上市日唯一的
CNINFO `stock_share_change` 行同时证明：

- total/circulating 双增量在 Decimal 表示容差内一致；
- total delta 明确大于 actual；
- post total、两个 circulating projection 与 rights 行一致；
- aligned reason pairs 恰好为 `015005/配股上市` 与 `015012/可转债转股`。

完整 rights/share-change receipt、response、命中行、Decimal 对账与原因集合进入 canonical proof；
ledger 仅保存 proof SHA。event/candidate identity、ledger↔selection closure、selection 自包含 verifier
以及 candidate `input_receipts` closure 均绑定该 proof。

## 2. 关键实现

- `CorporateActionLedgerSchema` 增加 mixed rights circulating 与 proof SHA 字段；
- `CorporateActionSelectionEvidenceSchema` 同步字段并保存完整 proof JSON；
- mixed Schema 使用独立 `1e-12` 表示级容差，不复用旧严格 rights 的 `1e-6` 容差，避免形成
  隐含业务大小阈值；
- selection 版本升级为
  `tushare_dividend_cninfo_rights_share_consideration_basis_v8`；
- reconciliation 版本升级为
  `tushare_factor_daily_preclose_suspension_resume_basis_terms_v9`；
- candidate 提前构建并复用 share-change response 映射，并在构建与 audit 两处核对 proof receipt
  与正式 `input_receipts`。

## 3. 对抗性验证

已覆盖：

- 正式 601016 数值形状的 mixed 正例；
- 不提供 share proof；
- 上市日差一天；
- 只有单腿、code/name 错配、含第三原因；
- share total、F021、F022 任一漂移；
- 两条同日同 post 的等价匹配行；
- 伪造但内部自洽的 share response 可通过 selection 自检，但不能替换正式 receipt projection；
- proof 变化必须改变 event/candidate identity；
- residual 仅在表示误差内时只能走旧严格支路；
- 小于旧 `1e-6` 带、但大于 Decimal 表示误差的真实 residual 仍可走 mixed 支路；
- dividend、share-consideration 与旧严格 rights 不得携带 mixed 字段。

## 4. 已完成验证

Windows 原生 Miniforge：

- Schema：31 passed；
- P0K-C selector/proof/identity 对抗集：17 passed，140 deselected；
- mixed candidate build→audit 与正式 receipt 伪造反例：1 passed；
- P0F/P0I/P0K-B 相邻公司行动回归：24 passed，133 deselected；
- candidate/planning/reference 相邻版本与投影：4 passed；
- Ruff：通过；
- mypy（三个生产文件）：通过。

WSL Miniforge base：

- Schema：31 passed；
- P0K-C selector/proof/identity 对抗集：17 passed，140 deselected；
- mixed candidate build→audit 与正式 receipt 伪造反例：1 passed；
- P0F/P0I/P0K-B 相邻公司行动回归：24 passed，133 deselected；
- candidate/planning/reference 相邻版本与投影：4 passed；
- Ruff：通过；
- mypy：通过。

## 5. 主验发现与返工

独立只读终审没有直接接受初版实现，而是发现并关闭了两项 P1：

1. selector 的 strict/mixed 分支门仍使用旧 `1e-6` `math.isclose`，使旧容差带内的真实正 residual
   绕过 proof，负 residual 也可能被当作 strict。现已改为基于 raw Decimal 的 `1e-12`
   表示级判断，并新增正 residual、负 residual、纯表示 residual 三类 selector 测试。
2. selection verifier 只重算 rights `event_id`，未重算 `economic_event_key_sha256` 与
   `candidate_id`。现已在 ledger↔selection closure 中独立重算两者，并新增分别篡改这两个
   identity 字段、同步表摘要后仍必须拒绝的反例。

另补齐 candidate 级 receipt closure：合法 mixed rights 的完整 build→audit 通过；用第二份内部自洽
share response 生成完整 proof/event/reconciliation，再保留第一份正式 `input_receipts` 的攻击被 audit
以 `CORPORATE_ACTION_FACTOR_MISMATCH` 拒绝。完整“现象—根因—规则—复现—新增测试—通过条件”记录见任务单
§10。

## 6. 正式重放与剩余边界

返工前正式 receipt 的单次零网络候选重放曾在 Windows 原生完成：

```text
status=UNEXPECTED_OK
reconciliation_version=tushare_factor_daily_preclose_suspension_resume_basis_terms_v9
bars=1489629
primary_candidate_key_prefix=88ef701c27cb6307
```

该结果证明初版候选构建曾越过 `601016.SH@2022-11-28`，且没有出现新的 factor 首败；捕获产物为
`artifacts/g1_component_diag_20260722/p0kb_status_first_failure_v1.json`（ignored 诊断产物）。
但此后 selector/verifier 的两个 P1 返工改变了 `src/quant` source-tree identity，因此该重放只保留为
定位证据，不能代替返工后的正式裁定。

初版正式 Windows `status` 随后启动，但独立终审发现上述两项阻断后，该进程已主动停止：继续等待的
结果会对应旧源码身份，不能作为返工后验收证据。完成最终双平台定向回归后，必须以返工后的 source-tree
identity 重新运行正式 `status`，并在本报告补充最终 CLI JSON。

在 `status` 证据补齐前，P0K-C 尚不关闭，HISTORY、REFERENCE、PREPARE、PUBLISH、Linux Gate 与 G2A
均不宣称通过；当前也没有有效 `VerifiedG1Release`。
