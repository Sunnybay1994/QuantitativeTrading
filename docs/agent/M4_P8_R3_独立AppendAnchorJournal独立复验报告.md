# M4 P8 R3：独立 Append Anchor Journal 独立复验报告

日期：2026-08-09  
角色：未参与 R3 实现的全新独立初验 Agent  
结论：**FAIL**

## 结论摘要

R3 的双根、append-only anchor、terminal capability 与 Gate fresh-verify 主合同经代码审查和定向对抗后成立：
语义合法 retained closure 整体替换、已有 key 重签、crash exact 补锚、anchor 链删除/新增/换序/跳号/重复 key、
错误 predecessor/receipt/facts、双根复制、symlink、旧 capability、hostile decoder、并发 sequence 竞争、正式
未来/回溯时间以及 development never-PASS 均有 fail-closed 证据。

但是独立增加的“全新进程、相邻公共模块先导入”反例发现 P8 公共导出引入循环依赖。Windows 和 WSL base 中
直接导入 `quant.backtest.event_simulator` 均失败；`test_event_simulator.py` 与
`test_trading_metrics.py` 单文件收集也失败。P8/P5-P8 大套件因测试导入顺序预先初始化部分模块而隐藏该回归。
这破坏正常公开模块的冷启动可导入性，故 R3 本轮不得进入主验，也不得据此注册正式 runner。

## P1 阻断：P8 eager public export 形成跨包循环导入

### 现象与最小复现

Windows 原生 Miniforge，全新 Python 进程：

```text
PYTHONPATH=src python -c "import quant.backtest.event_simulator"
ImportError: cannot import name 'evaluate_a_share_intent' from partially initialized module
'quant.backtest.a_share_execution'
```

同平台分别单跑以下测试，均在 collection 阶段失败：

```text
pytest tests/unit/test_event_simulator.py -q
pytest tests/unit/test_trading_metrics.py -q
```

WSL Miniforge base、`/mnt/f` 上同一个全新进程导入探针得到相同 `ImportError`。

### 根因

当前依赖链为：

```text
quant.backtest.__init__
  -> a_share_execution
  -> quant.execution.__init__
  -> quant.execution.soak
  -> quant.reporting.__init__
  -> trading_metrics
  -> event_simulator
  -> 尚未完成初始化的 a_share_execution
```

另一冷启动顺序还会在 `quant.reporting.execution_report` 尚未完成初始化时，由 `execution.__init__` 再次导入
`soak`，得到 partially initialized `ExecutionCashLine`。R3 将 `soak` 的全部符号 eager re-export 到
`quant.execution.__init__`，而 `soak` 又依赖 reporting/backtest 合同；结合 P7 的 reporting eager export 后形成
闭环。静态检查和先导入 `execution/soak` 的大测试集合不会暴露该问题。

### 应遵循规则、必须新增测试与通过条件

- 公共包入口不得因新增 P8 导出反向拉入 reporting/backtest 并破坏既有模块冷启动导入。
- 采用最小依赖解环；不得通过固定 pytest 文件顺序或测试预导入掩盖问题。
- 新增全新解释器或等价隔离进程回归，至少覆盖：
  `quant.backtest.event_simulator`、`quant.reporting.trading_metrics`、
  `quant.execution.soak` 与任务冻结的公共导入路径，各自独立导入成功。
- 单跑 `test_event_simulator.py`、`test_trading_metrics.py`、`test_execution_soak.py` 均须收集并通过；随后再跑
  P5-P8 合流范围、Ruff、mypy 与 WSL base 对应验证。

## Anchor 与 Gate 合同核对

- `anchor_root` 与 `evidence root` 均要求绝对路径、身份进入 manifest/run id，且相同或祖先/后代关系拒绝；
  已存在 symlink/junction 祖先由 `_safe_path` 拒绝。
- writer 在 receipt/facts exclusive/no-clobber 写入并从磁盘复验后才 append anchor；已有 key 只接受 exact
  receipt/facts，另一份合法 closure 及同步全量重哈希不能得到新 anchor。
- anchor 文件名与 sequence 从 1 连续，previous id、唯一 `(kind,key)`、严格递增 UTC、canonical bytes 和 exact
  目录集合均由磁盘 reader 重新核对。两个不同 next writer 竞争同一 sequence 时只有一个成功；失败者保留
  evidence，exact retry 从新 terminal 接续，不产生分叉。
- verifier 要求 evidence 与 anchor 双向 exact 对应，verified identity 绑定 terminal anchor；decision 先以显式
  双根 fresh 调用 verifier，并要求 fresh capability 与传入 capability exact equal。
- 独立 hostile decoder 探针注入 `TOKEN C:/secret BROKER_MARKER`，公开结果仅为
  `SOAK_EVIDENCE_INVALID`，marker 不可见且 cause/context 均为 `None`。
- 独立正式时间边界探针确认：旧于五分钟 `1 微秒` 及未来 `1 微秒` 的 started_at 均稳定拒绝；development
  capability 没有 PASS 分支。

上述证据证明 R3 anchor/TOCTOU 返工方向正确，但不抵消公共导入回归。

## 验证命令与结果

Windows 原生 Miniforge：

```text
P5-P8 定向合流（含 P8）: 404 passed, 6 skipped
P8 standalone（由同一范围覆盖）: 41 cases collected，其中 Windows symlink 能力相关 skip
Ruff: All checks passed!
mypy: Success: no issues found in 2 source files
独立 hostile decoder + 正式未来/回溯时间: INDEPENDENT_HOSTILE_TIME_PASS
event_simulator standalone import/test: FAILED during import/collection
trading_metrics standalone test: FAILED during collection
```

WSL Miniforge base、`/mnt/f`：

```text
P8: 41 passed
Ruff: All checks passed!
mypy: Success: no issues found in 2 source files
event_simulator standalone import: FAILED with the same circular ImportError
findmnt: /mnt/f -> F:\, drvfs, case=off
```

WSL 结果仅是 base + DrvFS 开发兼容证据，不是 ext4/Linux 正式 Gate。本轮没有启动或注册正式 28 日 soak，
没有网络/broker 调用，没有触碰正式 artifacts/journal；除本报告外保持生产代码、实现测试与正式产物只读。

## 最终判定

**FAIL**。R3 的 append anchor 与 stale-capability 闭环本身通过独立挑战，但 P8 公共导出造成双平台冷启动循环
导入，属于进入主验前必须关闭的合流阻断。状态应回到“最小依赖解环返工 -> 新增独立导入顺序回归 -> 全新
独立复验”；M4 继续保持 `WAITING_FOR_SOAK_EVIDENCE`，正式 runner、真实 28 日和 ext4/Linux Gate 均保持开放。
