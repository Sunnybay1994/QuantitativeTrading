# M1-X2-R2 Audited Result 严格绑定独立复验报告

日期：2026-07-18  
角色：外部独立复验 Agent（全新会话，未参与任何 X2 实现、未参与 R2 返工实现）  
返工任务单：[`M1_X2_R2_AuditedResult严格绑定返工任务单.md`](M1_X2_R2_AuditedResult严格绑定返工任务单.md)  
返工交付报告：[`M1_X2_R2_AuditedResult严格绑定返工交付报告.md`](M1_X2_R2_AuditedResult严格绑定返工交付报告.md)  
前置：[`M1_X2_R1_Coverage严格跨字段校验与CLI文档独立复验报告.md`](M1_X2_R1_Coverage严格跨字段校验与CLI文档独立复验报告.md)  
状态：**独立复验通过；不等于主验通过；不关闭 M1 或任何 Gate**

## 1. 结论

按 R2 返工合同逐项核对：

- **R2-A**：`BarWindowCoverage` 对 `missing_symbols` / `short_symbol_counts` 经
  `_require_canonical_symbol` 使用领域 SSOT `quant.domain.schemas.SYMBOL_PATTERN`
 （`re.compile` + `fullmatch`），未复制第二套正则；空串、非 canonical、错误市场后缀稳定抛
  `BAR_WINDOW_INPUT_INVALID`；合法 A/H canonical 可构造。
- **R2-B**：`AuditedBarWindow.__post_init__` 在构造期绑定 frame/coverage；任务单最小复现
  （full coverage + empty frame）稳定拒收；非空 frame 校验列存在、dtype 精确相等、无 null、
  source/as_of、唯一键、canonical symbol、确定排序、returned/missing 不相交、逐证券 counts 与
  short/min/max 闭包；值对象内无静默 cast/排序/去重/丢行；错误仅暴露稳定码。

Windows / WSL 聚焦 pytest（38 passed）、Ruff、mypy 均 exit 0。复验独立对抗探针（含实现者未使用
用例）两平台均 FAILS=0。未改生产代码、实现者测试、配置、`data/**`、`artifacts/**`、`.git`；
唯一写入为本报告；对抗脚本仅写系统临时目录。

**本报告不构成主验通过，亦不关闭 M1 或任何 Gate。**

## 2. 范围与只读约束

| 项 | 执行情况 |
|---|---|
| 生产代码 / 实现者测试 / 配置 / `data/**` / `artifacts/**` / `.git` | 只读 |
| 唯一写入 | 本报告 |
| 对抗脚本 | Windows 内联 `python -c`；WSL 经 `%TEMP%` 复制到 `/tmp` 后执行并删除 |
| 真实查询 / 联网 / 安装依赖 | 未执行 |

核对白名单：`src/quant/data/query.py`、`tests/unit/test_query.py`、返工交付报告。未触碰
`query_universe.py`、Schema、README。

## 3. R2-A / R2-B 合同 → 独立证据 → 结论

### 3.1 R2-A — coverage canonical symbol

| # | 合同项 | 独立证据 | 结论 |
|---|---|---|---|
| A1 | 使用 `SYMBOL_PATTERN` SSOT，不复制正则 | `from quant.domain.schemas import SYMBOL_PATTERN`；`_SYMBOL_RE = re.compile(SYMBOL_PATTERN)`；对抗 `ssot_pattern_identity`：`_SYMBOL_RE.pattern == SYMBOL_PATTERN` | 通过 |
| A2 | missing/short 空串、非 canonical、错误后缀拒收 | 代码 L97–100 `_require_canonical_symbol`；实现者 8 参数化用例；对抗 5×2 非法 symbol | 通过 |
| A3 | 合法 A/H canonical 通过 | 实现者 `test_bar_window_coverage_accepts_canonical_a_and_h_symbols`；对抗 `R2A_legal_AH` / `legal_AH` | 通过 |
| A4 | 不修改 Schema SSOT | 只读：`schemas.py` 中 `SYMBOL_PATTERN` 未被本包改写；query 仅 import | 通过 |

### 3.2 R2-B — AuditedBarWindow frame/coverage 绑定

| # | 冻结绑定合同 | 独立证据 | 结论 |
|---|---|---|---|
| B1 | frame 为 `pl.DataFrame`，coverage 精确 `BarWindowCoverage` | `isinstance(frame)` + `type(coverage) is BarWindowCoverage` | 通过 |
| B2 | 空 frame ⇒ returned=0 且 max=0（真空池 / all-missing） | 代码 L188–194；合法 empty/all-missing 对抗通过；full+empty 拒收 | 通过 |
| B3 | 非空须含 symbol/trade_date/source；无 null；dtype String/Date/String；不 cast | 代码 L195–209；实现者缺列/Datetime 用例；对抗 `null_symbol` 拒收 | 通过 |
| B4 | 每行 source==coverage.source；trade_date≤as_of；唯一键；symbol canonical | 代码 L210–222；实现者未来/异源/重复 key；对抗同路径 + `frame_noncanon` | 通过 |
| B5 | 已按 `(symbol, trade_date)` 确定排序；乱序拒收，不静默排序 | `order_keys != sorted(order_keys)` 仅比较；对抗日期乱序 + **跨证券乱序** | 通过 |
| B6 | unique symbol 数 = returned；与 missing 不相交；每证券行数 ∈[1, requested] | 代码 L233–240；对抗 `intersect_missing`、`rows_gt_req`、`forged_returned` | 通过 |
| B7 | 从 frame 重算 short/min/max，逐字段等于 coverage；声明 full 须恰有 requested 行 | 代码 L241–259；short identity mismatch 拒收 | 通过 |
| B8 | 不凭空验证 full symbol 身份；不扩 Schema / 不发明名单 | 无 eligible 列表字段；仅 counts/canonical/payload 闭合 | 通过 |
| B9 | 错误统一 `BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")`，不泄漏 frame/路径/SQL | `str(e)==code`；对抗检查 repr/str 无 DataFrame/SQL/路径片段 | 通过 |

## 4. 验证命令与结果（复验独立执行）

### Windows（`D:\Miniforge3\python.exe`，`F:\AI_Coding\QuantitativeTrading`）

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider` | **38 passed**；exit 0 |
| `python -m ruff check src/quant/data/query.py tests/unit/test_query.py` | All checks passed；exit 0 |
| `python -m mypy src/quant/data/query.py` | Success；exit 0 |
| 独立对抗探针（内联 `python -c`） | **30 PASS / 0 FAIL**；exit 0 |

### WSL（`/home/mabw/AI_Coding_win/QuantitativeTrading`，`conda run -n base`）

| 命令 | 结果 |
|---|---|
| 同上 pytest | **38 passed**；exit 0 |
| 同上 ruff | All checks passed；exit 0 |
| 同上 mypy | Success；exit 0 |
| 独立对抗探针（`/tmp/m1_x2_r2_adv_probe.py`） | **FAILS 0**（全部 PASS）；Python 进程成功完成 |

压缩摘要：两平台契约测试 38 绿；静态检查绿；对抗探针与交付报告声称范围一致且额外反例均拒收/接受符合合同。

## 5. 未公开对抗反例

实现者交付第 5 节已覆盖：coverage 非 canonical；full+empty；缺列/错误 dtype；日期乱序；重复 key；
未来/异源；short count 相同但 symbol 不同；min/max 正确但 returned 伪造；合法 empty/all-missing/
full-window 绑定。

复验**额外**执行实现者测试未单独覆盖的对抗（两平台一致）：

### 5.1 任务单列明项（独立复现，非依赖实现者自测）

| 反例 | 构造摘要 | 预期 | Win | WSL |
|---|---|---|---|---|
| short count 相同、symbol 不同 | coverage short=`00001.HK`×1；frame=`00700.HK`×1 | 拒收 | PASS | PASS |
| full+short min/max 正确、returned 伪造 | coverage returned=3；frame 仅 2 个 unique symbol | 拒收 | PASS | PASS |
| 未来行 | trade_date = as_of+1 | 拒收 | PASS | PASS |
| 异源行 | source=`other` | 拒收 | PASS | PASS |
| 重复 key | 同 (symbol,trade_date,source) 两行 | 拒收 | PASS | PASS |
| 乱序行（日期） | 同 symbol 日期倒序 | 拒收 | PASS | PASS |
| 非法 coverage symbol | `""` / `not-a-symbol` / `.US` / `.XX` / `700.HK`（missing 与 short） | 拒收 | PASS | PASS |
| 合法 empty / all-missing / short-only / full+short / full-window | 见下表 | 接受 | PASS | PASS |

### 5.2 实现者未使用的新增对抗

| 反例 | 构造摘要 | 预期 | Win | WSL |
|---|---|---|---|---|
| 跨证券字典序乱序 | frame 先 `00700.HK` 后 `00001.HK`（counts 与 full coverage 数值可对齐） | 拒收 | PASS | PASS |
| frame 非 canonical symbol | frame symbol=`not-a-symbol`（coverage 为合法 full） | 拒收 | PASS | PASS |
| frame ∩ missing | coverage missing 含 `00700.HK`，frame 仍返回该 symbol 满窗 | 拒收 | PASS | PASS |
| key 列 null | symbol 列含 null | 拒收 | PASS | PASS |
| 每证券行数 > requested | frame 3 行 / requested=2，coverage 声称 full | 拒收 | PASS | PASS |
| 合法 short-only 绑定 | returned=1, short=(`00700.HK`,1), frame 1 行 | 接受 | PASS | PASS |
| 合法 full+short 绑定 | short=`00001.HK`×1 + full=`00700.HK`×2 | 接受 | PASS | PASS |
| 无静默突变 | 合法 frame 构造前后 `to_dicts()` 相等 | 保持 | PASS | — |

### 5.3 合法结果矩阵

| 场景 | 关键断言 | Win | WSL |
|---|---|---|---|
| empty（eligible=0） | 空 frame 可绑定 | PASS | PASS |
| all-missing | returned=0, max=0, 空 frame | PASS | PASS |
| short-only | `is_full_window=False`；可绑定 | PASS | PASS |
| full+short | min/max/short 与 frame 闭合 | PASS | PASS |
| full-window | `is_full_window=True`；可绑定 | PASS | PASS |

## 6. 实现者自测反例复核（只读映射）

| 交付声称 | `tests/unit/test_query.py` | 复核 |
|---|---|---|
| R2-A 非 canonical | `test_bar_window_coverage_rejects_non_canonical_symbols`（8 例） | 一致 |
| R2-A 合法 A/H | `test_bar_window_coverage_accepts_canonical_a_and_h_symbols` | 一致 |
| full+empty | `test_audited_bar_window_rejects_full_coverage_with_empty_frame` | 一致 |
| 缺列 / 错误 dtype / 乱序 / 重复 / 未来异源 | 对应 `rejects_*` 用例 | 一致 |
| short identity mismatch | `test_audited_bar_window_rejects_short_symbol_identity_mismatch` | 一致 |
| forged returned | `test_audited_bar_window_rejects_forged_returned_count` | 一致 |
| 合法 full / empty / all-missing | `accepts_consistent_full_window_frame` / `accepts_empty_and_all_missing_bindings` | 一致；**未**单测 short-only / full+short 手工绑定（由复验对抗补齐） |

未发现测试绿但合同语义漂；`AuditedBarWindow.__post_init__` 内无对 frame 的 `cast`/原地排序/去重/丢行。
查询路径中的 `cast(pl.DataFrame, pl.from_arrow(...))` 属 DuckDB 结果类型标注，不在值对象静默修复范围内。

## 7. 缺陷与返工项

无。不触发新一轮「现象—根因—规则—最小复现—新增测试—通过条件」返工闭环。

## 8. 残留风险（不阻塞独立复验，但阻塞主验 / Gate 表述）

- 本包不构成真实港股通 60 日全市场覆盖证据。
- Windows 绿测不等于 WSL/Linux Gate；本次两平台聚焦检查均绿，仍非主验/Gate。
- coverage 不保存完整 eligible 列表：无法验证「未出现在 frame/missing/short 中的 full symbol」具体身份（任务单 B8 已冻结接受）。
- 空 frame 早退依赖 `BarWindowCoverage` 已保证 returned=0⇒min=0/short 空；通过 `type(coverage) is BarWindowCoverage` 防子类绕过，但不防极端 `object.__new__` 手工拼装（超出本包威胁模型）。

## 9. 下一步

交主 Agent 终验（契约、真实依赖边界、回归与文档一致性）。本独立复验**不得**被表述为 M1 或任何 Gate 已关闭。
