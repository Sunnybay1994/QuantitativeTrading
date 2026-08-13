# M3 G7D-F0 R4：benchmark 510300 SSOT 主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS；恢复 formal G7E 设计冻结，不等于真实全 work、Linux/ext4 或 M3 Gate。**

## 1. 验收结论

G7E 设计审计发现并停止于上游 SSOT 冲突：项目权威配置与交接规定 M3 v1 benchmark 只能是可交易 ETF
`510300.SH`，而 F0 formal facts 与 F1 date guard 仍使用旧 `H00300.CSI`。R4 已关闭该冲突：F0 只从已经过
G7B fresh closure 的 `fresh_context.config.section("data")["benchmark"]` 取得 selector，并 exact 要求
`510300.SH`；没有新增 caller selector、路径、裸 TOML 读取或第二套配置。

## 2. 最小修复边界

- F0 selected benchmark exact 为 `510300.SH x execution_dates`，每日一行；原 Schema、物理顺序、source、八表
  root/file、portable digest、whole hash与process-local attestation闭包不变。
- F1 date guard 删除旧 benchmark 代码常量，只验证 exact F0 capability 的 benchmark frame 对请求日期恰有一行。
  F1 public API 已在任何 property 前拒绝 fake/development/subclass，且 exact capability 每次属性读取都会执行 R3
  内容与来源重验，因此这不是接受裸 frame 或放宽 selector。
- G7C、F1、F2 其余生产语义、public exports、config、G1 release与正式 artifact均未改变；
  `backtest/__init__.py` 本轮零修改。
- `a_share_execution.py` 的 F0/F1 production path 已无 `H00300.CSI`。全仓 G1规划器仍有两处合法的旧指数
  参数过滤/拒绝常量，不属于本轮残留，未作过度清理。

## 3. 独立复验

全新独立初验结论 PASS，新增对抗全部通过：

1. old-only `H00300.CSI` 无法签发 formal facts；
2. old+new 混表只选择 `510300.SH`，三路 selected content digest 按内容变化；
3. G7B config drift、F0 fresh顺序与 hostile异常图、F1 fake/subclass前置拒绝均 fail closed；
4. 合法 `510300.SH` capability 可贯穿 F1/F2。

独立最终证据：Windows/WSL当前邻接各 `74 passed`，fixed-order各 `26 passed`，额外定向 `6 passed`；
两平台 Ruff、mypy、cold import与diff check均PASS。计数与实现阶段的76差异来自后续测试节点演进，不是失败。

## 4. 主 Agent 验证

主 Agent 对最终 revision 复验：

- Windows F0+F1+F2 三正式文件：`68 passed`；
- WSL base 同组三文件：`68 passed`；
- Windows Ruff/mypy：PASS；
- WSL base Ruff/mypy：PASS；
- scoped `git diff --check`：退出0，仅有既有 LF/CRLF 提示；
- 静态审查确认 config selector 在 G1/G7B fresh exact 后读取，F0 selector与F1 date guard职责分离正确。

当前 SHA256：

- `a_share_execution.py`：`8CF60BCB0906628D556C14BE9B6B8F7694BD68432F64BE2C74E1D4B19CAA19D0`
- `test_m3_formal_a_share_market_facts.py`：`73A6682EE54E403AAA5684703309EFC4C2B140EB7AB620BC839340285B11ADF7`

测试仅产生既有 pandera deprecation warnings。WSL 实路径为 `/mnt/f`/DrvFS，只证明兼容，不是 ext4 Gate。

## 5. 后续边界

formal G7E 设计冻结可以恢复，但必须维护独立 mark book，覆盖当前持仓、target与未结权益证券；不得仅用
`PositionBook.mark_price` 推断应收股估值或 FULL_DAY stock settlement。G7E 还必须在自身调用栈 fresh消费
F0/G7B/G7C/F2，不能接受 caller transition或裸frame。未联网、未add/commit、未触碰正式G1/artifact/journal。
