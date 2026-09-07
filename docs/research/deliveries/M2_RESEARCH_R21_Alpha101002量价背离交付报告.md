# M2 Research R21 Alpha101 #002 量价背离交付报告

## 交付状态

`IMPLEMENTATION_STATIC_DELIVERY / VALIDATION_UNRUN / ECONOMIC_IO0 / TRIAL0`

本报告由唯一授权 R21 实现者写入。实现严格消费已合流的
`quant.factors.cross_sectional_rank.rank_cross_sectional_components`：将
`volume_change` 与 `intraday_return` 作为同一 long-form 输入的一次调用，保留两组件独立成员集合，随后按
六个连续 session pair 计算 Pearson 相关并取负号。

## exact4 变更

- `src/quant/factors/classic_eleventh_batch.py`：新增 Alpha101 #002 的 Bar1dSchema、严格交易日 lag-2、
  exact8 语义、独立组件 rank 消费、exact6 Pearson 与输出契约。
- `tests/unit/test_classic_eleventh_batch.py`：新增公共 helper exact-one spy、真实 helper 等价、成员集合/null、
  exact8、内部缺 bar、输入失败闭合与配置合同测试。
- `configs/research/m2_classic_daily_factors_eleventh_batch.toml`：新增冻结研究身份、公式口径、方向、试验
  预算与 `economic_execution = BLOCKED_PENDING_PUBLIC_RECEIPT_AND_RUN_TASKBOOK` 的静态候选。
- 本报告。

未修改任务书、公共 rank helper、`__init__`、runner、schema、repository、receipt、roadmap 或其他路径。

## 验证边界

按任务合同的 `STATIC_ONLY / CPU NONE / PYTHON0 / DATA0 / NETWORK0 / ECONOMIC_IO0 / TRIAL0`，本交付未运行
Python、pytest、Ruff、mypy、真实数据、网络、经济计算或 trial。故不能宣称测试、Linux Gate、经济结果或任何
收益结论通过；定向 Windows 验证由独立 reviewer/中央后续安排。

## 交付身份

最终 exact4 的实际 bytes/SHA256 与 `git diff --check` 证据由中央在交付收尾时读取并绑定；本报告不写入自指
身份，避免报告内容改变自身 SHA。

## STATIC_REWORK 补充

中央复核指出的三项 P1 已在同一实现链修正：

1. `_intraday_return` 现在对完整 `((close-open)/open)` 表达式先 cast 再 alias；
2. 测试使用显式手算的六期非退化 rank 序列，锁定 exact6 Pearson、负号与第八个 session 首值；并独立锁定
   两组件全相同 raw input 的 zero-variance null；
3. 测试矩阵已逐节点覆盖：两组件不等 null 成员集、零成交量局部 null、内部 gap 不跨洞、ascending average
   ties、n=1/n=2、输入与并列行置换、七期/exact8、schema/duplicate/nonfinite/calendar、helper failure
   无 fallback、exact 输出列/key/dtype，以及配置完整身份和阻断字段。

本补充仍保持 `VALIDATION_UNRUN`：未运行 Python、pytest、Ruff、mypy、真实数据、网络、经济计算或 trial；上述
均为可复核测试源码与静态交付范围，不是已通过的运行 Gate 或经济结论。

## 复验后修订

复验指出内部 gap 测试必须尊重“只返回原始 bars keys”合同：9 个 session 中缺一 bar 时，目标 symbol 输出为
8 行且 8 行全为 null；测试已改为显式断言 `len == 8` 与 `null_count == 8`，没有用宽松长度规避。

同时补入行为 oracle：负 volume fail-closed；raw-shares `log(volume_t)-log(volume_(t-2))` 的 `log(3)` 数值；
同日 `(close-open)/open` 的 `0.1` 数值；以及 config 全部冻结 section/字段值和类型的逐项断言。仍未运行任何验证命令。

## Validation2 V2 记录

中央已记录历史 Validation2 原生 unit chunk `9ee9b5`：exit `1`，`3 failed, 9 passed`；失败属于当时
Pearson fixture oracle 与 calendar-superset 断言，不能回填为期望值，也不改变生产公式。Ruff/mypy 当时
`UNRUN`。本次静态返工已按任务书 §15 修正：共同 open=128 与整数 close 差、独立手算
`3*sqrt(3)/(2*sqrt(13))`、`-1` 与同序/反序 ±1 oracle；合法 calendar superset 接受；真实 bar 日期移出
calendar 才拒绝；并增加严格 lag1 bar-presence 的 feature-level spy 断言。上述仍是静态源码交付，未宣称新的运行通过。

## §15.1 中间矩阵补充

最新测试在同一次真实公共 helper 调用中保存 ordered long-form input 与真实 output，断言 exact-one call、
`sessions[2:8] × 3 symbols × 2 components` 的唯一 key 闭包，并逐证券逐组件核对：return 输入为整数差/128、
volume 输入为独立 d_volume 的自然 log lag-2 数值、normalized rank 为 A/B/C 全部六期冻结矩阵。B 证券的正仿射
rank 变换虽可能保留最终 Pearson，已被中间 rank 精确断言击穿；未从生产因子输出反推 expected。

补充：中间 input oracle 对 `intraday_return = d/128` 使用逐项 exact equality；仅 raw natural-log volume lag-2
使用 `pytest.approx` 容纳 log 浮点误差。

## Validation3–5 原生结果与控制偏差收口

本节为中央提供的历史原生证据追加，经理未重新执行任何命令，未创建或清理证据/Temp/cache。

- V3：turn `01a07ac6-74b8-79a2-8d5a-367706058dec`，chunk `32bc00`，outer exit1；`foreach($n in$names)` token
  边界错误在产品启动前阻断，T3 absent，Python/unit/Ruff/mypy 均 UNRUN，结论
  `VALIDATION3_PREFLIGHT_STOP / OUTER_FOREACH_TOKEN_BOUNDARY_ERROR / PRODUCT_NOT_EVALUATED`。
- V4：unit chunk `a67398` 为 `14 passed, 196 warnings in 2.88s`、exit0；Ruff文本为 `All checks passed!`，但外层
  exit记录命令错误，故 V4 Ruff 无可靠阶段 exit 闭包，mypy UNRUN；V4 Temp 保留。
- V5：中央接受 V4 unit 有效证据，不重复 unit；Ruff chunk `aecbea` 文本 `All checks passed!`、可靠 exit0；mypy
  session `47575`/chunk `be6631` 为 `Success: no issues found in 1 source file`、exit0。V5 root scope 首次
  控制表达式另有 foreach 错误，随后由中央无循环只读检查补齐；不把首次 scope 命令写成通过。

V5 Ruff 实际 argv 顺序为 `-m`, `ruff`, `check`, production, test, `--config`, `pyproject.toml`，缺少 §14 冻结的
独立 `--no-cache`；因此记录为工具结果通过但控制合同偏差，不改写为 exact command PASS。V5 前 root `.ruff_cache`
为空，V5 后出现的 `.ruff_cache` 归因本次缺 flag，保留且不删除；V4/T4、V5/T5 亦按合同保留，不能宣称
global cache0 或 Temp-absent。

本追加对应唯一终态：
`R21_WINDOWS_PRODUCT_STAGES_PASS / CONTROL_CONTRACT_DEVIATION_RECORDED / CACHE_RETAINED / ECONOMIC_UNASSESSED / TRIAL0`。
它不关闭 Linux Gate、不提供经济有效性证据，也不授权策略 run、PAPER 或 LIVE。追加前 delivery 4713 bytes 的
UTF-8 raw prefix 保持逐字不变；本文件仍为历史追加，不伪造 V3/V4/V5 独立日志或完整合规证据。
