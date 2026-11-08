   它不是 capability、签名或第二份 open-state；只保存本次 transition 中所有 `requested_quantity is not None` intent
   的 exact F1 reference open。物理顺序严格 symbol 升序、symbol 唯一；每个 inner item 必须 exact 二元 tuple、
   exact str 与 finite positive Decimal。不得保存 close/high/low/limit、FULL_DAY 的伪 0/None open 或 caller 值。
2. public session builder 必须从本次 exact 一次 F1 返回的 open-state frame，在 intent 已构造后生成
   `reference_opens`。其 symbol set 必须 exact 等于 non-null intents 的 symbol set；null intent 不得有 entry，任何
   extra/missing/duplicate/reverse entry fail closed。
3. transition `__post_init__` 在私有 Decimal context 中重验：
   - 每个 fill 的 `reference_open` exact 等于对应 entry；
   - 每个普通 non-null rejection（除 §14 target-attainability LOT 唯一例外）的
     `rejected_notional == reference_open * rejected_quantity`；
   - §14 target-attainability LOT 仍 exact 等于 `target_notional`，不能误改为 open×raw；
   - null-quantity gap 仍用 target notional 与 pre-position mark 复算，且不得查 reference open。
4. 单独漂移任一普通 rejection notional、单独漂移 reference open、增删换序 reference entry、fill reference 与
   entry 不同必须拒绝。同步修改 reference open 与所有相关金额而形成另一套普通自洽值仍只是 plain value 的
   whole-rehash，不在本地 dataclass 来源证明范围；G7E 必须继续自己调用 public F2 并立即消费，禁止接受 caller
   transition。本包不得引入 seal/HMAC/registry 来伪装来源真实性。
5. R2 必须把独立报告中的五类 exact minimal repro 持久化为正式测试，并保留 §14 blocked SELL + target LOT、
   hostile Decimal、极小正 target 与大 STAR oracle。R2 完成后在当前最终 revision 重新运行双平台 `111 + 37`
   邻接，不得沿用 R1 收紧前结果。

R2 文件白名单保持 §12 不变，唯一新增交付报告为
`docs/framework/agent/M3_G7D_F2_R2_referenceOpen与RejectionNotional闭包交付报告.md`；全新独立复验报告固定为
`docs/framework/agent/M3_G7D_F2_R2_referenceOpen与RejectionNotional闭包独立复验报告.md`。只有 R2 全新独立复验 PASS
后才进入主验。

## 16. Special-only reference open 的可证明边界补充（2026-08-09）

R2 首轮测试证明：若一个 non-null intent 只有 §14 target-attainability LOT、没有 fill 或普通 rejection，微小修改
`reference_open` 可能保持 `floor(target_notional/reference_open)` 不变，因而没有其他数值字段可用于 exact 比较。
把测试换成“有 fill 的 symbol”会遗漏这一可达情形，禁止以测试场景替换掩盖合同缺口。

为满足 §15“单独漂移任一 reference entry 必须拒绝”，在 transition 再新增普通自摘要字段：

```python
reference_opens_sha256: str
```

冻结规则：

1. digest payload exact 为 canonical JSON
   `['m3-formal-reference-opens-v1', [[symbol, decimal_plain_text], ...]]`；entry 顺序就是已验证的 symbol 升序，
   Decimal 必须 finite positive并用无指数 canonical plain text，禁止 `str(float)`、repr、路径、平台 identity 或时钟。
2. public builder 从同一次 F1 生成 `reference_opens` 后立即计算 digest；transition `__post_init__` fresh 重算并
   `compare_digest`/exact compare。digest 必须 bare lowercase 64hex。
3. 单改 special-only reference、单改 digest、增删换序 entry 均拒绝；至少覆盖 current=0 raw=0/raw<min、
   current>0 §14 SELL+target LOT、FULL_DAY/null intent 无 reference 三类。
4. 同步修改 reference entries 并重算 digest形成另一套自洽普通值，仍属于任务已承认的 whole-rehash 边界；该
   self-digest 不是签名、capability、首次来源或防篡改锚。G7E 仍必须自己调用 F2，不得接受 caller transition。
5. `reference_opens_sha256` 只补 reference exact 内容绑定；普通 rejection notional 仍必须按 §15 逐项
   `reference_open * rejected_quantity` 复算，不能用 digest 代替经济校验。

本补充不允许 HMAC、随机 key、registry、seal、pickle token 或新文件；白名单和 R2 报告路径保持 §15 不变。

## 17. R2 主验后 null-gap ambient Decimal R3 闭环（2026-08-10）

G7E golden 对照发现：F2 formal null/open-unknown rejection 构造先用私有80位 context计算
`target_notional - current_value`，随后调用 ambient-sensitive `abs(...)`；validator同样先私有subtract再ambient abs。
在caller `prec=50`时，两次舍入位置不同，导致 public F2 自己生成的合法 transition 被自身 `__post_init__`
稳定拒绝；默认prec=28偶然通过。违反§7“所有中间运算使用私有context”和§11 hostile ambient不变量。

R3 只修该局部算术，不改变F2 API、值对象、§14-§16语义或G7E：

1. formal构造与validator中的两处 null-gap absolute 必须使用 exact、ambient-independent 的 Decimal absolute
   primitive（例如私有subtract结果的`copy_abs()`）；禁止用调整caller context或固定G7E precision掩盖。
2. development line中的整数quantity `abs`不在本缺口范围，不做无关修改。全文件其他formal Decimal unary/
   arithmetic必须定向审查，若发现同类ambient逃逸一并以同一私有原语关闭，不扩业务语义。
3. 新增同一合法null-gap case在caller contexts：默认28、prec50、prec4+ROUND_DOWN+Inexact trap下的
   build→transition `__post_init__`，要求逐字段exact相等；caller precision/rounding/Emax/Emin/traps/flags前后不变。
4. 对合法transition低层仅漂移null-gap rejected_notional后仍拒绝；ordinary五类notional、§14 special、reference
   digest/whole-rehash回归保持绿色。
5. 白名单仅 `src/quant/backtest/a_share_execution.py`、
   `tests/unit/test_m3_formal_a_share_session_execution.py`、本任务状态与唯一R3交付报告
   `M3_G7D_F2_R3_nullGapAmbientDecimal返工交付报告.md`。禁止改G7E simulator/tests、F0/F1/G7C、Schema/config。
6. Windows与WSL base重跑最终F2 formal及F0/F1/F2邻接、Ruff/mypy/cold/diff；全新独立复验必须增加
   实现者未用的中等precision/rounding/trap组合，并写唯一
   `M3_G7D_F2_R3_nullGapAmbientDecimal独立复验报告.md`。主验PASS前G7E保持暂停。
