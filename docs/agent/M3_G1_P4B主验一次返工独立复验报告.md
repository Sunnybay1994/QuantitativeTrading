# M3 G1-P4B 主验一次返工独立复验报告

日期：2026-07-15  
角色：独立外部复验 Agent（全新上下文；未参与本轮返工实现；只读验收）  
实际模型标识：`cursor-grok-4.5-high`  
主验一次返工任务单：[`M3_G1_P4B主验一次返工任务单.md`](M3_G1_P4B主验一次返工任务单.md)  
主验一次返工交付：[`M3_G1_P4B主验一次返工交付报告.md`](M3_G1_P4B主验一次返工交付报告.md)  
前置独立初验返工：[`M3_G1_P4B独立初验返工任务单.md`](M3_G1_P4B独立初验返工任务单.md)  
前置独立复验：[`M3_G1_P4B独立初验一次返工独立复验报告.md`](M3_G1_P4B独立初验一次返工独立复验报告.md)

## 结论：**通过**

可交主 Agent 再终验。主验三个隐藏反例（H1/H2/H3）已独立重放为必拒；H1–H3 合同有代码与对抗证据；新增 ≥4 个实现者未使用变体全部符合预期；定向 / P4B+connector / P4A / 全量 pytest / Ruff / mypy 均为绿色。

本结论**不**宣布 B4 / G1 / M3 / 任一 Gate 通过。

## 1. 复验边界与环境

- 只读：未修改生产代码、既有测试、配置、路线图或任何历史报告。
- 仅新增本报告；对抗与检查脚本置于系统临时目录
  `C:\Users\mbw\AppData\Local\Temp\p4b_main_reverify\`（WSL：`/mnt/c/Users/mbw/AppData/Local/Temp/p4b_main_reverify/`），报告完成后已删除。
- 环境：Windows `cursor-agent` 启动 → `wsl.exe` →
  `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` →
  `/home/mabw/miniforge3/bin/conda run -n base`。未使用 Windows Python/conda 执行项目测试。
- 零真实网络、零 token、零 `_old/`、零实盘/外部状态修改。

## 2. 文件范围与公共签名

| 检查项 | 结果 |
|---|---|
| 返工允许文件 | `src/quant/data/m3_reference.py`、`tests/unit/test_m3_reference.py`、主验一次返工交付报告；connector / P4A / RawStore / 配置 / 路线图 / 历史报告未作为本轮验收改动面 |
| 本复验写入 | 仅本报告；临时对抗脚本未进入仓库 |
| Bundle 公共字段 | 仍为 `sample_plan / reference_receipts / detail / detail_sha256 / summary / summary_sha256 / issues / passed` |
| 生产路径 | `m3_reference.py` 静态无 `os.replace` / `os.rename` / `import socket` |
| Shared helper | `_derive_cross_source_from_detail` 定义 1 次；`_validate_present_side_value` 定义 1 次；derive 由 reconcile 与 bundle 共用 |
| 零网络 | 对抗路径 `socket.connect` 打桩下 `reconcile_cross_source` 仍成功 |

## 3. H1–H3 逐项映射（非仅看新增测试绿色）

### H1：缺失行 tolerance 必须 exact `0.0`

| 合同要求 | 代码证据 | 复验证据 |
|---|---|---|
| 缺侧 tolerance 只接受 exact float `0.0`（`-0.0` 按数值相等可接受） | `_derive_cross_source_from_detail` 缺侧分支：`type(tolerance) is float and math.isfinite(tolerance) and tolerance != 0.0` → 必拒 | REPLAY_H1：真实缺 REFERENCE 五格 `tolerance=123.0` 并重绑 detail/summary hash → **必拒** |
| 其他 finite / NaN / Inf / null / 错误 dtype 必拒 | 同上 + dtype 门禁 | 实现者 `test_h1_*` 定向 23 passed 之一；NEW_V4：BOTH `tolerance=-0.0` **合法接受** |
| 正常缺行/停牌继续通过 | reconcile 生产路径未改坏 | NEW_V8：真实 missing REFERENCE bundle 与 suspend/空 OHLC 路径 **仍接受** |

### H2：缺失行现存侧必须领域合法

| 合同要求 | 代码证据 | 复验证据 |
|---|---|---|
| 现存侧 exact finite float；OHLC `> 0`；volume `>= 0` | `_validate_present_side_value`；PRIMARY 验 reference、REFERENCE 验 primary | REPLAY_H2：真实缺 REFERENCE 现存 primary 全改 `-1.0` 并重绑 hash → **必拒** |
| PRIMARY 价格 0/Inf 必拒；PRIMARY volume=0 合法 | 同上 | NEW_V1：缺 PRIMARY `reference open=0/Inf` **必拒**；NEW_V2：缺 PRIMARY `reference volume=0` **合法** |
| REFERENCE volume=-1 必拒；异常稳定 ValueError | 同上；dtype 非法统一 `ValueError("bundle detail dtype 非法")` | NEW_V3：真实缺 REFERENCE 的 `primary volume=-1` **必拒**；NEW_V7：present-side Categorical/List **仅稳定 ValueError**，无 polars/路径泄露 |
| BOTH 双侧 null | BOTH 分支要求两侧均 null | NEW_V4 合法 BOTH；实现者 BOTH 非法路径定向覆盖 |

### H3：30 receipts 的 `stable_response_sha256` 必须 30 唯一

| 合同要求 | 代码证据 | 复验证据 |
|---|---|---|
| `len(set(stable_digests)) == 30` | bundle `__post_init__` | REPLAY_H3：保留 30 唯一 `request_id`，合并两 receipt digest，summary 自洽压成 29 并重绑 → **必拒** |
| summary digest tuple 长度 30 且与 receipt digests 完全相等 | `len(reference_receipt_digests) == 30` 且 `== tuple(sorted(stable_digests))` | 实现者三类漂移（仅 receipt / 仅 summary / 同漂移）定向覆盖 |
| 同漂移后再排序仍拒；digest 重复但 request_id/endpoint 不同仍拒 | 唯一性按 digest 集合，不因排序或 endpoint 差异放行 | NEW_V5：同漂移后 reverse 再 sort **仍拒**；NEW_V6：digest 重复、request_id（及不同 endpoint）仍不同 **仍拒** |

## 4. 重放三个主验反例

临时脚本：`/mnt/c/Users/mbw/AppData/Local/Temp/p4b_main_reverify/run_reverify.py`（已删除）。

| ID | 操作 | 结果 |
|---|---|---|
| REPLAY_H1 | 真实 `missing_side="REFERENCE"` 五格 `tolerance`→`123.0`，重绑 detail/summary hash | **必拒** `ValueError` |
| REPLAY_H2 | 同真实缺 REFERENCE bundle，现存 primary 五值→`-1.0`，重绑 hash | **必拒** `ValueError` |
| REPLAY_H3 | 30 唯一 `request_id`；第二 receipt `stable_response_sha256` 并入第一；summary digests 自洽 29 + 重绑 summary hash | **必拒** `ValueError` |

与主验临时测试失败模式对照：原“构造成功”已翻转。

## 5. 新增对抗反例（实现者未使用；≥4）

相对实现者 `test_h1_*` / `test_h2_*` / `test_h3_*` 的差异点：缺 PRIMARY 的 Inf/合法 volume=0、真实缺行上的 volume=-1、BOTH `-0.0`、同漂移再排序、跨 endpoint 的 digest 重复、present-side List/Categorical、正常缺行/停牌回归。

| ID | 目标 | 反例 | 结果 |
|---|---|---|---|
| NEW_V1 | H2 缺 PRIMARY | `reference open=0.0` / `Inf` | 必拒 |
| NEW_V2 | H2 合法路径 | 缺 PRIMARY，`reference volume=0.0` | 合法接受 |
| NEW_V3 | H2 真实缺行 | 缺 REFERENCE 的 `primary volume=-1.0`（非伪造 missing 行） | 必拒 |
| NEW_V4 | H1 BOTH | `missing_side="BOTH"` 且 `tolerance=-0.0` | 合法接受 |
| NEW_V5 | H3 | receipt+summary 同压成 29 后，receipts/digests reverse 再 sort | 必拒 |
| NEW_V6 | H3 | digest 重复但 `request_id`（及不同 `endpoint`）仍唯一；summary 仍 30 | 必拒 |
| NEW_V7 | H2 dtype | present-side `primary_value`→Categorical / List[Float64]（List 绕过 identity hasher 直打 helper） | 仅稳定 `ValueError`（`bundle detail dtype 非法`） |
| NEW_V8 | 回归 | 正常缺 REFERENCE bundle；以及 suspend/空 OHLC 生产路径 | 仍接受 |

另：STATIC_no_os_replace_rename_socket、STATIC_shared_helper_defs、STATIC_bundle_public_fields、STATIC_zero_network_reconcile 均为 PASS。  
对抗汇总：**18/18 passed**。

## 6. 命令与真实结果

环境前缀：

```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base --no-capture-output
```

| 命令 | 结果 |
|---|---|
| 独立对抗 `run_reverify.py` | **18/18 passed**（含 H1–H3 重放与 NEW_V1–V8） |
| `pytest -q tests/unit/test_m3_reference.py -k "h1_ or h2_ or h3_ or adv5_ or adv9_ or f3_"` | **23 passed**, 91 deselected |
| `pytest -q tests/unit/test_m3_reference.py tests/unit/test_baostock_connector.py` | **133 passed** |
| `pytest -q tests/unit/test_m3_g1_candidate.py` | **33 passed** |
| `pytest -q`（全量） | **769 passed** |
| `python -m ruff check src tests` | **All checks passed** |
| `python -m mypy src` | **Success: no issues found in 78 source files** |

大量既有 Pandera/Polars deprecation warnings 不构成否决依据。

## 7. 限制与残余观察

- 未实现 / 未验收 P4C；不得开始下游包或以本报告勾选路线图。
- 任务单标明的非阻塞观察仍成立：`missing_primary` planner 可达性、raw symlink 错误码——本轮不扩大、不否决。
- `primary_receipt_digests` 相对原始 candidate receipts 的来源证明仍属 `reconcile_cross_source` + P4C 重执行范围；bundle 不夸大自包含。
- 整套另一真实自洽来源的 wholesale detail+summary 替换，仍需由重执行区分（原 §8.9）；本轮确认的是 H1–H3 身份闭包已关闭。

## 8. 复验声明

**独立复验结论：通过。**  
可交主 Agent 执行最终契约 / 真实依赖 / 回归与文档一致性验收。  
不得据此宣布 B4 / G1 / M3 / Gate 通过；不得跳过主验勾选路线图。
