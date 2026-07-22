# M1-X1 复权因子首日基线 Fail-Closed 主 Agent 最终验收报告

日期：2026-07-18  
任务单：[M1_X1复权因子首日基线FailClosed实现任务单.md](M1_X1复权因子首日基线FailClosed实现任务单.md)  
交付：[M1_X1复权因子首日基线FailClosed实现交付报告.md](M1_X1复权因子首日基线FailClosed实现交付报告.md)  
独立初验：[M1_X1复权因子首日基线FailClosed独立初验报告.md](M1_X1复权因子首日基线FailClosed独立初验报告.md)

## 1. 最终结论

**M1-X1 零网络合同包主验通过。** 显式复权路径现对每个已返回 bar 的证券要求首根 bar 当日或之前存在
累计因子基线；任一证券缺失或只有未来因子时全局 fail closed，不返回部分结果、不把 bar 原
`adj_factor` 静默当作有效因子。该结论不证明账号具有 `hk_adjfactor` 权限，不证明真实港股复权链路或 M1
里程碑完成。

## 2. 合同与实现核对

- `AdjustmentFactorCoverageIssue.reason` 稳定区分 `missing_symbol` 与
  `no_baseline_on_or_before_first_bar`；错误只包含 canonical symbol/date/reason，不包含路径、凭据或原始响应。
- `apply_adjustment_factors` 在任何 as-of join 前完成全局 coverage preflight；首 factor
  `effective_date == first_trade_date` 合法，晚一日失败，变化日使用新因子。
- `BarUpdatePipeline` 先留存 bar/factor raw，再执行 coverage；通过后才调用 factor clean store，随后质量门禁
  与 bar clean。coverage 失败时两个 clean store 都未调用；显式不启用 factor 的路径不受影响。
- 输入仍由 `Bar1dSchema` 与 `AdjustmentFactorSchema` 校验；未改变 Schema、配置、依赖、CLI 或包根导出，故本包
  不需要额外 README/配置同步。

## 3. 主验执行证据

Windows Miniforge base：

```text
pytest tests/unit/test_adjustments.py tests/integration/test_bar_pipeline.py
       tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider
→ 27 passed；exit 0
ruff check X1/X2 八个白名单 Python 文件
→ All checks passed；exit 0
mypy adjustments.py pipeline.py query.py query_universe.py
→ Success；exit 0
```

WSL Miniforge base（`/home/mabw/AI_Coding_win/QuantitativeTrading`）：同一组合命令结果为 27 passed、Ruff
通过、mypy 通过，均 exit 0。

主验未公开反例：bar 只含合法 `600000.SH`，factor 另含无 bar 的 `00700.HK` 未来事件；期望仅按 bar symbol
检查，合法证券成功匹配 2.0，不能被无关 factor 误伤，且输入 bar 原值 9.0 不被原地修改。Windows 输出
`X1_MAIN_ADVERSARIAL_PASS`，exit 0。

## 4. 残余风险与边界

- 请求列表中完全没有返回 bar 的证券不属于 X1 coverage 对象；其缺失由行情质量/coverage 门禁负责，不能用
  X1 代替。
- coverage 通过后若后续 bar 质量门禁失败，factor clean 已写入；这不是 X1 冻结的 coverage 失败原子性范围，
  如需跨 clean store 事务须另立合同。
- 两平台输出有 Pandera/Polars deprecation warnings，不影响当前结果，但依赖升级前需处理。
- 真实 `hk_adjfactor` 权限仍缺失；不得把本次手算/fixture 证据写成真实港股复权验收。
