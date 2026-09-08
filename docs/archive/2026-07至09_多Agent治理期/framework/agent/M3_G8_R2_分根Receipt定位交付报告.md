# M3-G8-R2 分根 Receipt 定位交付报告

## 交付结论

`verify_experiment_identity` 现在分别从 snapshot 与 provider 自己所属的 artifact root 定位对应
receipt，不再把二者错误地假设为同根。其余 E3 receipt 字节、路径边界、hash 与 closure 验证保持原样。

## 根因与最小修复

- 现象：正式 G2A/G2B 分根时，G8 final verifier 到错误的 G2A root 查找 provider receipt。
- 根因：局部变量 `root` 只由 `snapshot.root` 解析，却同时用于两个上游 receipt。
- 修复：独立解析 `snapshot_artifact_root` 与 `provider_artifact_root`，分别拼接固定 formal/development
  receipt stage 与已验证业务 key。
- 回归：新增无 mock 的 formal 分根闭环，重建真正的 formal snapshot/provider identity 与 receipt，把
  provider tree/receipt 迁至独立 G2B root 并删除 G2A receipt 副本，再经 public provider/experiment
  verifier 验真；另将 development provider 与 experiment 分根并继续进入 public label verifier。

## 独立初验返工

首次独立初验发现 label consumer 的 `_verify_experiment_receipt_from_source` 仍借 snapshot root 定位
provider receipt，且首版测试在 receipt verifier 前主动中止。返工后：

- 先从 experiment receipt 中唯一且 hash 匹配的 provider manifest digest 安全解析 manifest path，再从该
  path 所属的最具体 artifact root 定位 provider receipt；
- formal/development 测试均使用真实 canonical receipt、root alias、hash、stage/scope 与 input/output
  closure，不再 monkeypatch receipt verifier；
- formal 测试逐项篡改 provider receipt 的 stage、input hash 与 `../` 逃逸路径，均由 public verifier
  fail closed；既有 nested-root 测试继续验证最长匹配 alias。

## 验证

- Windows Miniforge：扩大定向回归 `97 passed, 5 skipped`；定向 Ruff 与 mypy 通过。
- WSL Miniforge base：对应回归 `100 passed, 2 skipped`；定向 Ruff 与 mypy 通过。
- WSL py312 正式产物探针严格只读：另行记录当前 source/config identity 与历史 G8 manifest 的漂移，
  并使用历史 manifest 对应的冻结 source/config 身份单独验证分根 receipt 定位。该探针不写正式目录，
  也不把历史 G8 残留升级为当前 Gate 证据。

## 边界与遗留

- 本包只修复 verifier 的分根定位，不重新发布 formal G8。
- 既有 formal G8 的 code/config identity 已落后于当前源码；后续应在相关源码稳定后以新 identity 发布，
  不覆盖或伪装复用旧目录。
- Windows/DrvFS 验证不等于 Linux/ext4 Gate。
