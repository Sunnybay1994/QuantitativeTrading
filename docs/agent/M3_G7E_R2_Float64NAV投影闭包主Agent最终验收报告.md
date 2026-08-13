# M3 G7E R2：Float64 NAV 投影闭包主 Agent 最终验收报告

日期：2026-08-10  
结论：**PASS；G7E 单场景账户回放工程合同完成，G7F 仍等待 P0 主验；不等于 ext4 或 M3 Gate。**

## 验收结论

R1 独立初验发现合法 Decimal 账户在七表出口被 Float64 exact Schema 自拒绝：四个分量与 equity 分别
`float()` 后，不保证 `equity == cash + market_value + cash_receivable + stock_receivable_value` 的二进制
加法路径相同。R2 保留投影前 Decimal 严格恒等式，只把七表输出改为先投影四分量，再按权威 Schema 的同一
左结合顺序生成输出 equity；unit_nav、daily_return 与下一 session 的 previous equity 仍使用原 Decimal 值。

全新独立复验使用非实现者 `0.1 + 0.2` 的数值：Decimal `41104.74 + 58800 = 99904.74`，独立
`float(equity)` 为 `99904.74`，而四分量左结合为 `99904.73999999999`。public 输出精确采用后者并通过七张
权威 Schema；ex-date 首次买入产生一笔 BUY，且不追溯产生 entitlement/CAPTURE。独立还核对 caller Decimal
context/traps/flags、fresh exact-once、hostile/nonexact、row-order、独立 mark book 与 gross/2。Windows/WSL
各 `8 + 90 passed`，Ruff、mypy、cold import、diff-check 均 PASS。

主 Agent 对最终 revision 重新执行 unit+golden：Windows `8 passed`，WSL base `8 passed`；双平台 Ruff 与
mypy 均 PASS。源码核对确认未修改 Schema、F0、G7C、F1、F2，也没有让输出 Float64 反向参与账户状态。当前
SHA-256：

- `a_share_simulator.py`：`2E123BC293137B468307BD64BD8EDE2F4BBBCED0BA48B487596461F235605406`
- `test_m3_g7e_formal_a_share_simulator.py`：`16DBB11E3B22B6FBF2F638D8F54E0F453F74F4DCCBD8D4EB4784FAAEB31A4D88`
- `test_m3_g7e_formal_a_share_simulator_golden.py`：`6D39287929C5619577DE70CD89C7C81736158CEE7941316DDE2A69FCF1F790CD`

Windows 与 WSL 的 pytest cache/Pandera warning 不影响断言。WSL 路径仍为 `/mnt/f`/DrvFS，只构成兼容证据。
未联网、未 add/commit、未触碰正式 artifact/receipt。
