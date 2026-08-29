# M4-UA006-R3 Fresh Formal Bootstrap Run1 独立初验报告

日期：2026-08-30<br>
状态：`FINAL_EVIDENCE_REVIEW_PASS / P0=0 / P1=0 / P2=0`<br>
task id：`M4-UA006-R3-FRESH-FORMAL-BOOTSTRAP-RUN1`

## 1. 审查结论与边界

本次以未参与 B1/B2/C 运行的独立审查上下文，只读复核 taskbook、delivery、production/tests、B1/B2/C 原生 evidence、exact external roots、Git 与资源现场。未运行 Python、`initialize`、`reopen`，未取得 `0xF00`，未清理或修改 config、production、tests、evidence 与 external roots。

结论为 PASS：B1 carrier STOP 的非产品边界、B2 initialize exact1、任务书 postcheck 合同纠正、C reopen exact1、身份分组、资源释放与 D 锁定保留均有原生证据支持，未发现 P0/P1/P2。

本 PASS 的结论上限仅为 `FRESH_INITIALIZE_REOPEN_WINDOWS_ENGINEERING_VALIDATED / LOCKED_RETAINED`。它不是 PAPER Gate，不关闭 28 日 soak、session-close、OMS/order、broker submit、UA-M4-006 整体 Gate 或 Linux Gate。

## 2. 文档与范围身份

- taskbook：15282 bytes，SHA-256 `905bf139c1577c8aa1adfbb390daad17b11776d1ed592eac43807deeb4f785ce`。
- delivery：5524 bytes，SHA-256 `191ed901bd9860dbc9597aaef5d6c5ff572150c3a025f8e90d29011dc5bd93a3`。
- Git HEAD：`1a25284fc2db58d165ec59b43560c53214147850`；taskbook 冻结 base 为 `aa84ebc8519a34dcc83b309db6fda0f2b95dc4a5`。
- 写入 review 前 actual exact2：只有 taskbook modified 与 delivery untracked；cached `0`；`git diff --check` 无错误（只有已知 LF→CRLF warning）。
- config 仍为 947 bytes，SHA-256 `4217f157885f3e304da7d834f8e80ed21bdd23273017e1fea42863abebd752cd`，且为 ignored。

## 3. B1 carrier STOP

B1 leaf 只有 runner 与 Parser 三件套，没有 identity、initialize、summary 或其他产品 evidence，与“外层 exact-affinity 检查在 runner/Python 前 STOP”一致。

- runner：8601 bytes，SHA-256 `e8938415823beb7dd931ae87a4a2d2ac7f5d2135b9d9ab21524d1e77313f7d9b`。
- parser stdout：16 bytes，SHA-256 `e1bdb8e40a14661f82b5cef6183eaf557433d6da08f1e9285c5f4614dc14c093`。
- parser stderr：0 bytes，SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。
- parser exit：`0\n`，SHA-256 `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`。

因此 B1 只能定级为 carrier STOP / Python0 / initialize0，不得写成 initialize 成功或失败。B1 leaf 必须继续 `LOCKED_RETAINED`。

## 4. B2 initialize exact1 与合同纠正

B2 原生证据闭合：Parser errors exact0，identity exit0/stderr0/stdout exact `IDENTITY_PASS`，initialize exit0/stderr0。initialize stdout 为 1484 bytes，SHA-256 `b62ff39e8e8d1db88b1915e3da87141a2bb659d3f1eab59158e0649d6d05011d`；严格 UTF-8 解码后为单行 JSON，exact18 keys，`schema_version=m4-formal-bootstrap-operator-result-v1`，`mode=initialize`，`session_date=2026-08-27`，其余身份值均为 canonical lowercase 64-hex。

B2 关键文件身份与 delivery 一致：

- runner：8604 bytes，SHA-256 `d324571e8ed056725e6e65fc6d454a67911f10a7bf2a5d11b78de81b5df730ed`。
- identity stdout：SHA-256 `896cadc8f26819d0ec32e85827d3bdc3c2b25a7b65b9cf4905e2ad3e1dca4207`。
- stage summary：214 bytes，SHA-256 `a8a1edf59571b269e6005148868b510da5fd8fa57b9f9b3e2d55d7f68fd05361`。
- B2 各 exit 均为 `0\n`，各 stderr 均为 0 bytes。

summary 显式保留了 initialize 之后的 STOP：旧 runner 在对 `evidence` 执行“必须是物理目录”的错误 postcheck 时失败。当前源码与测试明确证明这是任务书预期漂移，而非 production 失败：formal broker/execution initializer 只物化 broker/runtime，`paper_runtime` 对未存在的角色使用 package-owned `absent-paper-runtime-root-v2` identity，且 public CLI 只有在 fresh verifier 通过后才输出成功 JSON。

当前外部布局与纠正后合同一致：

- physical materialized exact2：`runtime`、`broker`，均为 real non-reparse directory。
- physical absent exact3：`evidence`、`anchor`、`log`。
- semantic exact5：五个角色由 production `root_identities` 与 `runtime_layout_identity` 闭合；没有为迁就旧 postcheck 而补建 absent exact3。

initialize 授权已 exact1 消费，不得再运行。

## 5. C reopen exact1 与身份分组

C 使用第三个 no-clobber ignored leaf。runner 的 `EvidenceRoot` 为 mandatory 参数，并核它精确等于冻结 C leaf；source 中 `--initialize` token 数量为 0，`--reopen` 为唯一业务模式。

- runner：9470 bytes，SHA-256 `c86a58a50e9edeba0167198c0eda394a16e8572725f54ee4a0ebe09a2976665d`。
- parser errors exact0；parser stdout SHA-256 `e1bdb8e40a14661f82b5cef6183eaf557433d6da08f1e9285c5f4614dc14c093`。
- reopen exit：`0\n`，SHA-256 `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`。
- reopen stderr：0 bytes，SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。
- reopen stdout：1480 bytes，SHA-256 `0df4039325fc201a777e74b3c89fa24044ff3fbf6d8b055a2e54ea80650e6396`。
- stage summary：109 bytes，SHA-256 `a714ca452f2a9b1babd943bb3c78294eb9a281925f3eb989584224fe26683daa`，顺序记录 START→resource acquired→preflight PASS→reopen PASS→identity groups PASS→runner PASS→resource released。

独立解析 B2 initialize 与 C reopen 原生 JSON 得到：

- key 集合均为 exact18，集合差异 0。
- control exact2：`schema_version` 一致，mode 依次为 `initialize` / `reopen`。
- durable exact10：`session_date`、`config_identity`、`config_raw_sha256`、`source_file_identity`、`runtime_layout_identity`、`gateway_identity`、`execution_store_identity`、`barrier_epoch`、`barrier_capability_identity`、`barrier_lock_identity`逐项比较，mismatch exact0。
- time-bound exact6：`bootstrap_identity`、`runtime_environment_identity`、`execution_policy_identity`、`broker_binding_identity`、`account_verification_identity`、`broker_capability_identity`逐项比较，equal exact0。
- 两份 JSON 的 15 个身份字段均为 canonical lowercase 64-hex，没有路径、`verified_at` 或对象 repr 泄露。

reopen 授权已 exact1 消费，不得再运行。

## 6. 锁定、资源与 Git 闭合

- external parent、config、runtime、broker 与 B1/B2/C leaf 均存在；三个 evidence leaf 均为 real non-reparse directory 且为 Git ignored。
- `evidence`、`anchor`、`log` 仍 absent，不得补建。
- 当前 Python/pythonw 进程计数为 0；对可读进程使用 affinity exact equality 核验，exact `0xF00` 命中为 0。
- 写 review 前 Git actual exact2、cached `0`、diff-check PASS；production、tests、config、roadmap、governance 无 tracked 变更。
- initialize 与 reopen 各 exact1，两个授权均已消费。不得 cleanup、overwrite、append、adopt、resume 或任何第二次业务调用。

## 7. 对抗性反例

### 反例 A：删除 STOP 历史后只保留绿色结论

若交付文档删除 B1 carrier STOP 或 B2 旧 postcheck STOP，只保留 initialize/reopen exit0，将失去 carrier 错误、合同预期漂移与“initialize 未重跑”的完整因果链。这种修订必须判定 P1，不得以“终态已 PASS”为理由删除 STOP 历史。当前 taskbook/delivery 均保留了 B1 与 B2 STOP，通过此反例。

### 反例 B：把 Windows engineering evidence 提升为 PAPER Gate

若任何结论把一次 fresh initialize+reopen 写成 PAPER 候选已准入、28 日 soak 已完成、UA-M4-006 已关闭或 Linux Gate 已通过，则缺少对应的长时运行、session-close、业务与 Linux 证据，必须判定 P0/P1 并拒绝合流。当前 taskbook/delivery 均明确保持这些 Gate OPEN，通过此反例。

## 8. 最终裁定

`FINAL_EVIDENCE_REVIEW_PASS / P0=0 / P1=0 / P2=0`

可进入 exact3 文档 SAFE_COMMIT 申请，但本 review 不授权 stage、commit、merge、cleanup、PAPER 运行或任何第二次 initialize/reopen。
