# M3 G7D-F2 R2：referenceOpen 与 RejectionNotional 闭包交付报告

日期：2026-08-09  
角色：实现 Agent  
结论：**R2 实现与双平台自测完成，等待全新独立复验；本报告不宣布主验或 Gate PASS。**

## 1. 返工原因与冻结合同

R1 独立初验确认，合法 transition 的普通 non-null rejection 可被单独漂移
`rejected_notional` 后重新构造。根因是 transition 没有保存本 session 的 exact F1 reference open，因而只能校验
quantity residual，不能复算普通 rejection 的经济金额。

按任务单 §15，R2 新增有序 `reference_opens`，要求其 symbol set exact 等于 non-null intent symbol set，并以同次
F1 的 reference open 逐项复算 fill 与五类普通 rejection。R2 首轮反例进一步证明：special-only non-null intent
可能没有 fill 或普通 rejection，微小 reference 漂移又不改变 floor(raw)，仅靠已有值字段不能满足“任一 entry
单独漂移必拒绝”。实现停止扩大并保留失败证据，待任务单 §16 重冻后新增 canonical self-digest。

## 2. 实现范围

严格在 F2 白名单内完成：

- `src/quant/backtest/a_share_execution.py`
  - `AShareSessionExecutionTransition` 新增只读值字段 `reference_opens` 与
    `reference_opens_sha256`；
  - builder 从 exact 同一次 F1 结果、仅按 non-null intents 生成升序且唯一的 reference entries；
  - reference entry exact 校验 outer/inner tuple、str、finite positive Decimal 与顺序；
  - digest payload 固定为 canonical JSON
    `["m3-formal-reference-opens-v1", [[symbol, decimal_plain_text], ...]]`，Decimal 使用无指数 plain text；
  - `__post_init__` fresh 重算 lowercase 64hex SHA-256，并使用 `compare_digest` 比较；
  - fill 的 `reference_open` 必须 exact 等于对应 entry；五类普通 non-null rejection 必须 exact 等于
    `reference_open * rejected_quantity`；
  - 保留 §14 target-attainability BUY LOT 的 `target_notional` 复算和 null intent 的 mark-gap 复算，二者不误用
    ordinary 公式。
- `tests/unit/test_m3_formal_a_share_session_execution.py`
  - 固化 T+1、SELL LOT、ordinary BUY LOT、CASH、SELL_AT_LOWER_LIMIT 五类 notional 漂移；
  - 固化 reference 增删、换序、重复、类型、单 entry 漂移、digest 单改与 fill/reference 不一致；
  - 覆盖 current=0 raw=0/raw<min、current>0 §14 SELL+target LOT 的 special-only reference 漂移；
  - 覆盖 FULL_DAY/null intent 无 reference，并保留 reference+digest 同步 whole-rehash 的诚实边界对照。
- `src/quant/backtest/__init__.py`
  - 仅保留 R1 已冻结的安全 public 导出，无新增旁路。
- 本任务单
  - 状态更新为 R2 自测完成、待全新独立复验和主验。

未修改 G7E、G7C、F0/F1 API、Schema、enum、config、corporate actions、NAV、artifact/journal 或 I/O；未联网、
add 或 commit。除任务书指定的 `hmac.compare_digest` 恒定时间比较外，未引入 signer、HMAC-based authority、
key、registry、seal 或来源 authority。

## 3. 合同闭包与诚实边界

`reference_opens_sha256` 只证明 transition 内 reference entries 与其 canonical 自摘要一致；它不是签名、capability、
首次来源或防篡改锚。caller 同步修改完整 reference set、重算 digest，并同步构造另一套自洽普通值，仍属于任务单
承认的 plain-value whole-rehash 边界。后续 G7E 必须内部调用 public F2 并立即消费，禁止接受 caller transition。

经济闭包不依赖 digest 代替：普通 rejection 仍逐项以 exact reference open 与 rejected quantity 在私有 Decimal
context 内复算。§14 target-notional 与 null mark-gap 保持各自独立守恒域。

## 4. 最终 revision 验证证据

所有命令均在 `artifacts/dev_worktrees/m3-g4-formal` 使用工作树自身 `src`。

### 4.1 Windows 原生 Miniforge

- F2/F1/development execution/allocation：**111 passed**，238.93s；
- F0/G7C/development simulator：**37 passed**，224.02s；
- Ruff：**PASS**；
- mypy：**PASS**；
- cold import/public signature：**PASS**；public signature 无 `open_states`，未加载 qlib/lightgbm/mlflow。
- production 白名单 `git diff --check`：**PASS**；最终白名单 status 仅列任务单、R2 报告、production/export 与
  formal test，未包含本会话的白名单外改动。

### 4.2 WSL Miniforge base

- F2/F1/development execution/allocation：**111 passed**，231.66s；
- F0/G7C/development simulator：**37 passed**，182.61s；
- Ruff：**PASS**；
- mypy：**PASS**；
- cold import/public signature：**PASS**。

WSL 工作树实际位于 `/mnt/f`/DrvFS；本轮只计双平台兼容证据，不声称 Linux/ext4 Gate。两平台 pytest 均仅有
既有 pandera deprecation warnings 与工作树 `.pytest_cache` 写权限 warning，不影响测试结果。

R2 首轮在 §16 重冻前的 special-only 漂移反例为 **1 failed / 110 passed**；这是合同缺口证据，不计最终绿测。
§16 实现后 targeted 反例与最终双平台 `111 + 37` 全部通过。一次 WSL 并行静态调用因未在工作树目录启动导致
mypy internal error，不计证据；改为任务书指定工作目录逐项重跑后 Ruff、mypy、cold 均取得上述可计 PASS。

## 5. 待验与交付结论

R2 已达到进入全新独立复验的条件。独立复验须重新覆盖 ordinary rejection、special-only reference、自摘要与
whole-rehash 边界，并不得由本实现会话承担。只有全新独立复验 PASS 后才进入主 Agent 主验；当前不宣布 M3
Gate、G7E、artifact 发布或 Linux/ext4 已通过。
