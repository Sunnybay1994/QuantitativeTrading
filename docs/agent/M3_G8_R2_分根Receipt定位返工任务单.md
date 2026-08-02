# M3-G8-R2 分根 Receipt 定位返工任务单

## 背景与现象

正式 G2A snapshot、G2B provider 与 G8 experiment 可以位于不同 artifact root。现有
`verify_experiment_identity` 却用 snapshot root 同时定位 snapshot/provider receipt，导致各自
合法且已严格验证的分根正式产物在 G8 最终验证阶段以 `receipt missing` 失败。

## 冻结不变量

- snapshot receipt 必须从 `snapshot.root` 所属 artifact root 定位。
- provider receipt 必须从 `provider.root` 所属 artifact root 定位。
- 两个 receipt 仍分别执行 E3 路径边界、字节哈希与闭包验证；不得因分根放宽任何验证。
- development example 与 formal 共用同一定位规则，但类型、stage 名称与 Gate 身份仍严格隔离。
- 不修改、不删除、不重启既有正式 G1/G2/G8 产物或 journal；既有失败残留只作为只读诊断证据。

## 最小实现范围

- `src/quant/research/m3/labels.py`
- `tests/unit/test_m3_experiment_identity.py`
- 本任务单及对应交付/验收报告

## 反例与通过条件

反例：snapshot 位于 G2A root，provider 位于独立 G2B root，两个 root 各自保存对应 receipt。
验证器若仍从 G2A root 查找 provider receipt，测试必须失败。

同一不变量适用于 label 对 experiment receipt 的 fresh 复验：provider receipt 必须由 receipt 中已验真的
provider manifest digest 所属 root 定位。测试必须继续进入 public label verifier，并覆盖错误 stage、hash、
input closure 与路径逃逸；不得以 mock 调用参数代替真实 E3 验证。

通过条件：

1. 分根回归测试通过，原有 experiment identity 测试无回归；
2. Windows 与 WSL base 定向 Ruff、mypy、pytest 通过；
3. WSL py312 对既有正式 G2A/G2B/G2C/G8 产物执行只读严格验证，能穿过原 provider-receipt
   定位失败点；
4. 独立审查确认未放宽 identity/receipt closure，且未写正式目录。
