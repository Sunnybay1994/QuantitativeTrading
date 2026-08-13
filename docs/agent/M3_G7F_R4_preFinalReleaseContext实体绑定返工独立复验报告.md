# M3 G7F R4：pre-final Release/Context 实体绑定返工独立复验报告

日期：2026-08-10  
角色：未参与 G7F R4 实现的全新外部独立初验 Agent（生产/实现测试/任务单/既有报告只读；本文件为唯一写入）  
任务单：[`M3_G7F_R1正式A股三场景回测Artifact任务单.md`](M3_G7F_R1正式A股三场景回测Artifact任务单.md) §18  
交付报告：[`M3_G7F_R4_preFinalReleaseContext实体绑定返工交付报告.md`](M3_G7F_R4_preFinalReleaseContext实体绑定返工交付报告.md)  
前置 FAIL：[`M3_G7F_R3_正式G1Quality来源闭包与路径类型分离独立复验报告.md`](M3_G7F_R3_正式G1Quality来源闭包与路径类型分离独立复验报告.md) 主验补充 S1/S2

## 结论

**PASS（仅解锁主验与后续 G8 同步返工）**。§18 合同在同 fresh context 下已关闭 R3 补充 S1/S2；本轮实现者未用对抗双平台稳定拒绝。不得宣主验通过、G7F/G8/ext4 或 M3 Gate PASS。

## 逐项核对

| 合同项 | 证据 | 结果 |
|---|---|---|
| fresh context exact `release: VerifiedG1Release` + 构造时 nested exact + 私有实体 snapshot | `BacktestArtifactFreshVerificationContext` init 含 `release`；`_source_snapshot` 为 `init=False/repr=False/compare=False`；`__post_init__` 调 `_capture_formal_g1_source_snapshot`（递归 `G1Release`/`G1ManifestV5`/`G1QualityReportV1`/17 artifact paths + root/manifest/quality/八表实体） | PASS |
| 所有 formal 入口在 29 输出读取 / G7E 回放前重验绑定 | `backtest_artifact_input_paths`→`_validate_formal_input_identity`；`build`/`verify_backtest_build_output`/`verify_backtest_artifact`→`_formal_bundle`/`_verify_formal_build_tree`→`_validate_formal_inputs`→`_validate_formal_release_context_binding`（caller exact、与 `fresh_context.release` 逐字段相等、重算 snapshot） | PASS |
| portable 输出无 inode/device | 合法 tree 下全部 `.json` 扫描无 `"inode"`/`"device"`/`st_ino`；`BacktestBundleManifestV1`/`BacktestScenarioManifestV1` 字段无实体身份项；snapshot 仅 process-local | PASS |
| development API / G8 不变 | `BacktestArtifactUpstreamPaths` 仍四路径含 `g1_receipt_path`；formal 仍三路径；本包未改 G8 production；G8 继续因旧 context 缺 `release` 暂停 | PASS* |
| R3 补充 S1/S2 关闭（同 context） | 实现者 `test_r4_...`：SimpleNamespace nested + exact copied-root `replace(VerifiedG1Release)` → pre-final 稳定 `M3_A_SHARE_BACKTEST_ARTIFACT_INVALID`；独立 A1 同对象 in-place exact copied-root 亦拒 | PASS |

\*工作树另有既有/并发脏文件（含部分 G8 文档与 `orchestration.py`），不计入本包 R4 主张；初验未改生产或实现者测试。

## 实现者未用对抗（双平台）

独立脚本：`.tmp-g7f-r4-indep-adversarial.py`（证据 `.tmp-g7f-r4-indep-adv-win.txt` / `.tmp-g7f-r4-indep-adv-wsl.txt`）。相对实现者 `test_r4_prefinal_release_context_entity_binding` 的增量：

| ID | 攻击面（相对实现者增量） | Win | WSL |
|---|---|---|---|
| A1 / A1b | **同一** context 绑定的 `VerifiedG1Release` 对象上 in-place exact `G1Release`+`artifact_paths` 指到 same-bytes copied root（实现者 S2 换的是另一 `VerifiedG1Release` kwargs）；pre-final + public helper | PASS reject | PASS |
| A2a–c | same-path **manifest / quality / market(`bar_1d`)** inode 重写（实现者仅 quality） | PASS reject | PASS |
| A3a–c | nested `manifest_path`/`quality_path` off-root `__setattr__`；`artifact_paths` 指 copied；nested `quality`→`SimpleNamespace` | PASS reject | PASS |
| A4a–b | 私有 snapshot 伪造 inode；`object.__setattr__(context,"release", exact copied VerifiedG1Release)` | PASS reject | PASS |
| A4c / A5 | `dataclasses.replace(context, release=exact_copied)` **新建** context；同 tree 上 pre-final | `OK` / `CONTENT_PASS_NEW_REQUEST` | 同左 |
| A6 / A7 | final+receipt 仍拒 copied caller release；build 同 context copied 在 P0 写入前拒且空输出根 | PASS reject | PASS |
| PORTABLE | 合法 29 文件 JSON 无 inode/device 泄漏 | PASS | PASS |

### 新 context 边界（如实记录）

§18.1：「新建另一 context 表示新的验证请求，不在本包声明跨请求持久来源证明。」  
A5 在 **新** `BacktestArtifactFreshVerificationContext(release=exact_copied)` 上对既有 tree 跑 `verify_backtest_build_output` 得到 `CONTENT_PASS_NEW_REQUEST`。这不是同 context 逃逸，而是合同允许的「新请求」边界；同 context 攻击（A1/A4b/A7）与 final+receipt（A6）仍 fail-closed。

## 定向验证证据

Windows（`D:\Miniforge3\python.exe`，`PYTHONPATH=<worktree>/src`）：

| 项 | 结果 | 证据 |
|---|---|---|
| targeted R4 | `1 passed`，594.88s | `.tmp-g7f-r4-indep-win-targeted.txt` |
| G7F unit+golden | `12 passed`，1400.66s | `.tmp-g7f-r4-indep-win-g7f.txt` |
| 邻接（排除 G8） | `128 passed`，768.77s | `.tmp-g7f-r4-indep-win-adj.txt` |
| R2 fixed-order | `4 passed`，221.03s | `.tmp-g7f-r4-indep-win-r2-order.txt` |
| Ruff / mypy / cold / diff-check | All checks passed / Success / `cold-ok` / `diff-check-ok` | `.tmp-g7f-r4-indep-win-{ruff,mypy,cold,diffcheck}.txt` |
| 对抗 | `SUMMARY_BAD 0` | `.tmp-g7f-r4-indep-adv-win.txt` |

WSL Miniforge `base`（`/mnt/f/.../m3-g4-formal`，`stat -f -c %T` → `wslfs` / DrvFS，非 ext4 Gate）：

| 项 | 结果 | 证据 |
|---|---|---|
| targeted R4 | `1 passed`，620.01s | `.tmp-g7f-r4-indep-wsl-targeted.txt` |
| G7F unit+golden | `12 passed`，1039.59s | `.tmp-g7f-r4-indep-wsl-g7f.txt` |
| 同构邻接（排除 G8） | `128 passed`，417.46s | `.tmp-g7f-r4-indep-wsl-adj.txt` |
| R2 fixed-order | `4 passed`，110.22s | `.tmp-g7f-r4-indep-wsl-r2-order.txt` |
| Ruff / mypy / cold | 通过 / Success / `cold-ok` | `.tmp-g7f-r4-indep-wsl-{ruff,mypy,cold}.txt` |
| 对抗 | `SUMMARY_BAD 0` | `.tmp-g7f-r4-indep-adv-wsl.txt` |

警告仅为既有 Pandera/Polars deprecation 与 `.pytest_cache` 无写权限；未联网、add、commit；未改生产或实现者测试。

## R3 FAIL 闭环映射

1. **现象**：同 tree 上 exact copied-root / SimpleNamespace nested 使 pre-final unexpected pass。  
2. **根因**：context 未绑定 build-time release/实体 snapshot。  
3. **规则**：§18.2 / §17.2.5–17.3 共享闭包 + nested exact + 拒 same-bytes root replacement（同 context）。  
4. **最小复现（已关闭）**：实现者正式 S1/S2；独立 A1 同对象 exact copied-root。  
5. **新增测试**：实现者 `test_r4_prefinal_release_context_entity_binding`；独立 A1–A7。  
6. **通过条件**：本报告双平台 targeted/G7F12/邻接128/fixed-order4/Ruff/mypy/cold/diff + 对抗全绿。

## FAIL 清单

无。

## 残留（不构成初验 FAIL）

- 新 context + copied-root 的 pre-final 内容通过是 §18.1 明示边界，不提供跨请求持久来源证明。  
- 私有 snapshot 含平台 inode，仅 process-local，不得也不应进入 portable manifest/receipt/hash（本轮已扫）。  
- WSL `/mnt/f` 仅 DrvFS 兼容证据。  
- G8 仍需在 R4 主验 PASS 后另开同步返工；本报告不解锁 Gate。
