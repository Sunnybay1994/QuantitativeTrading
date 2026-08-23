# M4-C0 主 Agent 最终验收报告

日期：2026-07-16  
结论：**M4-C0 子包最终验收通过**  
边界：不关闭 M4 或任何实盘 Gate，不代表后置 D/P/B 包通过

## 1. 闭环链路

1. 原外部实现与独立初验完成；
2. 主验发现 direct constructor 可绕过安全校验、schema version 双事实和 selector URI 绕过，结论见
   [`M4_C0主Agent终验报告.md`](M4_C0主Agent终验报告.md)；
3. 外部实现按 [`M4_C0主验返工任务单.md`](M4_C0主验返工任务单.md) 完成 F1–F3；
4. 全新外部 Agent 独立初验通过，见
   [`M4_C0主验返工独立初验报告.md`](M4_C0主验返工独立初验报告.md)；
5. 主 Agent 在当前工作树执行最终定向与未公开反例复验。

## 2. 最终验证

环境：WSL Miniforge `base`；无网络、无 data/token、无全量 pytest。

```text
python -m pytest -q tests/unit/test_trading_config.py
→ 19 passed
```

主 Agent 内存反例：

| 反例 | 结果 |
|---|---|
| thaw 合法配置后伪造 `execution.mode=LIVE`，直接构造 `TradingConfig` | `TradingConfigError`，`VALUE_ERROR @ execution.mode` |
| 构造后修改调用方原 dict/list | 已构造 config 仍为 PAPER，identity 不变 |
| 传入独立 `schema_version="forged"` | `TypeError`，不存在第二事实入口 |
| selector 注入 `file:///home/private` | 稳定拒绝，issues 不回显 URI |

外部初验还复跑了目标文件 Ruff/mypy，并以嵌套 unknown/type/path 组合验证了聚合错误和脱敏边界，均通过。

## 3. 最终判定

- `TradingConfig` 的公开构造与文件加载共享同一严格校验、标准化和递归冻结路径；
- `schema_version` 只从 document 派生；
- 四个 version selector 只接受受控 literal，不接受 URI/路径；
- config identity 对递归不可变且已验证的 document 计算。

因此 M4-C0 子包最终验收通过。C0 通过只建立后置 M4 包的配置前置；PAPER/SHADOW 业务闭环、真实数据、券商
Gateway 与实盘安全门禁仍未验收。
