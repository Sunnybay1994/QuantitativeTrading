# M3 G7A R3：正式 G1 Quality 来源闭包独立复验报告

日期：2026-08-10  
角色：未参与实现的全新外部独立初验 Agent（只读生产/测试/任务单/既有报告；本文件为唯一写入）  
任务单：[`M3_G7A_R1正式TargetArtifact任务单.md`](M3_G7A_R1正式TargetArtifact任务单.md) §10  
交付报告：[`M3_G7A_R3_正式G1Quality来源闭包返工交付报告.md`](M3_G7A_R3_正式G1Quality来源闭包返工交付报告.md)

## 结论

**PASS（仅解锁主验）**。未发现 §10 合同级缺陷；不得宣 Gate / 主验通过 / G7B·G7F·G8 恢复。

## 逐项核对

| 合同项 | 证据 | 结果 |
|---|---|---|
| formal 14-input = manifest → quality → eligible → feature/prediction/folds/experiment | `_formal_receipt_inputs` 固定 14 元组；闭环断言 `paths[1]==quality_path` 且 `name==quality.json`；`len(set(normalized))==14` | PASS |
| quality sha/path/fresh 绑定 | `_formal_g1_quality_path` 强制 `root/quality.json`；`_formal_fresh_upstream_bytes` 绑定 `quality_sha256`；build/verify 入口经 `_validate_formal_inputs` 调用 | PASS |
| development 不变 | `_fresh_upstream_bytes` / `_receipt_inputs` 仍使用 `root/receipt.json` + `receipt_sha256`；邻接 development 定向绿 | PASS |
| 无伪 G1 receipt 正向依赖 | fixture 根仅 manifest/quality/eligible，断言无 `receipt.json`；旁路 decoy 不入闭包；G1 前三项禁 `receipt.json` 名 | PASS |
| 白名单/禁改 | R3 相关写入限于 `targets.py`、formal 测试、任务单状态、交付报告；`m3_release.py` 无 diff；development 测试文件未改 | PASS* |

\*工作树另有大量既有脏文件（G4–G8 等），不在本包 R3 主张范围；初验未将其计入本包变更。

## 实现者未用对抗（双平台）

独立脚本 `.tmp-g7a-r3-indep-adversarial.py`（不改生产/测试）：

| ID | 攻击面（相对实现者 suite 增量） | Win | WSL |
|---|---|---|---|
| A1 | quality↔eligible same-bytes hardlink alias（实现者仅 quality↔manifest） | PASS reject alias | PASS |
| A2 | `quality_path` 指向根外 hardlink 别名（非 exact `quality.json`） | PASS `M3_TARGET_ARTIFACT_INVALID` | PASS |
| A3 | 旧伪 G1 receipt 整包合法重签后 verify | PASS reject | PASS |
| A4 | 整根 G1 root 替换 + 旧 `quality_sha256` 绑定 | PASS reject | PASS |
| A5 | 对 `_formal_fresh_upstream_bytes` 注入含绝对路径 hostile（实现者打的是 prediction verify） | PASS 仅 `M3_TARGET_ARTIFACT_INVALID`、无路径泄漏 | PASS |
| A6 | quality 单字节漂移后再 verify | PASS reject | PASS |

## 定向验证证据

Windows（`D:\Miniforge3\python.exe`，`PYTHONPATH=src`）：

- formal + development 邻接 pytest：`11 passed`，224.58s（`.tmp-g7a-r3-indep-win.txt`）
- Ruff：`targets.py` + formal 测试 All checks passed
- mypy：`targets.py` Success
- cold import：`G7A_LIGHT_IMPORT_PASS`
- 对抗：6/6 PASS（`.tmp-g7a-r3-indep-adv-win.txt`）

WSL Miniforge `base`（`/mnt/f/.../m3-g4-formal`）：

- 同节点 pytest：`11 passed`，94.98s（`.tmp-g7a-r3-indep-wsl.txt`）
- Ruff / mypy 通过；cold import `G7A_LIGHT_IMPORT_PASS`
- `stat -f -c %T .` → `wslfs`（DrvFS 兼容，非 ext4/Linux Gate）
- 对抗：6/6 PASS（`.tmp-g7a-r3-indep-adv-wsl.txt`）

未 add/commit/联网；未改生产或实现者测试。

## 残留（不构成初验 FAIL）

- 父 SSOT 骨架表仍可能写 “manifest/receipt/eligible”；表文同步属主 Agent。
- 未跑真实全折 `VerifiedG1Release` 主验链。
- WSL `/mnt/f` 仅 DrvFS 兼容证据。

## FAIL 清单

无。
