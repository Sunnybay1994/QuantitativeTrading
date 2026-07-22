# M3 HISTORY FINAL 候选 Factor-Only 停牌语义修复主 Agent 验证报告

## 结论

- 状态：**代码与定向回归通过；真实候选已越过原失败点**。
- 生产改动仅一处：`apply_adjustment_factors_strict` 从 `bar_keys == factor_keys` 改为 `bar_keys ⊆ factor_keys`。
- 全部 factor observations 继续保留；factor-only 不生成虚构 bar 或 match evidence。

## 根因证据

- 原 traceback：`_build_candidate_body:1421 -> apply_adjustment_factors_strict:695`，稳定码 `G1_CANDIDATE_COMPONENT_INVALID`。
- 全量真实键：daily `1,489,629`、factor `1,517,796`、daily-only `0`、factor-only `28,167`，涉及 `405` symbols；其中 `24,739` 与 suspend_d 精确重合。
- 最小真实反例 `000002.SZ/2015-12-21`：开市停牌、daily 无行、factor=`127.447`、suspend_type=`S`。

## 验证

- Windows：`tests/unit/test_m3_g1_candidate.py`，`37 passed`。
- WSL Miniforge base：同一测试文件，`37 passed`。
- Windows/WSL Ruff：改动代码与测试均通过。
- Windows/WSL mypy：`src/quant/data/m3_g1_candidate.py` 均通过。
- 新增函数级反例：factor-only D0 不生成 bar/match，D1 exact factor 正常应用。
- 新增完整 build 反例：D0 FULL_DAY suspension + daily 仅 D1 + factor D0/D1，`build -> verify -> audit.passed`。
- 真实全量 candidate 重验不再在 factor key 集合失败，推进至 benchmark mapper。

## 未放宽门禁

- 缺失、重复、非正 factor、错误 lineage、越 request 范围日期仍失败。
- 不做 forward-fill、as-of、最近值或默认 factor。
- 未修改 mapper、Schema、plan、journal/receipt、配置或 identity 版本。

## 后续独立风险

- benchmark close-only 语义是当前首要阻断。
- 真实 dividend 还存在 null/缺 ex_date 等供应商语义反例；benchmark 解决后另立任务，不能将 null 猜成零。

