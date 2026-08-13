# M3 G7F R3：正式 G1 Quality 来源闭包与路径类型分离交付报告

日期：2026-08-10
角色：外部实现 Agent（全新会话）
状态：**实现者交付与双平台自测完成，待未参与实现的全新独立初验**
环境：Windows 原生 Miniforge 定向；WSL Miniforge `base`（DrvFS `/mnt/f`）兼容；默认不联网

## 1. 交付结论

已按任务单 §17 完成 formal/development 路径类型分离：保留 development 四路径
`BacktestArtifactUpstreamPaths`（含 `g1_receipt_path`）；新增并安全导出
`FormalBacktestArtifactUpstreamPaths`（仅 target/plan/experiment 三路径）。
`BacktestArtifactFreshVerificationContext.upstream_paths` exact 绑定 formal 三路径类型。
formal 21-input 第 12/13 项改为 G1 `manifest.json` + `quality.json`（quality 从
`VerifiedG1Release.release.quality_path` 派生并绑定 `quality_sha256`），禁止 fake G1 receipt
与兼容接受旧四路径类型。development `_receipt_inputs`/`_validate_upstream_receipts` 仍用
`g1_receipt_path` + development `receipt_sha256`。

本报告只声明实现者交付和自测完成，**不**声明独立初验、主验、G7F、G8、ext4 或 M3 Gate PASS。
G8 仍暂停，不得以兼容旧 formal context 类型绕过。

## 2. 关键实现

- `FormalBacktestArtifactUpstreamPaths`：三 `Path`、exact 去重；无 caller G1 path 入口。
- fresh context exact 拒绝 development 四路径 / duck / dict / subclass。
- `_formal_g1_quality_path` + `_formal_fresh_upstream_bytes`：强制 `root/quality.json` 且 bytes
  绑定 `release.quality_sha256`；不得从 G7A/G7B import 私有 helper。
- `_formal_receipt_inputs`：21 项顺序不变，G1 段为 manifest→quality→八表；禁 G1 段
  `receipt.json` 名；samefile alias fail-closed。
- development 路径与错误码、29 outputs、metrics、P0/G7E 调用链未改。
- `__init__.py` 仅新增 formal 类型安全导出。

## 3. 测试覆盖

- 正向 fixture 不创建/不依赖 fake G1 receipt；断言 21-input 第 12/13 项为 manifest/quality。
- R3 反例：quality missing/drift、根外 quality、伪 receipt 冒充 quality、quality↔receipt/
  market hardlink alias、same-bytes G1 whole-root 替换后 verify、旧伪 receipt 重签、
  development 四路径/dict 传入 formal API。
- 既有三次 actual G7E、Decimal/terminal、29-file、whole-bundle drift、golden 保持。

## 4. 验证证据（已落盘摘要，本轮未重跑长 pytest）

### Windows

| 项 | 结果 |
|---|---|
| G7F unit+golden | `11 passed`，754.22s（`.tmp-g7f-r3-win-g7f.txt`） |
| 邻接 G7B-R2/P0/F0/C/D/G7E(+golden) | `128 passed`，523.32s（排除 G8） |
| R2 fixed-order | `4 passed`，159.61s |
| development reporting | `10 passed`，204.00s |
| Ruff / mypy / cold / diff-check | 通过 / Success / `cold-ok` / 无 whitespace error |

### WSL base（DrvFS 兼容，非 ext4 Gate）

| 项 | 结果 |
|---|---|
| G7F unit+golden | `11 passed`，617.70s |
| 同构邻接 | `128 passed`，398.56s |
| R2 fixed-order | `4 passed`，109.58s |
| Ruff / mypy | 通过 / Success |
| cold | 原 `.tmp-g7f-r3-wsl-cold.txt` 为空；收尾短命令补证 `cold-ok`（worktree `src`） |

警告仅为既有 Pandera/Polars deprecation 与 `.pytest_cache` 无写权限，不改变结果。

## 5. 文件范围

1. `src/quant/backtest/a_share_reporting.py`
2. `src/quant/backtest/__init__.py`
3. `tests/unit/test_m3_g7f_formal_backtest_artifact.py`
4. `tests/integration/test_m3_g7f_formal_backtest_artifact_golden.py`
5. 任务单状态
6. 本交付报告

未修改 G8/G1/G7A/B/E/P0、contracts、schemas、config、receipt/StageRunner；未联网、add、commit。

## 6. 剩余风险与下一步

- G8 仍会因旧 formal 四路径 context 构造失败，需 R3 初验+主验后再开同步返工。
- 模块化 fixture 不重复证明完整 G1 retained release；来源闭包由 F0/G7B/G7E 邻接承担。
- WSL 证据在 DrvFS，不能表述为 Linux/ext4 Gate。
- 下一步：未参与本轮实现的全新外部 Agent 只写
  `docs/agent/M3_G7F_R3_正式G1Quality来源闭包与路径类型分离独立复验报告.md`，并增加未用反例。
