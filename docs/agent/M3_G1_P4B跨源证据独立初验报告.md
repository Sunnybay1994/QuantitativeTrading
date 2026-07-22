# M3 G1-P4B 跨源证据独立初验报告

日期：2026-07-15  
角色：独立外部初验 Agent（未参与本轮实现；只读验收）  
实际模型标识：`cursor-grok-4.5-high`  
原任务书：[`M3_G1_P4B跨源证据外部闭环任务单.md`](M3_G1_P4B跨源证据外部闭环任务单.md)  
阻塞解除：[`M3_G1_P4B合同阻塞解除与重开任务单.md`](M3_G1_P4B合同阻塞解除与重开任务单.md)  
实现交付：[`M3_G1_P4B跨源证据阻塞解除后交付报告.md`](M3_G1_P4B跨源证据阻塞解除后交付报告.md)  
阻塞历史：[`M3_G1_P4B跨源证据交付报告.md`](M3_G1_P4B跨源证据交付报告.md)

## 结论：**不通过**

不可交主 Agent 终验。实现者自测定向套件绿色，但独立对抗反例证明
`CrossSourceReconciliationBundle` 构造器未履行任务书 §7.8「从 detail 重算
stats/issues」与 §7.9「跨源 issue 均为 ERROR」。按任务书「对抗通过后再跑全量」规则，
本轮未执行全量 pytest / Ruff / mypy。

不宣称 B4 / G1 / M3 / 任一 Gate 通过。

## 1. 初验边界与环境

- 只读：未修改生产代码、既有测试、配置、路线图或实现交付报告。
- 仅新增本报告；对抗脚本置于临时目录，报告完成后已删除。
- 环境：Windows 启动 → `wsl.exe` → `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` →
  `/home/mabw/miniforge3/bin/conda run -n base`。未使用 Windows Python/conda。
- 零真实网络、零 token、零 `_old/`、零实盘/外部状态修改。

## 2. 文件范围与公共导出

| 允许文件 | 实际状态 |
|---|---|
| `src/quant/data/m3_reference.py`（新增） | 存在（约 1857 行） |
| `src/quant/data/m3_g1_candidate.py`（仅 `_ISSUE_CODES` 两跨源码） | `CROSS_SOURCE_INCOMPLETE` / `CROSS_SOURCE_MISMATCH` 已加入；`audit_g1_candidate` 源码无 `CROSS_SOURCE` 字符串 |
| `src/quant/data/connectors/baostock.py`（`fetch_reference_bar_raw`） | 已新增 |
| `src/quant/data/__init__.py`（冻结导出） | 任务书 §4 全部类型与五函数均在 `__all__` |
| `tests/unit/test_m3_reference.py` | 存在（约 49 个 `test_*`） |
| `tests/unit/test_baostock_connector.py` | 追加 reference raw 相关用例 |
| 交付/初验报告 | 实现报告已有；本文件为初验报告 |

未发现对 `m3_backfill.py` / `storage.py` / Schema / 配置 / 路线图的越权修改迹象（本轮只读核对）。  
生产 `m3_reference.py` 静态无 `os.replace` / `os.rename`。

## 3. 合同→证据映射（摘要）

| 合同项 | 映射证据 | 初验判定 |
|---|---|---|
| §1 四件事（抽样/journal/verify/reconcile） | 五公共函数 + connector；定向 110 passed | 功能面大体具备 |
| §2 文件范围 / 枚举扩展 | 上表；解除任务单 §5 回归在实现者测试中 | 范围合规 |
| §3 executor 双输入闭包 | `execute_baostock_reference_plan(sample_plan, plan)`；ADV1 零副作用拒绝 | 通过 |
| §4 导出与九错误码 | 包根导出齐全；`M3ReferenceError` 四观察面脱敏（ADV8） | 通过 |
| §5 身份自证 / content hash | 值对象 `__post_init__`；ADV4 row-order 不变、value/dup/dtype 敏感 | 通过 |
| §6 connector + journal 状态机 | 定向 lifecycle/preflight；ADV2 第 30 冲突零增量；ADV7 raw symlink 拒绝 | 大体通过 |
| §7.5–7.7 reconciliation 语义 | 定向 missing/停牌/阈值/3000；ADV3 tradestatus 对照；ADV11 volume 零分母 | 大体通过 |
| §7.8 bundle 从 detail 重算 stats/issues | **ADV5：构造器接受 detail 有 mismatch 但 summary 宣称全匹配** | **不通过** |
| §7.9 issues 仅两码且均为 ERROR | **ADV9：`severity="WARNING"` 的跨源 issue 可进入 bundle** | **不通过** |
| §8 实现者必测矩阵 | 定向 `110 passed`（约 2m51s） | 自测覆盖充分，不能代替独立对抗 |
| 解除任务单 §5 | 跨源码可构造；未知码拒绝；audit 不产跨源码；阈值等于不产 MISMATCH | 通过 |

## 4. 独立新增对抗反例（≥6，实现者未使用）

临时脚本：`/tmp/p4b_adv/run_adversarial.py` + `reprobe.py`（已删除）。

| ID | 反例 | 结果 |
|---|---|---|
| ADV1 | 另一自洽 sample keys+request plan，executor 配**原** sample_plan → 零 journal/raw/网络拒绝 | PASS（`G1_REFERENCE_PLAN_INVALID`） |
| ADV2 | 按 request_id 排序的第 30 个目录放未知文件 → 前 29 个零 intent、零网络 | PASS |
| ADV3 | `tradestatus=0` 空行情 → INCOMPLETE；`tradestatus=1` 空 OHLC → 硬失败 | PASS |
| ADV4 | content hash：行序无关；改值/重复行/dtype 改变 digest | PASS |
| ADV5 | **同一 mismatch detail + 自洽“全匹配”summary/hash/issues=()/passed=True** | **FAIL（构造器接受）** |
| ADV6 | receipt/frame 跨绑到另一 request 的 frame → reconcile 拒绝；list 对调不改变 by-id 映射（预期） | PASS（闭包有效） |
| ADV7 | journal 祖先 symlink 拒绝；raw `data.parquet` 换 symlink → `G1_REFERENCE_JOURNAL_INVALID` | PASS（拒绝成立） |
| ADV8 | duplicate key / string number / Infinity / 非法 UTF-8；网络异常四观察面无路径/raw/client repr | PASS |
| ADV9 | **`CROSS_SOURCE_MISMATCH` + `severity="WARNING"` 且 passed/summary 对齐** | **FAIL（构造器接受）** |
| ADV10 | preflight 主异常期间 lock `unlink` 失败 → 仍抛主码 `JOURNAL_INVALID` | PASS |
| ADV11 | `volume` reference=`0` → tolerance=`volume_rtol * max(0,1)` | PASS |
| ADV12 | 生产模块静态无 replace/rename；无 `socket` import | PASS |

## 5. 不通过项（六段式）

### 5.1 Bundle 构造器未从 detail 重算 stats/issues

- **现象**：构造 `detail` 含 mismatch cells，同时构造 `summary` 宣称
  `mismatch_cells=0` / `field_stats` 全 0 / `passed=True` / `issues=()`，且
  `summary.detail_sha256` 与 `detail_sha256` 均等于该 mismatch detail 的真实
  `clean_table_content_sha256`，`summary_sha256` 按撒谎 summary 的 `asdict` 重算。
  `CrossSourceReconciliationBundle(...)` **接受**该对象。
- **根因**：`CrossSourceReconciliationBundle.__post_init__` 只校验
  detail↔detail_sha256、summary 字段自洽、summary.detail_sha256 字符串相等、
  issues 码集合与 passed 布尔关系；**未**从 detail 行重算 field_stats /
  mismatch_cells / issues / passed。
- **应遵循规则**：任务书 §7.8「bundle 构造器从 detail 重算 digest/stats/summary
  digest/issues/passed」；主设计 §5.6 summary 必须与 detail 闭合。  
  §8.9「整套 summary 自洽替换须由 `reconcile_cross_source` 重跑发现」仅豁免
  *另一套完整自洽（detail+summary 一起替换）* 的来源闭包，不豁免
  *同一 detail 上撒谎 summary*。
- **最小复现**：见临时对抗 ADV5 / `reprobe.py` 输出
  `ADV5: ACCEPTED lying summary (BUG)`（WSL Miniforge `base`，零网络）。
- **新增测试**：在 `tests/unit/test_m3_reference.py` 增加：取
  `mismatch_cells>0` 的真实 reconcile bundle，伪造零 mismatch 的 summary（保持
  detail 与 detail hash 不变），断言构造器 `ValueError`。
- **通过条件**：上述撒谎 bundle 必拒；构造器从 detail 重算的 stats/issues/passed
  与 `reconcile_cross_source` 一致；原有 wholesale 双 bundle 重跑比较测试仍成立。

### 5.2 跨源 issue 允许 `WARNING` severity

- **现象**：`G1QualityIssue(code="CROSS_SOURCE_MISMATCH", severity="WARNING", ...)`
  在 `passed=False` 且 `summary.passed=False`、hash 对齐时可进入
  `CrossSourceReconciliationBundle.issues`。
- **根因**：bundle 构造器只检查 issue code ∈
  `{CROSS_SOURCE_INCOMPLETE, CROSS_SOURCE_MISMATCH}`，不强制 `severity=="ERROR"`。
- **应遵循规则**：任务书 §7.9「issues 只允许两码，**均为 ERROR**」。
- **最小复现**：`reprobe.py` 输出
  `ADV9_WARN: ACCEPTED (BUG - severity WARNING allowed)`。
- **新增测试**：对两个跨源码分别以 `WARNING` 构造 bundle，断言拒绝；`ERROR` 仍可进入。
- **通过条件**：任意 `severity!="ERROR"` 的跨源 issue 无法构造进 bundle；
  `reconcile_cross_source` 产出保持 ERROR。

## 6. 命令与真实结果

环境前缀（所有命令）：

```bash
cd /mnt/g/BaiduSyncdisk/wsl/Cursor/quant
PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base --no-capture-output
```

| 命令 | 结果 |
|---|---|
| 独立对抗 `/tmp/p4b_adv/run_adversarial.py` | 12 项中 ADV5/ADV9 类缺陷确认；其余 PASS |
| 复验 `/tmp/p4b_adv/reprobe.py` | `ADV5: ACCEPTED lying summary (BUG)`；`ADV9_WARN: ACCEPTED`；raw symlink 拒绝 `G1_REFERENCE_JOURNAL_INVALID` |
| 定向 `pytest -q tests/unit/test_m3_reference.py tests/unit/test_baostock_connector.py` | **110 passed**，约 171s；大量既有 Pandera/Polars deprecation warnings（不据此误判） |
| 全量 pytest / Ruff / mypy | **未跑**（对抗未通过，按任务书停止） |

## 7. 限制与残余观察

- 未实现/未验收 P4C；不得开始下游包。
- `missing_primary` 计数路径在「sample_plan 必须等于 `plan_cross_source_reconciliation(candidate)`」
  闭包下实际上不可达（planner 只从 bars 取样）。这不是本轮否决主因，但建议主 Agent
  确认 §7.5「缺 primary 五格」是保留防御还是应调整表述。
- raw symlink 在 `verify_reference_receipt` 路径抛 `G1_REFERENCE_JOURNAL_INVALID`
  而非 `G1_REFERENCE_RECEIPT_INVALID`；失败闭合成立，码选择可在返工时一并收紧。

## 8. 初验声明

**独立初验结论：不通过。**  
请主 Agent 按 §5 六段式形成返工任务，交回外部实现 Agent；返工后再由**未参与该轮实现**的
全新外部会话复验。在 ADV5/ADV9 修复并经独立复验通过前，不得进入主 Agent 终验，
不得勾选路线图或宣称 B4/G1/M3/Gate 通过。
