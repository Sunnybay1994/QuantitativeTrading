# M3 G1-P4B 独立初验一次返工独立复验报告

日期：2026-07-15  
角色：独立外部复验 Agent（全新上下文；未参与本轮返工实现；只读验收）  
实际模型标识：`cursor-grok-4.5-high`  
返工任务单：[`M3_G1_P4B独立初验返工任务单.md`](M3_G1_P4B独立初验返工任务单.md)  
独立初验（否决）：[`M3_G1_P4B跨源证据独立初验报告.md`](M3_G1_P4B跨源证据独立初验报告.md)  
一次返工交付：[`M3_G1_P4B独立初验一次返工交付报告.md`](M3_G1_P4B独立初验一次返工交付报告.md)  
原任务书：[`M3_G1_P4B跨源证据外部闭环任务单.md`](M3_G1_P4B跨源证据外部闭环任务单.md)（§5.4 / §7 / §8）

## 结论：**通过**

可交主 Agent 终验。原 ADV5 / ADV9 已独立重放为必拒；F1–F3 逐项有代码与对抗证据；新增 ≥4 个实现者未使用反例（含 ≥2 个针对 F3 或 detail schema）全部拒绝成功；定向 / P4B+connector / P4A / 全量 pytest / Ruff / mypy 均为绿色。

本结论**不**宣布 B4 / G1 / M3 / 任一 Gate 通过。

## 1. 复验边界与环境

- 只读：未修改生产代码、既有测试、配置、路线图或任何历史报告。
- 仅新增本报告；对抗与静态检查脚本置于系统临时目录
  `C:\Users\mbw\AppData\Local\Temp\p4b_reverify\`（WSL：`/mnt/c/Users/mbw/AppData/Local/Temp/p4b_reverify/`），报告完成后已删除。
- 环境：Windows `cursor-agent` 启动 → `wsl.exe` →
  `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` →
  `/home/mabw/miniforge3/bin/conda run -n base`。未使用 Windows Python/conda 执行项目测试。
- 零真实网络、零 token、零 `_old/`、零实盘/外部状态修改。

## 2. 文件范围与公共签名

| 检查项 | 结果 |
|---|---|
| 返工允许文件 | `src/quant/data/m3_reference.py`、`tests/unit/test_m3_reference.py`、一次返工交付报告（交付声明）；connector / P4A / RawStore / 配置 / 路线图 / 历史报告未作为本轮返工改动面 |
| 公共导出 | `__init__.py` 仍含冻结类型与五函数（含 `CrossSourceReconciliationBundle`） |
| Bundle 字段签名 | 仍为 `sample_plan / reference_receipts / detail / detail_sha256 / summary / summary_sha256 / issues / passed`；未见公共字段或函数签名漂移 |
| 生产路径 | `m3_reference.py` 静态无 `os.replace` / `os.rename` / `import socket` |
| Shared helper | `_derive_cross_source_from_detail` 定义 1 次；`reconcile_cross_source` 与 `CrossSourceReconciliationBundle.__post_init__` 各调用 1 次 |
| 值对象非法输入 | `G1CrossSourcePolicy(price_atol=NaN)`、`CrossSourceSamplePlan(...坏 hash...)` 仅稳定 `ValueError`，观察面无 raw/路径/Polars 底层泄露 |

## 3. F1–F3 逐项映射（非仅看新增测试绿色）

### F1：同一 detail 上不可伪造 summary/issues

| 合同要求（返工任务单 §2） | 代码证据 | 复验证据 |
|---|---|---|
| 共用纯 helper 派生 stats/issues | `_derive_cross_source_from_detail`；bundle 与 reconcile 共用 | 静态 `derive_def=1, derive_calls=2` |
| detail schema/dtype/3000/键集合/排序 | helper 内精确列、dtype、行数、键集合、排序校验 | NEW_R1（同键重复保 3000）、NEW_R2（`field` List dtype）必拒 |
| missing_side / null / finite / matched 闭包 | NONE 路径重算 abs/rel/tol/matched；非法只抛 `ValueError` | NEW_R3（matched 与 diff/tol 自洽伪造）必拒；值对象脱敏 PASS |
| BOTH 双侧计数与 evidence | `PRIMARY/BOTH` 与 `REFERENCE/BOTH` 各计；`count=两侧之和` | NEW_R4（BOTH 下 undercount + 伪造 issue count）必拒 |
| 重算 field stats / mismatch / issues / passed / hash | bundle 逐项与 `derived` 比较；issues 精确相等 | REPLAY_ADV5 必拒；实现者 ADV5 变体定向测试 7 passed 之一 |

### F2：跨源 issue 必须为 ERROR

| 合同要求 | 代码证据 | 复验证据 |
|---|---|---|
| 两码均为 ERROR | `issue_item.severity != "ERROR"` → `ValueError` | REPLAY_ADV9：MISMATCH / INCOMPLETE 的 WARNING 均必拒 |

### F3：bundle 可见闭包

| 合同要求（返工任务单 §4） | 代码证据 | 复验证据 |
|---|---|---|
| `primary_candidate_key` / `sample_plan_sha256` 与 sample_plan 相等 | bundle `__post_init__` 比较 | 实现者 `test_f3_*`；NEW_R6（wholesale 换 plan、summary 未重绑）必拒 |
| 守恒 30/20/600/5/3000 | summary 守恒字段校验 | 定向 + 全量绿色 |
| 恰好 30 receipts、排序、request_id 唯一；`reference_receipt_digests == sorted(unique(stable_response_sha256))` | 数量/排序/唯一 + digests 投影比较 | NEW_R5（30 receipts 中 digest 重复 → unique=29，summary 仍挂 30）必拒 |
| `summary.detail_sha256 == bundle.detail_sha256` | 与 derived digest 双侧比较 | 实现者 F3 漂移测试 |
| 不夸大 `primary_receipt_digests` 自包含 | 代码未对 primary digests 做超出字段可见范围的假验证 | 与合同一致；未伪称可独立关闭 |

## 4. 重放原 ADV5 / ADV9

临时脚本：`/mnt/c/Users/mbw/AppData/Local/Temp/p4b_reverify/run_reverify.py`（已删除）。

| ID | 操作 | 结果 |
|---|---|---|
| REPLAY_ADV5 | 同一 mismatch detail + 真实 detail hash + 自洽全绿 summary/hash + `issues=()` + `passed=True` | **必拒** `ValueError` |
| REPLAY_ADV9_MISMATCH | `CROSS_SOURCE_MISMATCH` + `severity="WARNING"` | **必拒** |
| REPLAY_ADV9_INCOMPLETE | `CROSS_SOURCE_INCOMPLETE` + `severity="WARNING"` | **必拒** |

与初验报告 ADV5/ADV9 失败模式对照：原“构造器接受”已翻转。

## 5. 新增对抗反例（实现者未使用；≥4，其中 ≥2 针对 F3 / detail schema）

| ID | 目标 | 反例 | 结果 |
|---|---|---|---|
| NEW_R1 | F1 detail schema | 保留 3000 行：末行改为首行键的 duplicate，同时丢掉原末键 | 必拒 |
| NEW_R2 | F1 detail schema | `field` 列改为 `List[Utf8]`（实现者仅测 Categorical） | 必拒稳定 `ValueError`，无 Polars 泄露 |
| NEW_R3 | F1 matched 闭包 | `matched=True` 但 `abs_diff > tolerance`，并配全绿 summary/hash | 必拒 |
| NEW_R4 | F1 BOTH | 一键五格改为 `BOTH`；summary `missing_reference_rows=0` 且 INCOMPLETE `count=1`（应为双侧计 2） | 必拒 |
| NEW_R5 | **F3** digests | 30 receipts 中两枚 `stable_response_sha256` 重复（unique=29），summary digests 仍为原 30 | 必拒 |
| NEW_R6 | **F3** sample_plan | wholesale 换成另一自洽 `sample_plan`，summary 的 key/hash 未重绑 | 必拒 |
| NEW_R7 | field max diff | `max_abs_diff=NaN` | 值对象层必拒 `ValueError` |

另：SHARED_HELPER、NO_REPLACE_RENAME_SOCKET、VO_policy_nan、VO_sample_plan_bad_hash 均为 PASS。  
对抗汇总：**12/12 passed**。

## 6. 命令与真实结果

环境前缀：

```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base --no-capture-output
```

| 命令 | 结果 |
|---|---|
| 独立对抗 `run_reverify.py` | **12/12 passed**（含 ADV5/ADV9 重放与 NEW_R1–R7） |
| 静态 `static_check.py` | exports_ok；no_forbidden_ops；derive 1 def / 2 calls；bundle_fields_ok |
| `pytest -q tests/unit/test_m3_reference.py -k "adv5 or adv9 or f3 or bundle_constructor"` | **7 passed**, 90 deselected，约 68.6s |
| `pytest -q tests/unit/test_m3_reference.py tests/unit/test_baostock_connector.py` | **116 passed**，约 194.4s |
| `pytest -q tests/unit/test_m3_g1_candidate.py` | **33 passed**，约 348.1s |
| `pytest -q`（全量） | **752 passed**，约 590.0s |
| `python -m ruff check src tests` | **All checks passed** |
| `python -m mypy src` | **Success: no issues found in 78 source files** |

大量既有 Pandera/Polars deprecation warnings 不构成否决依据。

## 7. 限制与残余观察

- 未实现 / 未验收 P4C；不得开始下游包或以本报告勾选路线图。
- `primary_receipt_digests` 相对原始 candidate receipts 的来源证明仍属 `reconcile_cross_source` + P4C 重执行范围（合同已冻结）；bundle 不夸大自包含。
- 整套另一真实自洽来源的 wholesale detail+summary 替换，仍需由重执行区分（§8.9）；本轮确认的是**同一 detail 上撒谎**与 **F3 可见闭包**已关闭。
- 初验曾提及的 `missing_primary` 在 planner 只从 bars 取样时实际不可达、以及 raw symlink 错误码选择，不在本返工合同 F1–F3 内，未作为本轮否决项。

## 8. 复验声明

**独立复验结论：通过。**  
可交主 Agent 执行最终契约 / 真实依赖 / 回归与文档一致性验收。  
不得据此宣布 B4 / G1 / M3 / Gate 通过；不得跳过主验勾选路线图。
