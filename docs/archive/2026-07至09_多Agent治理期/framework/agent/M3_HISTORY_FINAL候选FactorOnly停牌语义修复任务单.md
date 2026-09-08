# M3 HISTORY FINAL 候选 Factor-Only 停牌语义修复任务单

## 已证明现象与根因

- HISTORY 生产闭包已由 `_verify_tushare_complete` 验证为 `3186/3186`：
  `adj_factor=637`、`daily=637`、`dividend=637`、`index_daily=1`、`stk_limit=637`、`suspend_d=637`。
- workflow 后续失败为 `G1_CANDIDATE_COMPONENT_INVALID`。
- 绕过顶层异常折叠后的 traceback 精确指向：
  `_build_candidate_body:1421 -> apply_adjustment_factors_strict:695`。
- 全量业务键：daily `1,489,629`、adj_factor `1,517,796`、daily-only `0`、factor-only `28,167`；其中 `24,739` 与 suspend_d 精确重合。
- 最小真实反例：`000002.SZ/2015-12-21` 为开市停牌日，daily 无行、adj_factor=`127.447`、suspend_type=`S`。
- 根因：实现错误要求 `bar_keys == factor_keys`，与“停牌日可有 factor 而无 daily bar”的冻结语义冲突。

## 冻结修复

- 仅把全等约束改为 `bar_keys` 必须是 `factor_keys` 的子集。
- 每个 emitted bar 仍必须精确匹配同 `(symbol, trade_date, source)` factor。
- 保留全部 factor observations；factor-only 不生成 bar 或 factor-match evidence，继续供公司行动因子跃迁核对。
- 不允许 as-of/forward-fill、最近值、默认 `adj_factor=1.0`、缺失/重复/非正 factor、错误 lineage 或越 request 范围日期。
- 不修改 mapper、Schema、request plan、journal/receipt、配置、identity 版本或稳定错误码。

## 回归与通过条件

1. 函数级：daily 只有 D1，factor 有 D0+D1；输出 bar/match 仅 D1，factor-only D0 不报错也不生成虚构输出。
2. build 级：一个成员 D0 为 FULL_DAY suspension，daily 仅 D1，factor D0+D1；`build -> verify -> audit.passed`，candidate 保留两条 factor、仅一条 bar/match 和 D0 suspension。
3. 原 missing/duplicate/nonpositive/lineage 测试继续通过。
4. 定向 Ruff/mypy/pytest 在 Windows 与 WSL base 通过。
5. 零网络真实 candidate 重验不再在 factor key 集合处失败；若暴露公司行动供应商语义，另立任务，不在本修复中猜测或放宽。

