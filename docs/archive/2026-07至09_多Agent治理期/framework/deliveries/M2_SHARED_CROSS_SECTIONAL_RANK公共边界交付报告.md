# M2-SHARED-CROSS-SECTIONAL-RANK 公共边界交付报告

> 状态：`DELIVERY_READY / WINDOWS_DEVELOPMENT_VALIDATED`
>
> 资源边界：`RESOURCE_RELEASE / PYTHON0 / 0xF00_RESIDUE0 / DATA0 / ECONOMIC_IO0 / TRIAL0 / NETWORK0`

## 1. 交付范围

本次只新增任务书批准的四个实现者路径：

1. `src/quant/factors/cross_sectional_rank.py`
2. `tests/unit/test_cross_sectional_rank.py`
3. `tests/integration/test_shared_cross_sectional_rank_consumers.py`
4. `docs/framework/deliveries/M2_SHARED_CROSS_SECTIONAL_RANK公共边界交付报告.md`

任务书只读；独立 review 路径尚未由实现者创建。未修改 `quant.factors` facade、R14/R15/R21
消费者、Schema、config、runner、data 或其他生产/测试/文档路径。

## 2. 实现结果

`rank_cross_sectional_components` 是不读外部状态的单一纯函数，接受 exact ordered Polars 长表，返回
按 `signal_date, component, symbol` canonical 排序的 normalized rank 长表。

- 每个 `signal_date × component` 独立使用非 null `value` 有效集合。
- 排名为 ascending average tie；`n >= 2` 使用 `(average_rank - 1) / (n - 1)`。
- `n < 2` 整组 rank 为 null；全相等且 `n >= 2` 为 `0.5`。
- null key、duplicate key、non-finite value 均 fail closed；null value 保留 key 但不进入分母。
- 输入验证严格按 TYPE → SCHEMA → KEY_NULL → DUPLICATE_KEY → NON_FINITE → compute 的冻结全序。
- compute 或输出验证中的非公共异常统一收敛为
  `CROSS_SECTIONAL_RANK_INTERNAL_INVARIANT`，没有未受控 Polars 文本泄漏。
- 返回前重新核 exact schema/dtype、key 1:1、canonical order、duplicate、null pattern、finite/range，
  并把输出负零规范化为 `0.0`。

实现没有新增依赖、facade 别名、fallback、consumer import、IO 或可变全局状态。

## 3. 合同—静态证据映射

| 冻结合同 | 实现或测试证据 |
|---|---|
| `n=2` 得到 `0.0/1.0`；partial tie 使用 average rank | unit `test_two_values_and_partial_ties_use_average_normalized_rank` |
| 全相等、`n=0/1`、局部 null | unit `test_equal_null_and_small_groups_have_frozen_null_semantics` |
| component 使用不同有效集合，不预取交集 | unit `test_components_use_independent_valid_sets_without_intersection` |
| NaN/+Inf/-Inf 全局拒绝 | parametrized unit `test_non_finite_value_rejects_the_whole_call` |
| type/schema/key-null/duplicate exact code | unit `test_type_schema_key_and_duplicate_failures_are_exact` |
| compound-invalid total precedence 与行置换稳定 | unit `test_compound_invalid_precedence_is_permutation_stable` |
| compute/library 异常不穿透 | unit `test_compute_and_output_failures_use_the_internal_invariant` |
| 多日/多组件/行置换、输出 identity/range/负零 | unit `test_multiple_dates_components_and_input_permutations_are_canonical` |
| R14/R15/R21 全部只消费同一 fully-qualified identity | integration 三个中立 fixture；未 import consumer 模块或公式 |

这些测试合同已由第 5 节的 Windows 定向验证执行；其绿色结果不构成因子经济有效性或 Linux Gate 证据。

## 4. 静态检查与文件身份

首次静态交付阶段只执行了文本和 Git 只读检查；当时 Python、pytest、Ruff、mypy 和 cold import
均为 `UNRUN`。后续 Windows Validation1 在独立资源授权下完成，证据见第 5 节；本次仅更新报告，零 Python。

| 路径 | bytes | SHA-256 |
|---|---:|---|
| `src/quant/factors/cross_sectional_rank.py` | 4417 | `686df676bc484d85ea43f8a0c73ab6e22450a8cc0e5beb02ffc0dee88cbee30d` |
| `tests/unit/test_cross_sectional_rank.py` | 7808 | `67d602e4922849e88513e894e5e7133bc4f6567d9b076c6277ebb22266954479` |
| `tests/integration/test_shared_cross_sectional_rank_consumers.py` | 2462 | `589be42a432d847b6e1c3357973510958657f7f7462e5bb8b7e6a046946768c4` |

三条代码/测试路径静态文本核验为 UTF-8 no BOM、LF-only、CR0、NUL0、trailing whitespace 0、
single EOF LF；行长检查没有发现超过 100 字符的行。`git diff --check` PASS；cached0。

最终 delivery 自身身份和 exact dirty scope 由收件时 fresh 重算记录，避免在文件内写自指 SHA。

## 5. Windows Validation1 执行证据

保留证据根：
`artifacts/agent_runs/m2-shared-cross-sectional-rank-windows-validation1-20260902T130000Z`。
该 ignored no-clobber 根只读保留；所有阶段严格串行并以 exit `0\n` 闭合。

| 阶段 | 结果 | stdout bytes / SHA-256 |
|---|---|---|
| focused unit | `12 passed in 2.10s` | 101 / `749b9cfcca00ceb6d66adc80b2dc8dfbb6b8b5a93f59205be7da53b402241eea` |
| focused integration | `3 passed in 1.75s` | 100 / `e866805c1e524fecead47d5f1d08f3dc401557033fea4811e89730ad1d2b258f` |
| Ruff exact3 | PASS | 20 / `a4443afdcfb6d7363adb285762515ccf7cf50473b1a05c20c1a50f6bed4d26b0` |
| mypy production | PASS | 43 / `8e63ae22e8213e327a5e9cbd584067681681bd8ef7f25c869877887ccdcfc4ff` |
| cold import/public identity | PASS | 18 / `f2fa5abb3a94f7638617a512fe5f805721df611e0918049ef9780a23a332da3b` |
| exact6 scope | PASS | 393 / `c9e020e4ffdcc157944e5ddded4fcd0b823ef314322bc5a3ed564a597637b618` |

六阶段 stderr 均为 exact0 bytes / SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；exit 文件均为 exact
`0\n`（2 bytes）/ SHA-256
`9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`。`summary.log` 为
103 bytes / SHA-256 `e7eec3e779bf9152673f07663e950fdb66b5ccc17874109ec2f21c7a61c417b7`。

结束现场：Validation1 temp/basetemp 已精确清理；Python/pythonw=0；exact affinity `0xF00` residue=0；
actual exact6、cached0、ordinary `git diff --check` PASS；资源已明确 `RESOURCE_RELEASE`。

### 5.1 Final evidence review 与清理闭包

首轮最终证据复核永久记录为：`FINAL_EVIDENCE_REVIEW_FAIL / P0=0 / P1=1 / P2=0`；review
identity 为 12227 bytes / SHA-256
`bd4907c5ccfd75f824894d5a7c9790b33d4a14f879f4d771ce7bf47874e968c3`。该 finding 指向验证后
worktree-root `.ruff_cache` residue，不改写 Validation1 已完成的产品阶段结果，也不得删除或改写审查历史。

获得精确清理授权后，本轮只删除 worktree-root `.ruff_cache`（删除前为 5 个文件；实际退出审计同时列举
目录项），未清理 retained Validation1 evidence。fresh 清理后口径为：`.ruff_cache`、`.pytest_cache`、
`.mypy_cache`、`__pycache__` residue count 均为 0；Validation1 temp 仍 absent；Python/pythonw=0；exact
affinity `0xF00` residue=0；actual exact6、cached0、ordinary `git diff --check` PASS。最终
`RESOURCE_RELEASE` 以该清理后 fresh 证据为准。本次没有重跑任何验证阶段。

验证上限仅为 `WINDOWS_DEVELOPMENT_VALIDATED`。Linux/WSL Gate 仍 `UNRUN / OPEN`，且本证据不表示
rank 经济有效、consumer 已迁移、项目 Gate 关闭或合流完成。

## 6. 后续步骤与剩余风险

1. 由同一独立 reviewer 基于清理后 fresh residue 证据复核原 P1；不得改写首轮 review fail 历史。
2. review PASS 与 Windows 绿证据齐备后，仍须由统筹授权 safe commit、合流及必要 integration 回归。
3. R14、R15、R21 只能分别基于 merged public SHA 迁移，禁止绑定本 worktree 未合流 bytes。

剩余风险是 Linux 文件系统和 WSL Miniforge `base` 尚未终验，且本任务没有也不应验证任何因子经济效果。
