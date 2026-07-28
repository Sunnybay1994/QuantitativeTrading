# M3 G1 P0E：小额分红 factor / market 精度返工任务单

状态：**已完成外部实现、独立初验与主 Agent 最终验收；仅关闭 P0E，不代表 G1 / Windows publish / Linux Gate 通过**

## 1. 目标

修复 [`20260727_M3_G1_P0D后正式首败_000627小额分红精度.md`](20260727_M3_G1_P0D后正式首败_000627小额分红精度.md)
记录的正式首败：有完整实施分红事件时，`actual_factor_ratio` 与
`market_reference_factor_ratio` 可能因报价/供应商精度稳定在 `1±rtol`，不得仅因 ratio
不严格大于 1 而拒绝。

本轮不得处理 `000661` 配股、`600733` 重复实施行或其他后续首败；不得放宽无事件路径。

## 2. 必须保持的不变量

1. `NO_EVENT_STABLE_FACTOR` 仍只允许 `event_count=0` 且
   `abs(actual_factor_ratio-1)<=rtol`；无事件大跳继续
   `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`。
2. 有事件路径不得清空 `event_ids`、回退为 no-event 或丢失 cash/stock 经济事实。
3. 分母 `previous_close-cash<=0`、declared ratio `<=1`、缺前收、缺必要 daily、
   actual/market 远离支持域或 actual 与 market 超差，均继续 fail closed。
4. raw、receipt、daily、factor、dividend 和 P0D scoped topology 不变。
5. 不硬编码 `000627`、日期、证券或金额。

## 3. 冻结算法

定义：

```text
supported_ratio(x) := x > 1.0 OR abs(x - 1.0) <= rtol
```

event 分支：

1. 保留现有 previous close、declared formula、daily pre_close、event identity 和误差计算。
2. `actual` 必须为正（Schema 已保证），且必须满足 `supported_ratio(actual)`。
3. 有 ex-date daily 时：
   - `market = previous_close / daily.pre_close`；
   - `market` 必须满足 `supported_ratio(market)`；
   - `abs(actual/market-1)<=rtol`；
   - declared 误差在容差内仍为 `MATCHED_EVENT_DECLARED_FORMULA`，否则仍为
     `MATCHED_EVENT_MARKET_REFERENCE`。
4. 无 ex-date daily 时仍只允许 `FULL_DAY + declared_error<=rtol`；同时 actual 必须满足
   `supported_ratio(actual)`。
5. 不新增 status 或列。Schema 中现有 matched 状态的 `actual>1` / `market>1` 条件改成与
   上述 `supported_ratio` 等价的逐行条件；顶层正数、有限值和所有 identity/formula 校验保留。
6. reconciliation method version 从
   `tushare_factor_daily_preclose_v3` 升为
   `tushare_factor_daily_preclose_v4`。candidate / release 继续传播该 SSOT；不无理由提升
   manifest 结构版本。

## 4. 文件白名单

生产代码：

- `src/quant/data/m3_execution_facts.py`
- `src/quant/domain/schemas.py`

测试：

- `tests/unit/test_m3_execution_facts.py`
- `tests/unit/test_m3_g1_candidate.py`
- `tests/unit/test_m3_g1_planning.py`
- `tests/unit/test_m3_reference.py`

文档/报告：

- `docs/agent/M3_G1_无dividend事件因子跳变接受合同修订.md`：只把旧宽松合同标记为已废止，
  指向 P0/P0E，正文保留作历史；
- 新建本轮交付报告。

若实现需要修改白名单外生产文件，停止并提交接口冲突证据。

## 5. 最小测试矩阵

1. **真实形状 happy path**：event cash=`0.005`、previous close=`2.91`、
   actual=`1.0`、market=`1.0`、declared error 大于 rtol：
   输出 `MATCHED_EVENT_MARKET_REFERENCE`；event_count/ids/cash 全保留。
2. event actual=`0.9995`、market=`1.0`、rtol=`0.001`：允许；证明容差是对称的。
3. event actual=`0.998`、market=`0.998`：即使相互匹配也拒绝，防止远离 1 的反向 ratio。
4. event actual=`1.0`、market 明显 `>1` 且相互超差：拒绝。
5. event actual=`1.0`、无 daily、非 FULL_DAY：拒绝。
6. event actual=`1.0`、FULL_DAY、无 daily，但 declared error 超 rtol：拒绝。
7. no-event actual=`1.0` 仍为 `NO_EVENT_STABLE_FACTOR`；no-event 大 jump 仍拒绝。
8. 将 happy path 结果伪装为 NO_EVENT、清空 event ids 或改 cash，并同步表 digest：
   Schema/verifier/candidate audit 至少一层拒绝。
9. 版本常量和 planning/candidate/reference 传播精确为 v4；旧 v3 build spec 不得冒充新语义。

独立初验必须另加至少一个实现者未使用的边界反例。

## 6. 验收命令

Windows 原生快速反馈：

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_execution_facts.py tests/unit/test_m3_g1_candidate.py tests/unit/test_m3_g1_planning.py tests/unit/test_m3_reference.py -q --tb=short
D:\Miniforge3\python.exe -m ruff check <本轮生产与测试文件>
D:\Miniforge3\python.exe -m mypy src/quant/data/m3_execution_facts.py src/quant/domain/schemas.py
git diff --check
```

外部实现与初验通过后，由主 Agent 运行隐藏反例、定向静态检查和正式零网络 `status`。
本轮通过不代表 G1、Windows publish 或 Linux/ext4 Gate 通过。
