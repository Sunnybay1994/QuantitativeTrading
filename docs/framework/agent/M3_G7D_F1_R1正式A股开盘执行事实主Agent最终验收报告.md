# M3 G7D-F1 R1：正式 A 股开盘执行事实主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS；允许冻结 G7D-F2，不等于完整 G7D、账户回测、Linux/ext4 或 M3 Gate。**

## 1. 验收结论

G7D-F1 已形成唯一 formal 开盘事实投影边界：两个 public API 只接受 exact
`VerifiedAShareMarketFacts`，在任一 frame property 前拒绝 development/fake/subclass，随后先触发 F0 identity
与内容重验。F1 不读取磁盘、不回调 G1/G7A/G7B、不新建 facts capability，也不接触账户、费用、撮合、NAV、
entitlement 或 FULL_DAY 公司行动 mark。

## 2. 合同核对

- date 只接受 F0 benchmark 已证明的 execution-date 域；symbols 要求 exact tuple、严格字典序和唯一。
- instrument 必须 exact STOCK/CNY/SH|SZ、suffix匹配且处于上市生命周期；未知板块前缀稳定拒绝。
- 每个请求 key 必须满足 bar XOR FULL_DAY；FULL_DAY 双向禁止交易，非 FULL_DAY 必须有 bar 与有效双侧 limit。
- PARTIAL 使用严格 ` | ` 与半开区间，09:30 落入 `[start,end)` 才视为开盘停牌；未知或不可证明文本保守
  `OPEN_UNKNOWN`。Schema 不允许的空串/None 只保留为 parser/hostile 防御边界，未伪装成合法 capability。
- open 与上下限采用 Decimal 比较，半 tick 边界含等号拒绝；数量规则绑定 instrument、date 与同一请求域。
- 输出复用 exact 12 列 `OpenExecutionStateSchema`，只按 caller 已验证的物理顺序构造，不排序修复。
- F1 返回值不是 formal capability；后续 F2 必须重新接受 facts/date 并在同一调用栈内部投影，不能信任 caller
  修改后的裸 open-state DataFrame。

## 3. 独立反例

全新独立初验新增 5 组未落盘反例并全部通过：

1. 改变 close/high/low/volume，同时令 CA/reconciliation property 在访问时爆炸，open-only 输出逐字段不变；
2. 上市前请求在两个 formal API 均稳定拒绝；
3. fake/subclass/development/DataFrame 在零 facts property access 前拒绝；
4. FULL_DAY 无 limit 双拒、非 FULL_DAY 非有效 band 拒绝、STAR 规则 200/1；
5. hostile 递归异常图只暴露稳定码，cause/context 为空。

## 4. 验证证据

实现与独立初验：

- Windows：F1+F0+development `113 passed`，G7C+simulator `14 passed`，fixed-order `17 passed`；
- WSL base：对应 `113 + 14 + 17 passed`；
- 两平台 Ruff、mypy、cold import 均 PASS；独立初验结论 PASS。

主 Agent 聚焦复验：

- Windows 新 F1 文件：`25 passed`，Ruff PASS；组合 mypy 2.3.0 首次内部错误，standalone
  `--no-incremental --show-traceback` 后 `Success: no issues found in 1 source file`；
- WSL base 新 F1 文件：`25 passed`，Ruff/mypy PASS；
- scoped `git diff --check` 退出 0，仅有既有 LF/CRLF 提示。

当前 SHA256：

- `a_share_execution.py`：`106927450CE2F829F4427D5144866CBBE2F7EE7983C13A871AAE940CD1DA07BE`
- `backtest/__init__.py`：`7C6A67A8762B07BE4D806B02FC6DC42D3B273F7C40BF31FC54932C18EDFDF3F4`
- `test_m3_formal_a_share_open_execution.py`：`ED8AD05B13A2E5A223899C8508001A78BCE3A105F5ADA4B289484F98031C6494`

WSL 实路径位于 `/mnt/f`，文件系统为 DrvFS；这里只证明 WSL base 兼容，不是 ext4 Gate。

## 5. 剩余边界

G7D-F2 必须串行复用本文件，并继续以 exact facts/date 内部重建 F1；不得接受裸 open-state。账户现金、T+1、
先卖后买、费用、滑点与持仓转移属于 F2；公司行动盘前/record-close编排、mark、估值、七表与发布属于后续 G7E。
未联网、未 add/commit、未触碰正式 G1/artifact/journal。
