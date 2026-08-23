# M3 G7D-F1 R2：half-tick ambient Decimal 主 Agent 最终验收报告

日期：2026-08-10  
结论：**PASS；F1 ambient Decimal 合同恢复，允许恢复 G7E；不等于完整账户回测、ext4 或 M3 Gate。**

## 验收结论

G7E/F2 hostile Decimal 联调发现，formal F1 在涨跌停半 tick 边界直接执行 Decimal 除法和环境敏感加减；
caller 的低精度、非默认舍入或 Inexact trap 会使合法开盘事实投影失败。R2 仅新增 exact
`Decimal("0.005")` 半 tick，并将 formal 阈值计算改为既有私有 80 位 `_formal_subtract/_formal_add`；
development 路径、公开 API、F0 capability 与 F2 订单语义均未改变。

全新独立复验覆盖 default 以及 prec 3/17/50/79、ROUND_CEILING/FLOOR/HALF_EVEN、Inexact/Overflow
traps，确认两个 formal public API 逐字段一致，caller precision、rounding、traps 与 flags 前后不变；同时覆盖
upper/lower 等号及正负 `1e-12` 边界、fake/development/subclass 在零 property access 前拒绝。独立回归
Windows 与 WSL base 均为 `135 + 14 passed`，Ruff、mypy、cold import、diff-check 全部 PASS。

主 Agent 对最终 revision 重新执行 formal F1 文件：Windows `26 passed`，WSL base `26 passed`；双平台
Ruff 与 mypy 均 PASS，scoped diff-check PASS。当前 SHA-256：

- `a_share_execution.py`：`6F8A7CB854BCB4D4EFFCE68351362588081CD598068248418F0B55E6306E079F`
- `test_m3_formal_a_share_open_execution.py`：`9EDABD1E992F181B2B44BF7F322D5627A2F311FE0991678243D0EF74EFD28D56`

Windows 与 WSL 的 pytest cache 权限 warning 不影响断言结果。WSL 路径仍为 `/mnt/f`/DrvFS，只构成兼容
证据，不宣称 ext4 Gate。未联网、未 add/commit、未触碰正式 artifact。
