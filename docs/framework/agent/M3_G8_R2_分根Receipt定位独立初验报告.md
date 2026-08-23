# M3-G8-R2 分根 Receipt 定位独立初验报告

## 结论

**PASS（返工复验）。** `_verify_experiment` 与下游 `_verify_experiment_receipt_from_source` 现在都从
provider 自己的已验证 artifact/manifest 路径选择最具体 root；formal 与 development 的真实分根闭环均
已进入公开 verifier，且 E3 receipt、hash、stage、closure 与路径逃逸验证未被放宽。该结论允许进入主验，
不等于重新发布或认领正式 G8，也不替代 Linux/ext4 Gate。

## 上轮问题与返工闭环

### 原 P1：下游 experiment receipt 复验仍把 provider receipt 错定到 snapshot root——已关闭

- 上轮现象（修复前）：`src/quant/research/m3/labels.py:540-548` 的
  `_verify_experiment_receipt_from_source` 仍从 `source.snapshot_manifest_path` 选择 root，然后在该 root
  下拼接 provider receipt。正式 snapshot 位于 G2A、provider receipt 只存在 G2B 时，后续
  `verify_label_artifact` 对 G8 receipt 的 fresh closure 复验仍会寻找错误路径并失败。
- 上轮根因：当时只修改了 `_verify_experiment`，没有审计同一模块内第二条 provider receipt 定位路径。
- 应遵循规则：凡需定位 provider receipt，root 必须来源于已验证 provider artifact/manifest 所属 root，
  不得借用 snapshot root。若当前 source object 没有 provider root，应从 experiment receipt 中唯一的
  provider manifest digest 安全解析出 provider manifest 路径，再选择其最具体 root；整个过程仍须经过
  E3 alias、逃逸、文件身份和 digest 校验。
- 上轮最小复现：G2A root 只保存 snapshot receipt，G2B root 保存 provider tree 与 provider receipt，G8
  receipt 的 provider inputs 指向 G2B；先通过 formal `verify_experiment_identity`，再进入 label verifier
  对 experiment receipt fresh verify。修复前代码会构造 `G2A/receipts/provider/<key>.json`。
- 上轮要求的新增测试：增加真实 receipt 的 G2A/G2B/G8 分根闭环，并继续执行到 label source 的 experiment receipt
  复验；G2A 中不得保留 provider receipt 副本。
- 通过条件：上述闭环使用真实 E3 verifier 通过；删除、篡改或把 G2B provider receipt 换成错误
  stage/hash/closure 时分别 fail closed。

返工证据：`labels.py:548-558` 先从 experiment receipt 中唯一的 provider manifest digest 经过
`path_for_artifact_digest` 解析并验真，再以该 manifest 路径调用 `_artifact_root_for`，最后才拼接固定
provider receipt 路径；不再读取 snapshot root。development label 测试把 provider tree/receipt 搬到
sibling root、删除旧 receipt、重新发布 experiment receipt，并最终通过
`verify_development_example_label_artifact`，覆盖了该下游调用链。

### 原 P1：新增回归只测 mock 调用路径，没有锁住原始故障——已关闭

- 上轮现象（修复前）：`tests/unit/test_m3_experiment_identity.py:204-225` monkeypatch
  `_verify_stage_receipt_secure`；第二次调用主动抛 `RECEIPT_PATHS_CAPTURED`。fixture 只复制 provider tree，
  没有把真实 provider receipt 移到 G2B，也没有发布与新 root aliases 闭合的 G8 receipt。
- 上轮根因：测试在 receipt 校验开始前终止，只证明字符串拼接结果，没有证明真实分根产物能通过 verifier。
- 应遵循规则：冻结任务的核心反例必须由真实公开 verifier 驱动，mock 调用次数或参数只能作为补充，不能
  替代 receipt bytes、hash、root alias、stage、scope、input/output closure 的执行证据。
- 上轮最小复现：将修改回退为旧的单 `snapshot.root` 逻辑，该 mock 测试确实会失败；但将
  `_verify_stage_receipt_secure`、provider fresh verify 或 experiment closure 破坏为放宽实现，该测试仍会
  按预期在第二次 mock 调用处结束，因而无法防住合同退化。
- 上轮要求的新增测试：至少新增 formal 与 development 两个真实分根闭环；provider receipt 仅存在 G2B；包含一个
  嵌套 root，断言 digest 使用最长匹配 alias；逐项篡改 provider receipt hash、stage 与 input closure；
  增加 `../`/绝对路径或错误 alias 的逃逸反例。
- 通过条件：测试不 monkeypatch receipt verifier，nominal 闭环返回对应 formal/development verified
  类型，所有对抗项稳定失败。

返工证据：formal 回归现在真实发布 G2A snapshot、G2B provider 与 G8 experiment receipt，删除 G2A 中
provider receipt，先调用 `verify_provider_artifact`，再调用公开 `verify_experiment_identity` 得到 verified
manifest；随后分别篡改 provider receipt stage、input hash 与 `../escape`，均要求稳定边界错误。
development 回归同样删除旧 provider receipt，并完整跑到 label artifact fresh verify。测试不再
monkeypatch receipt verifier。

## 已确认未被本轮局部代码直接放宽的性质

- `_verify_experiment` 在 `labels.py:738-763` 分别以 `snapshot.root`、`provider.root` 调用现有
  `_artifact_root_for`；该 helper 复用 `select_artifact_root`，现有 run-state 测试覆盖嵌套 root 最长匹配。
- 两类入口仍以精确 verified 类型和 `example_id` 隔离；formal/development stage 分别为
  `snapshot/provider/experiment-identity` 与 `development-*`。
- 当前修改没有改动 `verify_stage_receipt_with_bytes`，其路径包含、alias、稳定 regular-file 读取、receipt
  canonical parse、context consistency 和每个 digest bytes 复验仍在。

返工后的真实 split-root 回归与既有共享安全测试共同证明：最小修复没有放宽共享安全原语，两个原 P1 均已
关闭。嵌套 root 最长匹配继续由 `test_nested_roots_select_most_specific_and_verify_distinct_files` 锁定；本轮
扩展集同时执行该测试。

## 验证记录

Windows 原生 `D:\Miniforge3\python.exe`，显式 `PYTHONPATH=src` 与工作区独立 `--basetemp`：

- Ruff（`labels.py`、`test_m3_experiment_identity.py`）：`All checks passed!`
- mypy（`labels.py`）：`Success: no issues found in 1 source file`
- pytest（experiment identity、run state、provider materialization）：`78 passed, 4 skipped`

WSL Miniforge base，DrvFS 工作树：

- 同范围 Ruff：`All checks passed!`
- 同范围 mypy：`Success: no issues found in 1 source file`
- 同范围 pytest：`81 passed, 1 skipped`

以上是上轮 FAIL 时的基线记录：当时新增测试在真实 receipt 校验前中止，尚不足以证明原 bug 闭环。
本轮没有网络请求，没有写入或修改正式 G2/G8 目录，没有修改生产代码/既有测试，也没有提交。

### 返工复验（最终证据）

Windows 原生：

- Ruff（`labels.py` 与两个直接测试文件）：`All checks passed!`
- mypy（`labels.py`）：`Success: no issues found in 1 source file`
- pytest（experiment identity、label artifact、run state、provider materialization）：
  `97 passed, 5 skipped`

WSL Miniforge base（DrvFS 工作树）：

- 同范围 Ruff：`All checks passed!`
- 同范围 mypy：`Success: no issues found in 1 source file`
- 同范围 pytest：`100 passed, 2 skipped`

平台 skip 数差异来自现有平台特有测试；两侧均执行并通过新增 formal/development 分根 nominal 与对抗路径。

## 复验入口

两项返工已按上述通过条件闭合。M3-G8-R2 可提交主 Agent 最终验收；正式产物、正式 Gate 与 Linux/ext4
结论仍由主 Agent 后续独立判定。
