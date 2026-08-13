# M3 G7D-F2 R2：reference open 与 rejection notional 闭包主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS；允许进入 formal G7E，不等于完整账户回测、真实成本 Gate、Linux/ext4 或 M3 Gate。**

## 1. 验收结论

G7D-F2 已形成 formal session 订单执行的纯内存状态转移边界：public API 只接受 exact
`VerifiedAShareMarketFacts`，内部 exact 一次调用 G7D-F1，按冻结顺序完成目标差量、先卖后买、T+1、lot、现金、
费用与离散买入分配。它不接受 caller 裸 open-state，不读取磁盘，不发布 artifact/receipt，也不承担公司行动编排、
mark、NAV、七表或回测发布。

R1 独立初验发现普通非空 rejection 的 `rejected_notional` 未与开盘参考价闭合；R2 现以
`reference_opens` 绑定同次 F1 的非空 intent symbol 域，并逐项重算普通 rejection 的
`reference_open * rejected_quantity`。五类原始反例均已关闭。

## 2. R2 合同闭包

- `reference_opens` 必须 exact tuple、symbol 严格升序且唯一、Decimal finite positive，symbol 集合 exact 等于
  non-null intent 集合；fill 的 `reference_open` 必须与对应 entry 相等。
- `reference_opens_sha256` 采用 canonical JSON
  `['m3-formal-reference-opens-v1', [[symbol, decimal_plain_text], ...]]`，fresh 重算并比较，拒绝单独的 entry、
  digest、增删或换序漂移。
- T+1、普通 SELL/BUY lot、BUY cash 与市场阻断 rejection 均按 reference open × rejected quantity 精确复算。
- §14 target-attainability LOT 仍按 target notional；null-open gap 仍按 target value 与 mark value 差额；二者没有被
  普通金额公式错误吞并。
- self-digest 只提供普通值内部一致性；同步修改 reference entries 并重算 digest 仍是允许的 whole-rehash 边界，
  不是签名、来源证明或防篡改锚。后续 G7E 必须在自己的调用栈内调用 F2，不得接受 caller transition。
- 未引入 HMAC、随机 key、registry、seal、IO、网络或新发布协议。

## 3. 独立复验

全新独立复验新增实现者未使用的对抗并全部通过：

1. 五类 ordinary rejection 使用 `+0.007` 单字段金额漂移均拒绝；
2. current=0 的 raw=0/raw<min、current>0 的 blocked SELL + §14 target LOT 使用 `0.0001` reference 漂移均拒绝；
3. digest 单漂移、entry 增删换序、FULL_DAY/null、fill reference 与 hostile 递归异常图均符合合同；
4. reference 与 digest 同步 whole-rehash 可构造，按冻结的普通值边界如实定性，未误称来源防篡改。

独立复验最终证据：Windows `111 + 37 passed`；WSL base `111 + 37 passed`；两平台 Ruff、mypy、cold import
与 scoped diff check 均 PASS。独立报告结论为 PASS，只解锁主验。

## 4. 主 Agent 验证

主 Agent 对最终 revision 定向复验：

- Windows `test_m3_formal_a_share_session_execution.py`：`20 passed`；
- WSL base 同文件：`20 passed`；
- Windows Ruff 与 mypy：PASS；
- WSL base Ruff 与 mypy：PASS；
- scoped `git diff --check`：退出 0，仅有既有 LF/CRLF 提示；
- 代码审查确认 digest fresh 重算、non-null intent exact-set、fill reference、§14 special、null gap 与普通
  rejection 经济复算是相互独立的验证分支。

当前 SHA256：

- `a_share_execution.py`：`693287E7BA44F67B2EA823C4C36287D05E98B1FD786C2BBBE86F3ED9CC4FE372`
- `backtest/__init__.py`：`5A68E189B8CEE61F45720D3BE5C6B47FE582B06B1E1BA8FAF6AA612258773751`
- `test_m3_formal_a_share_session_execution.py`：`D9AE87A11395C268B147ED971532FAFD11D0B5CA0497A4546F8434FCFC0A94AE`

测试仅产生 pandera deprecation warnings；无产品失败。WSL 实路径位于 `/mnt/f`，文件系统为 DrvFS，因而只证明
WSL base 兼容，不是 ext4 Gate。

## 5. 剩余边界

G7E 才负责账户 session 编排：前一日买入 rollover、G7C 盘前 recognize/settle、FULL_DAY 公司行动 mark、
调用 G7D-F2、收盘估值、record-close、七表与正式发布。G7E 必须重新绑定 G7B target/cost provenance，不能把
本 transition 当作来源 capability。未联网、未 add/commit、未触碰正式 G1/artifact/journal。
