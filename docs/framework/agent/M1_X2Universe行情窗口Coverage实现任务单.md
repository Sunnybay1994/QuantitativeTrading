# M1-X2 Universe 行情窗口 Coverage 实现任务单

日期：2026-07-18  
状态：已授权零网络实现；不等于已取得全港股通 60 日真实数据，不关闭 M1 Gate

## 1. 目标与现状

现有 `BarQuery.recent_for_universe()` 正确返回 as-of 成员的“每证券最多 N 个观测”，但调用方无法知道 eligible
证券总数、静默缺失证券、短窗口证券或逐证券计数。CLI 只报告返回 rows/symbols，不能作为正式 60 日覆盖证据。

本包保留原方法兼容行为，新增显式 coverage 结果和可选 strict full-window 门禁；不扫描 `data/legacy`、不联网、
不制造不存在的历史行情。

## 2. 成功标准

- [ ] 定义不可变、严格校验的 coverage/result 值对象，至少包含：eligible symbol 数、returned symbol 数、
  missing symbols、short symbols 及其计数、min/max observations、requested observations、as_of、source、universe。
- [ ] 新的 audited 查询一次性绑定 membership payload 与 bar payload；结果只含 as_of 有效成员、指定 source、
  `trade_date <= as_of`，每证券最多 N 行，排序和 coverage 均确定。
- [ ] 保留 `recent_for_universe()` 的现有签名/语义；CLI 改用 audited 查询并输出 coverage 摘要。
- [ ] CLI 增加显式 `--require-full-window`：只要 missing 或任一 count < N，输出稳定脱敏错误摘要并返回非零；
  默认 report 模式仍允许新上市/短历史，但必须显式报告，不再静默。
- [ ] 重复 `(symbol, trade_date, source)`、结果混入其他 source、未来行、非 eligible 行均 fail closed；不得用
  drop/去重掩盖 clean 冲突。
- [ ] 无 bar 文件时仍读取 membership 并报告全部 eligible 为 missing；membership 文件缺失保持 fail closed。
- [ ] coverage 不写数据；仅当 CLI 显式给 `--output` 且查询/门禁成功时写 parquet。strict 失败不得留下 output。
- [ ] Windows/WSL 聚焦测试、Ruff、mypy 通过；路径使用 `pathlib`，JSON 不依赖平台分隔符做 identity。

## 3. 文件白名单

- `src/quant/data/query.py`
- `src/quant/data/query_universe.py`
- 新建或修改与这两个模块直接对应的 query 单元测试（优先现有文件；若无则
  `tests/unit/test_query.py`、`tests/unit/test_query_universe.py`）
- `docs/framework/agent/M1_X2Universe行情窗口Coverage实现交付报告.md`

禁止修改其他生产代码、Schema SSOT、`AGENTS.md`、`README.md`、配置、`data/**`、`artifacts/**`、`.git`；
禁止真实查询命令和联网。

## 4. 接口与失败语义

具体命名可由实现者选择，但必须是 typed public result，而非松散 dict。推荐：

```python
@dataclass(frozen=True)
class BarWindowCoverage: ...

@dataclass(frozen=True)
class AuditedBarWindow:
    frame: pl.DataFrame
    coverage: BarWindowCoverage

def recent_for_universe_audited(..., observations: int = 60) -> AuditedBarWindow: ...
```

strict CLI 失败使用稳定 code（例如 `BAR_WINDOW_INCOMPLETE`），错误输出只含计数和 canonical symbols，不包含
绝对路径、SQL 或原始 payload。输入 `observations` 必须 `type is int and > 0`，拒绝 bool/float。

## 5. 关键反例

1. eligible=A/B/C，A=60、B=59、C=0：report 模式返回 A/B 行并报告 short B、missing C；strict 失败且无 output。
2. eligible 集合非空但 bar root 无 parquet：coverage 仍为 eligible=3/missing=3，不得错误报告 eligible=0。
3. 同 symbol/date/source 两行：失败，不得由 row_number 随机选择其中一行。
4. 同证券混有第二 source 与 as_of 未来行：都不得进入 frame/计数；目标 source 自身重复仍失败。
5. membership 行顺序、bar 文件/行顺序变化不改变 frame 排序和 coverage。
6. 基线日前/无历史区间查询沿用 eligibility 稳定失败语义，不降级为空池成功。

## 6. 外部闭环与验证

实现 Agent 使用全新 `cursor-grok-4.5-high`；Windows base 与 WSL base 均验证。最低命令：

```text
python -m pytest tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider
python -m ruff check src/quant/data/query.py src/quant/data/query_universe.py tests/unit/test_query.py tests/unit/test_query_universe.py
python -m mypy src/quant/data/query.py src/quant/data/query_universe.py
```

若仓库现有测试文件名不同，使用实际文件并在报告中如实记录。实现后另一全新外部会话只读初验，唯一允许写
`docs/framework/agent/M1_X2Universe行情窗口Coverage独立初验报告.md`，新增“bar 文件不存在但 eligible 非空”与“目标
source 重复键”反例。

## 7. 停止条件

- 需要改 Schema、membership 发布合同、CLI 之外的公共行为或引入依赖；
- 试图用 forward fill、其他 source 或当前名单回填缺失历史；
- 真实 data 的覆盖不足被包装成代码通过或 M1 Gate 完成。

