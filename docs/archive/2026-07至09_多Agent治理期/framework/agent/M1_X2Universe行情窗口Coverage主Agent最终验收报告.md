# M1-X2 Universe 行情窗口 Coverage 主 Agent 最终验收报告

日期：2026-07-18  
初始任务：[M1_X2Universe行情窗口Coverage实现任务单.md](M1_X2Universe行情窗口Coverage实现任务单.md)  
R1：[M1_X2_R1_Coverage严格跨字段校验与CLI文档返工任务单.md](M1_X2_R1_Coverage严格跨字段校验与CLI文档返工任务单.md)  
R2：[M1_X2_R2_AuditedResult严格绑定返工任务单.md](M1_X2_R2_AuditedResult严格绑定返工任务单.md)

## 1. 最终结论

**M1-X2 查询与 coverage 合同包主验通过。** 该结论覆盖：audited universe window 查询、严格 coverage 数值
不变量、frame/coverage 绑定、canonical symbol、重复键 fail-closed、CLI 默认 report 与
`--require-full-window` no-output 门禁，以及 Windows/WSL 定向兼容。

本结论只证明查询/审计能力，**不证明真实港股通 60 日行情已取得，不关闭 M1 或任何 Gate**。2026-07-18
真实只读审计仍为每路由 644 eligible、2 returned（各 1 日）、642 missing、0 full-window symbols。

## 2. 闭环历史

1. 初始实现/独立初验通过后，主验发现 `requested=2,min=max=3` 可构造且冒充 full window；R1 用
   `full_count/expected_min/expected_max` 公式封闭数值合同并同步 README，独立复验通过。
2. R1 后主验发现非法 symbol 可进入 coverage、空 frame 可绑定 full coverage；R2 使用领域
   `SYMBOL_PATTERN` 并在 `AuditedBarWindow` 构造期重算 key/source/as_of/order/counts/short/min/max 闭包，
   独立复验通过。
3. 两轮均遵循外部实现 → 另一全新外部独立复验 → 主 Agent 终验；没有由主 Agent 直接修补后跳过职责分离。

## 3. 最终合同核对

- 旧 `recent_for_universe()` 签名和兼容语义保留；正式证据路径使用
  `recent_for_universe_audited()` / CLI。
- coverage 值对象冻结且严格验证：类型、排序、唯一、canonical symbol、eligible/returned/missing/short
  守恒，以及 min/max 的唯一推导公式。
- audited result 对非空 frame 校验 key dtype/非空、目标 source、`trade_date <= as_of`、唯一键、canonical
  symbol、`symbol/trade_date` 排序和逐证券 counts；不静默 cast、排序、去重或丢行。
- 空 frame 只允许 returned/max 为零，兼容真空 eligible 与 all-missing；full coverage + empty frame 拒绝。
- CLI strict incomplete 时稳定输出 `BAR_WINDOW_INCOMPLETE`、非零退出且不写 `--output`；README 已同步并明确
  不代表真实覆盖完成。
- coverage 不保存完整 eligible symbol 名单，因此不能验证未出现在 frame/missing/short 中的 full symbol 具体
  身份；该边界已由 R2 明确冻结，查询函数以 membership payload 提供真实集合。

## 4. 主验验证

Windows `D:\Miniforge3\python.exe` 与 WSL Miniforge base 均执行：

```text
pytest tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider
→ 38 passed；exit 0
ruff check src/quant/data/query.py tests/unit/test_query.py
→ All checks passed；exit 0
mypy src/quant/data/query.py
→ Success；exit 0
```

主验未公开反例：构造 1 missing + 1 short + 1 full 的合法混合 frame/coverage，绑定成功；把同一 frame 整体
逆序后必须以 `BAR_WINDOW_INPUT_INVALID` 拒绝。Windows 输出 `X2_R2_MAIN_ADVERSARIAL_PASS`，exit 0。

R1 主验最小复现现已拒绝；R2 独立复验额外覆盖 short symbol identity 错配、returned 伪造、未来/异源/重复/
乱序行、null key、非 canonical frame symbol、frame 与 missing 相交和 rows>requested，两平台均通过。

## 5. 残余风险

- 真实覆盖与结构性短历史另有审计：至少 5 个当前成员在最近第 60 个 HK 开市日后上市，另有 36 个当前成员缺
  clean instrument；不能机械要求所有 644 个证券恰有 60 条，也不能把采集缺失误标成结构性短窗。
- 正式数据恢复必须先补可信 instrument 类型/list date/board lot，再按上市、停牌与 source lineage 分类 coverage。
- Polars/Pandera deprecation warning 仍存在，当前不影响结果；依赖升级前需处理。
