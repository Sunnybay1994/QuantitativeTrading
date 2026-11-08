本轮只做静态源码/测试/任务书/交付文档映射；未运行 Python、pytest、Ruff、mypy、cold、Qlib、data/network、
root/evidence、controlled stage、Windows validation 或任何 Git stage/commit。因此该结论不等价于 runtime PASS、
Windows engineering validated、formal config ready、actual successor/Qlib、retained、M3 Gate 或 Linux Gate 完成。
实际写入范围仅为本 review 报告；production、unit、integration、taskbook、delivery 均未由本 reviewer 修改。

## 12. STATIC_REWORK4 复验

本轮按任务书 §13 对 replay fresh-verification 断言进行同一独立 reviewer 的静态复验。冻结输入经只读哈希核对：production
`cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be`、unit
`4d2cddc93e03486c98be4734f19bc93db16c82edf96be4c19a9570089a108ddc`、integration
`28b79f7276df878351c86b45b0538362547afc03f26df76470e810a703b7bf4f`（73229 bytes）、taskbook
`f932581760c9cf94c2529ed5e690b07d7c98cd1be067eed41a5a50ce7dde0be3`、delivery
`09677d1d63dbac103cdd8356edba7465dab2bb9086e8ffb88f09aa96d15e46ff`，REWORK3 review
`92c88ad0a51f12bbb513a4c3a2f2ed56d3432d30ccf62ffa35131fb7aaa63a9a`。

### 12.1 replay prefix/suffix 行为等价

`test_same_config_replay_is_exact_and_second_fold_tamper_fails_fresh`（`tests/integration/test_m3_successor_runtime.py:1122-1171`）
的修正局限于测试观测与断言，未改变 production、terminal verifier、unit 或其他反例：

1. 首次 `_run` 后保存完整 `first_public_api_calls`；replay 后对相同长度 prefix 逐字比较（`:1137-1148`），证明首次
   调用前缀未被改写或重排。
2. replay suffix 被 exact 限定为且仅为
   `summary-public-verify`、`reproducibility-public-verify`、`readiness-public-verify`、
   `acceptance-public-verify`（`:1149-1155`），不是仅断言 `+4`。同时显式排除 upstream/formal wave、`run-plan`、
   `public-run` 与 `publication`（`:1156-1162`）；exact tuple 本身也不包含这些调用。
3. replay 断言 `reused is True`、terminal path 与首次相同、attestation 完全相同且 `two_fold_identity` 不变（`:1141-1145`）。
   这保留 fresh Gate verification，同时证明没有第二次 stage/work/publication 行为。
4. 保存 `calls_after_replay` 后篡改同一 physical `shared.toml`；第三次 `_run` 预期
   `SUCCESSOR_INPUT_INVALID`，且 `public_api_calls` 长度保持不变（`:1163-1171`），因此 drift 在任何新增
   public verifier、stage 或 publication 前拒绝。

### 12.2 §10/§12 既有闭包与冻结复核

- production 与 unit SHA 仍分别为冻结值；integration 当前 diff 仅增加/修正测试观测、same-config 既有覆盖及 replay 断言，
  无 production hook、terminal schema、错误码、cache 或第二验证序列变化。
- §12 的 test-owned `_validate_request` wrapper、两轮 validation、每轮 shared read/load exact2、release
  `[fold_001, fold_002]`、未过滤 `runtime_read_calls`、controlled-root/unbound/terminal 约束保持；未恢复旧的
  `all_read_calls`/过滤/去重视图。
- §10 的 same physical fresh exact2、second-fold drift 前置拒绝、duplicate release、work ownership、shared/nonshared
  receipt ownership、四 Gate 顺序与 identity、两个 attestation bindings、`two_fold_identity`、different raw/full same
  scientific 正向均仍在当前测试结构中；本轮没有删除或弱化这些断言。

### 12.3 结论与证据边界

REWORK4 只修正了因 V3 发现而过严的 replay public-call 计数断言：允许既有四项 Gate fresh verifier suffix，同时严格保持首次
prefix、replay identity/terminal/reused、无第二 publication，以及 shared config drift 的零新增 public-call 失败语义。
未发现 P0、P1 或 P2。

故本轮结论为：

**`STATIC_REWORK4_REVIEW_PASS`（无 P0/P1/P2；STATIC_ONLY）**。

本轮未运行 Python、pytest、Ruff、mypy、cold、Qlib、data/network、root/evidence、controlled stage、Windows
validation 或任何 Git stage/commit；V3 的历史 `29 passed / 1 failed` 仅作为任务书背景，不被改写为本轮运行 PASS。
该结论不等价于 runtime PASS、Windows engineering validated、formal config ready、actual successor/Qlib、retained、
M3 Gate 或 Linux Gate 完成。实际写入范围仅为本 review 报告；production、unit、integration、taskbook、delivery 均未由
本 reviewer 修改。

## 13. EVIDENCE_REVIEW

本轮按 taskbook §14 对 V1–V5 保留证据、delivery 引用、组合范围与剩余边界进行独立只读复核。当前冻结输入经
`Get-FileHash -Algorithm SHA256` 核对：production `cd5a33492b399419389d5a8e93808ad4e918f3388ee5f87479fa4c5a531323be`、
unit `4d2cddc93e03486c98be4734f19bc93db16c82edf96be4c19a9570089a108ddc`、integration
`28b79f7276df878351c86b45b0538362547afc03f26df76470e810a703b7bf4f`、taskbook
`77c235669ef37dc24341dfa58007f8ab3be3b8ff682d50b28d22c35a764f59cc`、delivery
`5dba612abc3e31c90dc9e6f34e9567e3a2ca318c5aa71e6b7a0329c952fa5371`，REWORK4 review
`4becfdd9b27366775c35e065812741f824b63b9f15add22d12a3ecc5381d5162`。

### 13.1 V1–V5 证据逐项对账

保留 evidence 文件内容与 taskbook §14 的结论一致，关键文件 SHA 对账如下：

| 轮次/文件 | 实际 SHA-256 | 对账结论 |
| --- | --- | --- |
| V1 `summary.txt` | `47755ef671684c5f915629ddba624552c7a84d65c2a083ac620e36a1cbf537b8` | carrier syntax STOP；Python 0-call，产品阶段 UNRUN |
| V2 `summary.txt` | `60501198f959b2db4383b5c71098a7f1f507eec9b9db16d1c3236313755c633b` | carrier preflight STOP；Parser errors 0、Python 0-call，产品阶段 UNRUN |
| V3 `summary.txt` | `3bc22a591a7d64d9479cd3cef5de112f65691561d1835f46d582ce39604f418f` | identity/unit 通过，integration 29 passed/1 failed |
| V3 `02_unit.stdout.txt` | `7f0c60897d815a9e0d812a5ec768f0de50134fbdb41671316b2a62c2d511a2e6` | `35 passed` |
| V3 `03_integration.stdout.txt` | `ad36fc0e781bb7bcd8a2210d2dc17d727013f390a9fe6166e3a33a5e518e569f` | 失败仅为旧 replay 计数断言；不是产品逻辑失败 |
| V4 `summary.txt` | `0165770cda42407a1eb9257d85a3e7748c23cd412a70806748906472111c4468` | identity/replay node/Ruff exact3/mypy/cold 通过；scope carrier STOP |
| V4 `02_replay_node.stdout.txt` | `27b93b41fc7fe0209fb0edde525c85c2884ce93570c953f81487fc13e272dd56` | replay 修正节点 `1 passed` |
| V4 `03_ruff.stdout.txt` | `af352a86840ad0af3d37ea0d9197f868363a6dac6b1c2ef5d2722f6b41d2d9af` | Ruff exact3 通过 |
| V4 `04_mypy.stdout.txt` | `94594db09076fe305d51b50210d0bc5e9d275fb814f8b42c1ed4cf3368392f9a` | production mypy 通过 |
| V5 `summary.txt` | `d52f14f869ddcfc3840ad0f6ae72738a5a3a549d8079e795022f9dc36d2c60de` | scope-only PASS；exact6/cached0/diff-check/residue 均闭合 |

V1 carrier 文件进一步明确 `parser_error_count=2`、`python_call_count=0`、资源未取得；V2 明确 Parser errors 0、
`parser_triple_created=true`、Python 0-call、资源未取得。V3 exit artifacts 为 identity=0、unit=0、integration=1，且
stdout 明确 `35 passed` 与 `29 passed, 1 failed`。V4 exit artifacts 为 identity/replay/Ruff/mypy/cold 全部 0、scope=1；
该 scope STOP 没有被合入产品绿测。V5 五个 exit 均为 0，status 文件只列出六个 exact6 路径，cached count=0，
diff-check exit=0，temp/cache 目标均 absent，process 文件为 Python=0、affinity_0xF00=0。

### 13.2 组合范围与证据根边界

delivery 的组合范围与 taskbook §14.2 一致且有效：V3 的 identity、完整 unit 与 integration 其余 29 项；V4 的修正 replay
节点、Ruff exact3、mypy production、cold；V5 的 exact6/scope/residue。该组合没有把 V3 唯一失败、V1/V2 carrier STOP 或
V4 scope carrier STOP 洗成全绿，也没有重复或虚构产品阶段。

V3 evidence root `artifacts/agent_runs/m3-r2f-v2-validation3-20260828T121638Z` 存在并包含 taskbook 引用的 summary 与
unit/integration 输出。V1、V2、V4、V5 的对应保留目录与文件也存在，但 taskbook §14 只绑定 V3 的独立 evidence root；
delivery 正确地没有猜测或宣称其他轮次的 root 语义，而仅采用明确列出的 summary/stdout SHA。该保守处理不削弱已引用
证据，也不扩大证据范围。

production/unit 当前 SHA 与冻结值一致；V5 exact6 count=6、cached=0，实际六项正是 production、unit、integration、
taskbook、delivery、review；diff-check exit=0，stderr 仅 LF→CRLF warnings，temp/cache/Python/0xF00 residue 均清零。
本轮只读检查未发现 combined-scope 或 evidence 引用矛盾。

### 13.3 结论与剩余边界

故本轮结论为：

**`EVIDENCE_REVIEW_PASS`（无 P0/P1/P2）**。

结论边界严格限定为该 shared-scientific-config 合同的 Windows engineering validation 组合证据已可采用；不声明 A14
formal scientific config/controlled root、A15 formal G1 release、A17 Windows py312/Qlib、actual successor、真实
Qlib/network、new root、retained resume、acceptance 真实运行、M3 Gate 或 Linux Gate 完成。ignored evidence 不得 stage；
SAFE_COMMIT、merge 与 archive-first retirement 仍由中央流程另行裁定。

本轮只更新本 review 报告；未运行 Python、pytest、Ruff、mypy、cold、Qlib、data/network、root/evidence、stage 或 commit，
且 production、unit、integration、taskbook、delivery 未由本 reviewer 修改。
