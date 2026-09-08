# M3 G1 P0I：停牌除权复牌日因子延迟闭包主 Agent 最终验收报告

状态：**P0I 通过；G1 仍阻塞于下一独立缺陷 600733**

日期：2026-07-29（Asia/Shanghai）

## 1. 验收结论

P0I 的目标行为已闭包：

- `FULL_DAY` 除权日因子稳定且 declared 无法解释时，事件只延迟到连续全天停牌后的首个复牌日；
- 非停牌、精确日已可解释、缺口、无复牌、首复牌不可解释等路径继续 fail closed；
- 600717.SH 的正式形状已越过，正式 candidate 的下一首错变为 600733.SH；
- recon 身份已升级并在 execution、candidate、planning、REFERENCE 测试面统一为
  `tushare_factor_daily_preclose_suspension_resume_v6`；
- R1 的旧 v5 身份断言和 R2 的交付报告行尾/错误自报均已完成外部实现—独立复验闭环。

本结论只接受 P0I，不宣称 G1、REFERENCE、PREPARE、PUBLISH、Linux publish Gate 或新
`VerifiedG1Release` 通过。旧 release `3c9bda84…` 仍不得用于 G2A。

## 2. 交付链

| 阶段 | 提交 | 结论 |
|---|---|---|
| P0I 冻结 | `a993600` | 停牌除权复牌日延迟合同 |
| 外部实现 | `e2a3afb` | v6 延迟闭包与测试矩阵 |
| 初验更正 | `e8e1cbb` | FAIL：planning/reference 残留 v5 |
| R1 冻结 / 实现 | `cb8dae8` / `66052b0` | 身份断言同步 |
| R1 独立复验 | `d090d1e` | FAIL：报告行尾与 git-check 自报不真实；功能面 308 passed、5 skipped |
| R2 冻结 / 实现 | `7d42d74` / `15c5c0d` + `4ea5266` | 正向更正报告，保留历史坏提交 |
| R2 独立复验 | `6fcf15c` | PASS；最小两测、diff/show check 与对抗探针通过 |

同路径较早的 `de5aa6d` PASS 报告已被 `e8e1cbb` 明确覆盖，不作为验收依据。

## 3. 主 Agent 实跑

### Windows 原生

```text
D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_m3_execution_facts.py -k p0i \
  tests/unit/test_m3_g1_candidate.py -k "p0i or p0d_versions" \
  tests/unit/test_m3_g1_planning.py::test_static_plan_from_c0_and_forged_identity \
  tests/unit/test_m3_reference.py::test_p0e_reconciliation_version_propagates_in_build_spec -q
```

结果：`16 passed, 158 deselected`，退出码 0。

### WSL Miniforge base

同一聚焦命令在：

```text
/home/mabw/AI_Coding_win/QuantitativeTrading
/home/mabw/miniforge3/bin/conda run -n base
```

结果：`16 passed, 158 deselected`，退出码 0；WSL HEAD=`6fcf15c`。

WSL `git status` 对共享 Windows 工作树显示额外源码/测试行尾差异；Windows 权威状态未显示这些文件为
本轮改动，本验收未暂存、归一化或覆盖它们。

### 外部独立长回归

`d090d1e` 的全新外部独立复验实际运行：

```text
pytest test_m3_execution_facts.py test_m3_g1_candidate.py
       test_m3_g1_planning.py test_m3_reference.py -q
```

结果：`308 passed, 5 skipped`，退出码 0。R2 未改代码/测试，按测试分层规则不机械重跑。

## 4. 正式零网络证据

正式 `status` 产物：

```text
artifacts/g1_component_diag_20260722/formal_status_p0i_v1.out.log
```

结果：

```text
outcome=FAILED
error_code=G1_WORKFLOW_QUALITY_FAILED
error_operation=INSPECT
```

下一首错捕获：

```text
artifacts/g1_component_diag_20260722/p0i_status_first_failure_v2.json
recon_method_version=tushare_factor_daily_preclose_suspension_resume_v6
symbol=600733.SH
effective_date=2018-09-19
error=G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED
```

这证明 P0I 实现已越过原 600717 首错，但不证明正式 G1 candidate 已建成。600733 的冻结证据见
`docs/framework/agent/20260729_P0I后正式status首败_600733有事件declared不合.md`。

## 5. 提交卫生与已知非阻断项

- P0I 实现、R1/R2 实现和最新独立复验提交各自 `git show --check` 通过；
- `tests/unit` 不再含 `tushare_factor_daily_preclose_v5` 当前 recon 期望；
- 从 P0I 最初冻结点跨越全部历史报告执行宽范围 `git diff --check` 时，`e8e1cbb` 初验报告保留四个
  Markdown 双空格硬换行。它不在实现白名单、不影响代码/身份/测试，且历史 FAIL 报告内容已被冻结；
  本轮不为该历史排版再开启第四次返工。

## 6. 下一步

为 600733 单独冻结新合同。不得：

- 放宽 `factor_ratio_rtol`；
- 把有事件跳变降级为 `NO_EVENT`；
- 复用旧 REFERENCE/PREPARE/PUBLISH 身份；
- 在未查明两条同日 stock 事件的经济身份和 Tushare 因子口径前直接去重或改比例。
