# M2-R21-SINGLE-PASS-TRACE 交付报告

## 结论

`DELIVERY_READY`（Windows fixture-only implementation validation complete）。

本交付只实现任务书 §5.1 / §8 批准的 SinglePassTrace factor 包，不实现 runner 接入，
不改变 ETF 链，也不构造 receipt、label、evaluate、publish 或经济执行路径。

## 实现与文件范围

本次 exact3 改动为：

1. `src/quant/factors/classic_eleventh_batch.py`
   - 保留原 `compute_eleventh_batch_daily_factors(bars, *, sessions)` 签名、三列结果、实际 bar keys、排序、
     正零归一、输入校验和错误顺序。
   - 抽出共享计算 core；旧入口和新入口各自只经过一次特征构造、一次公共
     `rank_cross_sectional_components` 调用和一次六期相关统计。
   - 新增 `compute_eleventh_batch_daily_factors_with_trace`，在同一 grid/ranked/correlation 中间关系上投影
     `factors`、`component_counts`、`observations` 三张表；完整 session grid 的无 bar 行不会进入 factors。
   - component 计数、lag/session flags、rank member flags、window/pair、两侧 ss 与 primary reason 均由同次中间关系投影。
   - 新入口返回前执行 schema、键/排序、有限性、window、rank、方差与最终因子一致性检查；trace-only 不可解释状态
     fail closed 且不返回 partial mapping，旧入口不执行该诊断拒绝。
2. `tests/unit/test_classic_eleventh_batch.py`
   - 增加三表 exact schema/order/dtype、旧新因子恒等、single rank call、完整 grid/no-bar、warmup/lag/gap、
     zero-volume、single-member/all-tie、variance reason、输入拒绝和无 bar ss 故障注入覆盖。
   - 保留既有独立手算 Pearson、rank、正零、gap、负 volume、nonfinite、schema 与配置 oracle；未以共享 core
     自比较替代独立预期。
3. `docs/research/deliveries/M2_R21_SinglePassTrace交付报告.md`
   - 本报告。

未修改 taskbook、roadmap、runner、receipt、labels、rank helper、config、schema、evaluator、`__init__.py` 或 ETF 链。

## 合同与负例映射

- `factors` 仅为 `symbol/String`、`trade_date/Date`、`alpha101_002/Float64`，键来自实际 bars；新旧入口逐值、null、
  排序和正零一致。
- `component_counts` 固定两 component、按 `trade_date/component` 排序；`grid_symbols` 是输入 symbols × sessions，
  `finite_values` 来自 long-form，`ranked_values` 来自同次公共 rank，n<2 时为 0。
- `observations` 覆盖 symbols × 完整 sessions；index 0/1 的 lag 为 null，index<5 的 `window_ready=false/pair_count=null`，
  index 5/6 仍为八期 warmup；缺 bar 不压缩窗口；lag1 volume=0 不额外过滤；ss 不 clamp。
- 当前缺 bar 优先于 warmup，随后按 warmup、pair、双侧/volume/return 非正方差、VALID 的顺序生成 `primary_reason`。
  VALID 与当前 bar 存在且最终因子非 null/finite 严格等价。
- 覆盖缺 bar 的 lag1/lag2 与 pair incomplete、组件单成员 rank null、n>=2 全 tie 仍有有效 rank 但非正方差、
  当前/lag2 zero-volume flags、负 volume/nonfinite/schema fail-closed，以及乱序和合法 calendar superset。
- 故障注入只把 trailing 无 bar grid row 的 `_u_ss` 改为 finite 异常：legacy 因实际 bar-key 投影保持不变，trace
  因 trace-only intermediate inconsistency 拒绝且不返回三表。

## 验证环境与结果

验证均在 source worktree 内、单进程、Windows fixture-only 完成：

- interpreter: `D:\Miniforge3\python.exe`
- `POLARS_MAX_THREADS=2`
- `OMP_NUM_THREADS=1`
- `PYTHONDONTWRITEBYTECODE=1`
- pytest 为确保 editable 安装不解析到主 checkout，额外将当前 worktree 的 `src` 放入本进程 `PYTHONPATH`；命令参数保持任务书原样。
- 未访问项目真实 `data/`、raw、ledger、run 产物、网络或外部账户。

正式通过阶段严格为：

1. `D:\Miniforge3\python.exe -m pytest -q tests/unit/test_classic_eleventh_batch.py -p no:cacheprovider --basetemp=artifacts/agent_runs/m2-r21-single-pass-trace/pytest-attempt-20260908-03`
   - exit `0`
   - native result: `23 passed, 358 warnings in 3.08s`
2. `D:\Miniforge3\python.exe -m ruff check --no-cache src/quant/factors/classic_eleventh_batch.py tests/unit/test_classic_eleventh_batch.py`
   - exit `0`
   - native stdout: `All checks passed!`
3. `D:\Miniforge3\python.exe -m mypy --cache-dir artifacts/agent_runs/m2-r21-single-pass-trace/mypy src/quant/factors/classic_eleventh_batch.py`
   - exit `0`
   - native stdout: `Success: no issues found in 1 source file`

此前尝试也保留在 source 内 fresh evidence 目录：

- `pytest-attempt-20260908-01`：收集阶段 exit `1`；解释器解析了主 checkout 的已安装 editable 包，未加载当前 worktree 新导出。
- `pytest-attempt-20260908-02`：`22 passed, 1 failed`；失败为测试 tie fixture 在不同 open 下的浮点 oracle，修正为共同 `open=128` 后使用 attempt-03 重新验证。

## 未运行项与边界

未运行 full suite、Linux/WSL Gate、runner/receipt/label/evaluate/publish、真实数据或网络、trial、经济收益验证、PAPER、LIVE，
也未运行 ETF 链。上述 Windows 结果只证明本交付的 fixture-level development validation，不证明 Linux 兼容性、数据覆盖、因子有效性、
promotion 或任何交易准入。

验证产生的 `artifacts/agent_runs/m2-r21-single-pass-trace` 仅为未提交证据/cache，未加入 exact3 staging。

## Source identity

- task: `M2-R21-SINGLE-PASS-TRACE`
- branch: `codex/m2-r21-single-pass-trace`
- exact base / pre-implementation HEAD: `b6998b7e9960eb089bf4e07034f9ed86c94fcbd0`
- implementation source commit: `6fd05834cca189df50b9fa2542df5da56f73e023`
- parent of implementation source commit: `b6998b7e9960eb089bf4e07034f9ed86c94fcbd0`
- the final documentation-only follow-up commit carries this completed delivery report; the implementation source identity above remains unchanged.
