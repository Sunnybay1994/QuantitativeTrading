# M3 G8C-C1 U9 R1：sys.monitoring RAISE 单次诊断报告

日期：2026-08-13  
结论：**完成；定位到测试支持输入缺陷，不是生产订单规则缺陷**

## 1. 执行结果

- Windows `m3chain312` honest producer 成功；G1 阶段 `463.930s`，全链 `2478.233s`。
- `sys.monitoring.events.RAISE` probe 在 `1556.6s` 后取得 public `AShareExecutionError` 前的原始异常事件。
- 最早事件为 `builtins.ValueError`，函数 `resolve_a_share_order_quantity_rule`，bytecode offset `500`；该 offset 对应 `a_share_execution.py:1798` 的 `unsupported A-share board`。
- 同一异常随后依次穿过 `_formal_request_domain`、`_build_formal_open_execution_states`、`build_formal_a_share_open_execution_states`，最后按 public 合同映射为 `M3_A_SHARE_EXECUTION_INVALID`。

## 2. 根因

retained G1 `instrument.parquet` 共 300 行。对其逐证券调用纯函数 `resolve_a_share_order_quantity_rule` 后发现：

- 前 150 行是合法的 `000001.SZ` 至 `000150.SZ`；
- 后 150 行是 `000151.SH` 至 `000300.SH`，不属于生产规则接受的沪市股票代码前缀；
- 无效代码来自 `tests.unit.test_m3_reference._symbols`，而 public-chain support 直接复用了该只面向 G1 数据合同的合成 fixture。

因此 F2 fail-closed 行为正确。不得把 `000xxx.SH` 放宽为沪市主板；应在 public-chain support 中生成执行层也合法的证券代码。

## 3. 最小修正

- `tests/support/m3_formal_public_chain/g1_inputs.py` 新增 `_execution_compatible_symbols()`：精确生成 150 个 `000001.SZ`–`000150.SZ` 和 150 个 `600001.SH`–`600150.SH`。
- 仅在构造 public-chain G1 raw inputs 的局部窗口替换并恢复上游 unit fixture `_symbols`；生产代码和通用 G1 单测 fixture 不变。
- `tests/unit/test_m3_g8c_c1_backtest_cli.py` 新增 300 个代码逐项通过 public 数量规则 resolver 的快速回归。

开发检查：focused `1 passed`；Ruff、`py_compile`、scoped `git diff --check` 通过。单独对 support 文件运行 mypy 会递归分析既有测试模块并暴露既有 test-only 类型问题，未作为本次通过证据。

## 4. 清理证据

cleanup token：`ea121d65c77f47f6bad4f6024cf262c9`。

按 locator 中的设备、inode、类型和全树 SHA-256 精确移除：

1. G1 release 根；
2. stage root；
3. session config。

cleanup receipt 为 `m3-g8c-c1-u6-cleanup-receipt-v1`，`residual=[]`。没有复制、改址或保留 capability/正式产物。

## 5. 后续

下一次 honest public-chain 运行应使用修正后的 300 个有效 A 股代码。若回放仍失败，按新的第一个真实失败边界继续串行诊断；不回退生产 fail-closed 规则。
