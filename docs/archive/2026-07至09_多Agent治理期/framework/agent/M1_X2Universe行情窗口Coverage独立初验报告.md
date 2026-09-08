# M1-X2 Universe 行情窗口 Coverage 独立初验报告

日期：2026-07-18
角色：外部独立初验 Agent（全新会话，未参与实现）
任务单：[`M1_X2Universe行情窗口Coverage实现任务单.md`](M1_X2Universe行情窗口Coverage实现任务单.md)
交付报告：[`M1_X2Universe行情窗口Coverage实现交付报告.md`](M1_X2Universe行情窗口Coverage实现交付报告.md)
状态：**独立初验通过；不等于主验通过；不关闭 M1 Gate**

## 1. 结论

白名单实现与任务书成功标准一致：`BarWindowCoverage` / `AuditedBarWindow` /
`recent_for_universe_audited` 提供不可变 coverage；CLI 默认 report 显式 short/missing；
`--require-full-window` 在 incomplete 时以 `BAR_WINDOW_INCOMPLETE` 非零退出且不写 `--output`；
目标 source 重复键 fail closed；无 bar 文件仍保留非空 eligible 并全部记为 missing。

Windows / WSL 聚焦 pytest、Ruff、mypy 均 exit 0。WSL mypy 连续两次成功，交付报告中的首次
INTERNAL ERROR 判定为非稳定缺陷。未改生产代码/实现者测试；对抗脚本仅写系统临时目录。

**本报告不构成主验通过，亦不关闭 M1 Gate。**

## 2. 范围与只读约束

| 项 | 执行情况 |
|---|---|
| 生产代码 / 实现者测试 / 任务书 / 配置 / `data/**` / `artifacts/**` / `.git` | 只读 |
| 唯一写入 | 本报告 |
| 对抗脚本 | 仅 Windows Temp `m1x2_adv_*` 与 WSL `/tmp/m1x2_adv_*` |
| 真实查询 / 联网 | 未执行 |

核对白名单文件：`src/quant/data/query.py`、`src/quant/data/query_universe.py`、
`tests/unit/test_query.py`、`tests/unit/test_query_universe.py`、交付报告。

## 3. 成功标准 → 独立证据 → 结论

| # | 成功标准 | 独立证据 | 结论 |
|---|---|---|---|
| 1 | 不可变、严格校验 coverage（eligible/returned/missing/short/min/max/requested/as_of/source/universe） | 代码只读：`BarWindowCoverage` frozen+`__post_init__` 跨字段校验；`is_full_window`；实现者短窗测试 + 对抗 empty-bar | 通过 |
| 2 | audited 一次绑定 membership+bar；仅 as_of 成员、指定 source、trade_date<=as_of、每证券<=N、排序/coverage 确定 | 代码：`eligible_symbols_on`→JOIN→窗口 SQL；异源/未来行与顺序确定性测试 | 通过 |
| 3 | 保留 `recent_for_universe()`；CLI 改 audited 并输出 coverage | 兼容断言；CLI report 测试 | 通过 |
| 4 | `--require-full-window`：missing 或 count<N → 稳定脱敏错误、非零；默认 report 显式 short/missing | CLI 测试 + 对抗 strict/no-output 与 default report | 通过 |
| 5 | 重复键 / 异源入结果 / 未来行 / 非 eligible fail closed，禁止去重掩盖 | 裁剪前 `BAR_WINDOW_DUPLICATE_KEY`；异源/未来过滤不入 frame；对抗重复键 | 通过 |
| 6 | 无 bar 仍读 membership，全部 eligible=missing；membership 缺失 fail closed | 无 bar 测试 + 对抗；membership 缺失测试；CLI FileNotFoundError→`BAR_WINDOW_INPUT_INVALID` | 通过 |
| 7 | coverage 不写数据；仅成功且显式 `--output` 写 parquet；strict 失败无 output | CLI strict 测试（父目录亦不创建）+ 对抗 | 通过 |
| 8 | 两平台聚焦 pytest/Ruff/mypy；pathlib；JSON 用 as_posix() | 见第 4 节；成功 JSON output 无反斜杠 | 通过 |

## 4. 验证命令与结果（初验独立执行）

### Windows（`D:\Miniforge3\python.exe`，仓库 `F:\AI_Coding\QuantitativeTrading`）

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider` | **11 passed**；exit 0 |
| `python -m ruff check`（上述 4 文件） | All checks passed；exit 0 |
| `python -m mypy src/quant/data/query.py src/quant/data/query_universe.py` | Success；exit 0 |

### WSL（`/home/mabw/AI_Coding_win/QuantitativeTrading`，`conda run -n base`）

| 命令 | 结果 |
|---|---|
| 同上 pytest | **11 passed**；exit 0 |
| 同上 ruff | All checks passed；exit 0 |
| 同上 mypy（连续两次） | 两次均为 Success；exit 0 / exit 0 |

WSL mypy 稳定性：交付所述首次 INTERNAL ERROR **未复现**；连续两跑均绿 → 非本改动稳定类型缺陷。

## 5. 未公开对抗反例（实现者测试之外的独立脚本）

脚本路径（仓库外）：Windows temp `m1x2_adv_630988a7/adversarial_m1x2.py`；WSL 复制至 `/tmp/m1x2_adv_*`。
两平台均输出 `ALL_ADV_PASS`。

| 反例 | 预期 | 实际 |
|---|---|---|
| bar root 存在但无 parquet，eligible=3 | eligible=3、missing=3、returned=0、is_full_window=False，不得 eligible=0 | PASS |
| 目标 source (symbol,trade_date,source) 重复；另有 other source 行 | `BAR_WINDOW_DUPLICATE_KEY`，不得 silently 去重 | PASS |
| CLI `--require-full-window` + `--output` 且 short+missing | exit 1、stdout code=BAR_WINDOW_INCOMPLETE、无路径泄漏、output 文件与父目录均不存在 | PASS |
| 默认 report：满窗/短窗/缺失并存 | exit 0；JSON 显式 missing_symbols/short_symbol_counts/is_full_window=false；output=null | PASS |

## 6. 实现者自测反例复核（只读映射）

任务单第 5 节六项均有对应实现者测试覆盖；初验抽查代码路径与断言一致，未发现测试绿但语义漂。

## 7. 缺陷与返工项

无。不触发返工闭环。

## 8. 残留风险（不阻塞初验，但阻塞 Gate）

- 未验证真实港股通 60 日全市场覆盖；本包仅为查询/审计能力。
- Windows 绿测不等于 WSL/Linux Gate；本次两平台聚焦检查均绿，仍非主验/Gate。
- 旧 API `recent_for_universe()` 对重复键仍可能经 row_number 静默择一（任务要求保留旧语义）；正式证据路径必须走 audited/CLI。

## 9. 给主 Agent 的建议下一步

1. 主验：契约、跨模块不变量、文档一致性与（如需要）全量回归。
2. 不得将本初验表述为 M1 Gate 关闭或真实 60 日覆盖已取得。