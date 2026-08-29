# M4-UA006-R3 Fresh Formal Bootstrap Run1 交付报告

日期：2026-08-30<br>
状态：`FRESH_INITIALIZE_REOPEN_WINDOWS_ENGINEERING_VALIDATED / LOCKED_RETAINED`<br>
task id：`M4-UA006-R3-FRESH-FORMAL-BOOTSTRAP-RUN1`

## 1. 交付结论

在用户 A-D 明确授权与中央逐阶段资源准入下，本包完成了一个全新 Windows formal runtime 的 exact一次 `initialize` 与 exact一次 `reopen`。两次原生调用均 exit `0`、stderr `0B`；reopen 对 initialize 的 durable exact10逐项相等，time-bound exact6逐项不同。运行完成后资源释放，所有 runtime 与 evidence 按 D 原样 `LOCKED_RETAINED`。

结论上限仅为 fresh initialize+reopen Windows工程证据。它不关闭 PAPER、28日 soak、UA-M4-006整体 Gate、Linux Gate，也不授权订单、broker submit或任何第二次业务调用。

## 2. 冻结身份与调用次数

- exact base：`aa84ebc8519a34dcc83b309db6fda0f2b95dc4a5`
- tracked HEAD：`1a25284fc2db58d165ec59b43560c53214147850`
- config：947 bytes，SHA-256 `4217f157885f3e304da7d834f8e80ed21bdd23273017e1fea42863abebd752cd`
- session date：`2026-08-27`
- initialize call count：exact1，已消费，禁止重跑。
- reopen call count：exact1，已消费，禁止重跑。
- broker/network/PAPER/soak/order/cancel调用：0。

## 3. B1 carrier STOP

B1 在业务 Python 前因外层资源检查错误地使用 affinity bitmask overlap，而不是 exact equality，产生 `B_RESOURCE_PREFLIGHT_CARRIER_STOP`。该次 `Python=0 / initialize=0`，没有产品结论。B1 leaf随后永久锁定。

关键证据：

- runner：8601 bytes，SHA-256 `e8938415823beb7dd931ae87a4a2d2ac7f5d2135b9d9ab21524d1e77313f7d9b`
- parser exit：SHA-256 `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`
- parser stdout：SHA-256 `e1bdb8e40a14661f82b5cef6183eaf557433d6da08f1e9285c5f4614dc14c093`
- parser stderr：0 bytes，SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

## 4. B2 initialize 与合同纠正

B2 使用新 no-clobber leaf和修正后的 exact-affinity 外层检查。Parser、identity 与 initialize均通过；initialize原生 exit `0`、stderr `0B`，stdout为 exact18 canonical JSON。

随后旧任务书把五个 semantic root角色错误要求为五个 physical directory，runner在 `evidence` absent处触发 postcheck STOP。中央源码审计确认这是任务书预期漂移，不是 production失败。真实合同为：

- physical materialized exact2：`runtime`、`broker`；
- physical absent exact3：`evidence`、`anchor`、`log`；
- semantic identity exact5：五个角色全部进入 `root_identities` 与 `runtime_layout_identity`，absent exact3使用 package-owned absent identity。

未补建 absent exact3，未重跑 initialize。修订合同经独立静态复核通过。

关键证据：

- runner：8604 bytes，SHA-256 `d324571e8ed056725e6e65fc6d454a67911f10a7bf2a5d11b78de81b5df730ed`
- parser stdout：SHA-256 `e1bdb8e40a14661f82b5cef6183eaf557433d6da08f1e9285c5f4614dc14c093`
- identity stdout：SHA-256 `896cadc8f26819d0ec32e85827d3bdc3c2b25a7b65b9cf4905e2ad3e1dca4207`
- initialize stdout：1484 bytes，SHA-256 `b62ff39e8e8d1db88b1915e3da87141a2bb659d3f1eab59158e0649d6d05011d`
- stage summary：SHA-256 `a8a1edf59571b269e6005148868b510da5fd8fa57b9f9b3e2d55d7f68fd05361`
- exit文件：均为 `0\n`，SHA-256 `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`
- stderr文件：均为0 bytes，SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

## 5. C reopen

C 使用第三个全新 no-clobber leaf。runner接受 mandatory `EvidenceRoot`，自身不含 `--initialize`调用；写入后冻结身份并通过 Parser。它只读绑定 B2 immutable stdout/config/root状态后执行唯一一次 `reopen`。

结果：

- runner：9470 bytes，SHA-256 `c86a58a50e9edeba0167198c0eda394a16e8572725f54ee4a0ebe09a2976665d`
- parser errors：exact0；parser stdout SHA-256 `e1bdb8e40a14661f82b5cef6183eaf557433d6da08f1e9285c5f4614dc14c093`
- reopen exit：`0\n`，SHA-256 `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`
- reopen stderr：0 bytes，SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- reopen stdout：1480 bytes，SHA-256 `0df4039325fc201a777e74b3c89fa24044ff3fbf6d8b055a2e54ea80650e6396`
- stage summary：109 bytes，SHA-256 `a714ca452f2a9b1babd943bb3c78294eb9a281925f3eb989584224fe26683daa`
- control exact2：schema闭合，mode=`reopen`；
- durable exact10：与 initialize逐项相等，mismatch=0；
- time-bound exact6：与 initialize逐项不同，equal=0；
- physical exact2/absent exact3/semantic exact5保持。

## 6. 资源、Git 与保留边界

- 结束后 Python/pythonw=0；可读进程中 affinity exact `0xF00`=0。
- source worktree仅 taskbook/delivery为批准的 tracked文档变化，cached=0；config和三组 evidence均为 ignored。
- external parent、config、runtime、broker、B1/B2/C evidence均按 D `LOCKED_RETAINED`。
- 禁止自动清理、覆盖、追加、adopt、重跑 initialize/reopen或把当前现场用于 PAPER。
- production、tests、config、shared main、roadmap和治理文件均未修改。

## 7. 剩余工作

- 由未参与运行的同一独立 reviewer核原生 B2/C evidence、调用次数、身份分组和锁定边界。
- 本包只关闭 fresh bootstrap initialize/reopen 的 Windows工程证据；正式 PAPER候选、28日 soak、session-close真实证据和 UA-M4-006总 Gate仍须后续独立任务完成。
