# M3 G7D-F2 R3：null-gap ambient Decimal 主 Agent 最终验收报告

日期：2026-08-10  
结论：**PASS；F2 ambient合同已恢复。G7E仍等待F1 R2，不等于完整账户回测、ext4或M3 Gate。**

## 验收结论

R2主验后在G7E hostile context联调中发现，formal null-gap构造与validator对私有80位subtract结果再次调用
ambient-sensitive `abs()`；caller prec50会使F2自己生成的transition被自身拒绝。R3只把这两处改为Decimal
`copy_abs()`，未改变API、§14-§16分域、reference self-digest、普通rejection金额或development整数quantity。

全新独立复验新增prec17/50/79、ROUND_CEILING/FLOOR/HALF_EVEN、Overflow/Inexact traps组合，FULL_DAY held
null-gap在build与低层replace后16字段逐项一致，caller precision/rounding/traps/flags前后不变；单金额漂移继续拒绝。
独立最终Windows/WSL均为`112 + 37 passed`，Ruff/mypy/cold/diff均PASS，结论PASS。

主Agent对最终revision复验：Windows formal F2 `21 passed`，WSL base `21 passed`；双平台Ruff/mypy PASS；
scoped diff-check退出0，仅既有LF/CRLF提示。当前SHA256：

- `a_share_execution.py`：`32F4D26AFCC34FE318BE578FF33E106AE702F4AE77F6BD6B86D62931AD21334B`
- `test_m3_formal_a_share_session_execution.py`：`9525B0F1A33AEB0534A8CA2D71BF8E6ACEE838050DA90C863A399E092381702A`

独立复验另确认F1 half-tick仍有ambient division缺口；该问题已单独冻结为F1 R2，不归为F2失败，也不得由
G7E固定prec80掩盖。WSL路径为`/mnt/f`/DrvFS，仅为兼容证据。未联网、未add/commit、未触正式artifact。
