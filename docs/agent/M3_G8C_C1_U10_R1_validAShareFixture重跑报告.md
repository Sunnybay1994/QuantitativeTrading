# M3 G8C-C1 U10 R1：有效 A 股 Fixture Honest Chain 重跑报告

日期：2026-08-13  
结论：**U9 无效沪市代码阻断已关闭；完整 replay 未在原 30 分钟诊断预算内取得终态**

## 1. Producer

- 300 个证券均通过 public `resolve_a_share_order_quantity_rule`：150 个 `000001.SZ`–`000150.SZ`，150 个 `600001.SH`–`600150.SH`。
- honest G1 public publish/verify 成功，`485.920s`。
- G1 → snapshot → provider → folds → feature → label → alignment → model → prediction → target → backtest plan 全链成功，`2512.242s`。
- retained locator：schema `m3-g8c-c1-u6-retained-locator-v1`；stage tree 2448 files，G1 release 18 files。

这证明 U9 的 `unsupported A-share board` 是测试支持输入缺陷，修正后生产订单规则无需放宽。

## 2. Replay

- 唯一 0.5x probe 使用 public resolver、public F0 facts loader、actual G7E/G7C/F1/F2 和低开销 `sys.monitoring.events.RAISE` observer。
- 运行 `1831s` 后仍无 public/private exception evidence，CPU 持续增长且进程正常；达到任务单 30 分钟停止边界后由主 Agent终止。
- 与 U9 在约 25 分钟内稳定产生 F2 board `ValueError` 不同，本轮没有该异常，说明执行已越过原阻断。现有证据不足以宣称完整 replay 成功，也不支持猜测新产品缺陷。

## 3. 清理

cleanup token：`9a9f3427056c47bb93fdc66336d0aa9f`。

按 locator 的设备、inode、类型和全树 SHA-256 精确移除 G1 release、stage root、session config；cleanup receipt `residual=[]`。未保留 capability 或正式产物。

## 4. 下一步

下一次重跑保持同一 300 证券 honest chain，仅把 replay 诊断预算从 30 分钟扩到 45 分钟；不缩小证券域、不绕过 fresh verifier、不改变生产控制流。若 45 分钟仍无终态，停止重复全链，改做性能阶段测量任务。
