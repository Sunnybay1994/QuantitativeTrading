# M1-X2-R1 Coverage 严格跨字段校验与 CLI 文档独立复验报告

日期：2026-07-18  
角色：外部独立复验 Agent（全新会话，未参与 X2 实现、未参与 R1 返工实现）  
返工任务单：[`M1_X2_R1_Coverage严格跨字段校验与CLI文档返工任务单.md`](M1_X2_R1_Coverage严格跨字段校验与CLI文档返工任务单.md)  
返工交付报告：[`M1_X2_R1_Coverage严格跨字段校验与CLI文档返工交付报告.md`](M1_X2_R1_Coverage严格跨字段校验与CLI文档返工交付报告.md)  
前置：[`M1_X2Universe行情窗口Coverage实现任务单.md`](M1_X2Universe行情窗口Coverage实现任务单.md)、[`M1_X2Universe行情窗口Coverage实现交付报告.md`](M1_X2Universe行情窗口Coverage实现交付报告.md)、[`M1_X2Universe行情窗口Coverage独立初验报告.md`](M1_X2Universe行情窗口Coverage独立初验报告.md)  
状态：**独立复验通过；不等于主验通过；不关闭 M1 或任何 Gate**

## 1. 结论

按 R1 返工合同，`BarWindowCoverage.__post_init__` 已封闭 `min/max ≤ requested` 及
`full_count` / `expected_min` / `expected_max` 跨字段关系；任务单最小复现构造稳定抛
`BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")`，无法再冒充 `is_full_window=True`。
实现者参数化非法构造与合法 full+short 用例存在且与代码一致；`README.md` `query_universe`
小节已写明默认 report 显式 coverage，以及 `--require-full-window` 的
`BAR_WINDOW_INCOMPLETE` / 不写 `--output` 语义，且未声称真实 60 日覆盖完成。

Windows / WSL 聚焦 pytest、Ruff、mypy 均 exit 0（WSL mypy 连续两跑成功）。复验新增实现者
未使用的非法组合（不同具体数值）与合法 empty / all-missing / short-only / full+short /
full-window 值对象核验，两平台均 `ALL_ADV_PASS`。未改生产代码、实现者测试、README、配置、
`data/**`、`artifacts/**`、`.git`；唯一写入为本报告；对抗脚本仅写系统临时目录。

**本报告不构成主验通过，亦不关闭 M1 或任何 Gate。**

## 2. 范围与只读约束

| 项 | 执行情况 |
|---|---|
| 生产代码 / 实现者测试 / README / 配置 / `data/**` / `artifacts/**` / `.git` | 只读 |
| 唯一写入 | 本报告 |
| 对抗脚本 | Windows Temp `m1x2r1_adv_d13221d8`；WSL `/tmp/m1x2r1_adv_d13dee04` |
| 真实查询 / 联网 / 安装依赖 | 未执行 |

核对白名单：`src/quant/data/query.py`、`tests/unit/test_query.py`、`README.md`（仅
`query_universe` 小节）、返工交付报告。未发现 R1 白名单外生产改动进入本次复验范围。

## 3. 返工合同 → 独立证据 → 结论

| # | 返工合同项 | 独立证据 | 结论 |
|---|---|---|---|
| 1 | `min ≤ max ≤ requested`；矛盾手工构造拒收 | 代码 `max > requested` 与 `expected_min/max` 强制相等；任务单最小复现 + 对抗 `TASK_*` / `ADV_no_ms_*` 均 `BAR_WINDOW_INPUT_INVALID` | 通过 |
| 2 | eligible=0 全零合同 | 对抗 `OK_empty`：全零可构造；`is_full_window=True`（空池真空真） | 通过 |
| 3 | returned=0：min=max=0、全部 missing、short 空 | 代码 `returned==0` 分支；对抗 `ADV_ret0_*` 拒收不完整 missing；`OK_all_missing` 合法接受 | 通过 |
| 4 | returned>0：max>0；missing⇒min=0；无 missing⇒min>0 | 代码显式分支；实现者 `missing_nonzero_min` 参数化用例存在 | 通过 |
| 5 | short ∈[1,requested-1]、`len(short)≤returned`、与 missing 不重叠 | 代码循环与交集/长度校验；实现者 `short_len_gt_returned` | 通过 |
| 6 | `full_count` / `expected_min` / `expected_max` 公式 | 代码 L136–154；无 missing/short 时 min=max=requested；full+short 时 max 必须为 requested | 通过 |
| 7 | 不改 `recent_for_universe()`；strict 不移入 audited 库查询 | 只读：库查询仍返回 coverage；strict 仍在 `query_universe.py` CLI | 通过 |
| 8 | 参数化非法手工构造 + 保留查询合法反例 | `test_bar_window_coverage_rejects_inconsistent_manual_construction` 7 例；既有短窗/全缺等查询用例仍在 | 通过 |
| 9 | README 默认 report + `--require-full-window` fail-closed/no-output；不复制字段 SSOT；不声称真实 60 日完成 | README L261–275：显式 coverage；strict 非零且不写 output；明确“不表示真实港股通 60 日全市场覆盖已经取得” | 通过 |

## 4. 验证命令与结果（复验独立执行）

### Windows（`D:\Miniforge3\python.exe`，仓库 `F:\AI_Coding\QuantitativeTrading`）

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider` | **19 passed**；exit 0 |
| `python -m ruff check src/quant/data/query.py tests/unit/test_query.py` | All checks passed；exit 0 |
| `python -m mypy src/quant/data/query.py` | Success；exit 0 |

### WSL（`/home/mabw/AI_Coding_win/QuantitativeTrading`，`conda run -n base`）

| 命令 | 结果 |
|---|---|
| 同上 pytest | **19 passed**；exit 0 |
| 同上 ruff | All checks passed；exit 0 |
| 同上 mypy（连续两次） | Success；exit 0 / exit 0 |

WSL mypy：R1 交付所述偶发 INTERNAL ERROR **未复现**；连续两跑均绿。

## 5. 未公开对抗反例（实现者未使用的具体数值）

实现者已测：`req=60,min=max=59`；`eligible=3,missing=2,returned=0`；`short=59,max=59`。
复验改用不同具体组合，脚本仅写系统临时目录；两平台均输出 `ALL_ADV_PASS`（exit 0）。

### 5.1 非法组合（均期望 `BAR_WINDOW_INPUT_INVALID`）

| 反例 | 具体构造（摘要） | 预期 | Win | WSL |
|---|---|---|---|---|
| 无 missing/short 但 min/max < requested | req=10, returned=2, min=max=1 | 拒收 | PASS | PASS |
| 同上（非对称 min≠max 均 < requested） | req=10, min=3, max=7 | 拒收 | PASS | PASS |
| returned=0 但 missing 未覆盖全部 eligible | eligible=5, returned=0, missing=1 | 拒收 | PASS | PASS |
| returned=0 且 missing 为空 | eligible=4, returned=0, missing=() | 拒收 | PASS | PASS |
| full+short 并存但 max 等于 short count | req=10, short=3, max=3（应有 full⇒max=10） | 拒收 | PASS | PASS |
| 两 short + 一 full，max 错等于 max(short) | shorts=(2,5), max=5 | 拒收 | PASS | PASS |
| 任务单最小复现 | req=2, min=max=3, 无 missing/short | 拒收 | PASS | PASS |

### 5.2 合法值对象

| 场景 | 关键断言 | Win | WSL |
|---|---|---|---|
| empty（eligible=0 全零） | 可构造；`is_full_window=True` | PASS | PASS |
| all-missing | returned=0, missing=3；`is_full_window=False` | PASS | PASS |
| short-only | min=10,max=59；`is_full_window=False` | PASS | PASS |
| full+short | min=59,max=60；`is_full_window=False` | PASS | PASS |
| full-window | min=max=60；`is_full_window=True` | PASS | PASS |

### 5.3 README strict / no-output 文案

只读核对：默认 report 须显式报告 coverage；正式完整窗口证据须 `--require-full-window`；
失败码 `BAR_WINDOW_INCOMPLETE`、非零退出、即使指定 `--output` 也不写文件；并声明本命令不表示
真实 60 日覆盖已取得。与返工合同第 2.4 / 第 9 项一致。

## 6. 实现者自测反例复核（只读映射）

R1 交付第 5 节七项非法参数化 + 合法 full+short 手工构造，与 `tests/unit/test_query.py`
`test_bar_window_coverage_rejects_inconsistent_manual_construction` /
`test_bar_window_coverage_accepts_consistent_full_and_short_mix` 一致；未发现测试绿但语义漂。

## 7. 缺陷与返工项

无。不触发新一轮返工闭环。

## 8. 残留风险（不阻塞复验，但阻塞 Gate / 主验表述）

- 未验证真实港股通 60 日全市场覆盖；本包仅为值对象合同与 CLI 文档同步。
- Windows 绿测不等于 WSL/Linux Gate；本次两平台聚焦检查均绿，仍非主验/Gate。
- 空池 `is_full_window=True` 为真空真；若未来 CLI 对空 eligible 走 `--require-full-window`，
  语义需主验确认是否符合产品意图（非本 R1 合同缺陷）。
- 旧 API `recent_for_universe()` 重复键静默择一语义仍保留；正式证据路径须走 audited/CLI。

## 9. 给主 Agent 的建议下一步

1. 主验：契约、跨模块不变量、文档一致性与必要回归。
2. 不得将本复验表述为主验通过、M1 Gate 关闭或真实 60 日覆盖已取得。
