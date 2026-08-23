# M3 G1 B2A 请求计划与 Journal 独立三次复验报告

## 1. 复验身份、范围与结论

本报告由未参与本轮实现和三次返工的独立验收 Agent 编写。复验依据如下：

- [`M3_G1_B2A请求计划与Journal实现初验任务单.md`](M3_G1_B2A请求计划与Journal实现初验任务单.md)；
- [`M3_G1_B2A请求计划与Journal三次返工交付报告.md`](M3_G1_B2A请求计划与Journal三次返工交付报告.md)；
- 前三份独立记录：
  [`独立初验`](M3_G1_B2A请求计划与Journal独立初验报告.md)、
  [`独立复验`](M3_G1_B2A请求计划与Journal独立复验报告.md)、
  [`独立二次复验`](M3_G1_B2A请求计划与Journal独立二次复验报告.md)。

本轮只读检查生产代码，并使用临时目录运行隔离反例；未访问网络、Tushare token、`_old/` 或真实数据，
也未修改生产代码和测试。

**结论：独立三次复验不通过。** 三次返工已经关闭二次复验记录的静态非法 raw 先写 intent 问题；
14 个非法状态均在 connector/monotonic/sleep 为 `0/0/0` 时失败，且 raw/journal 普通文件集合零增量。
但本轮新增发现一个 **P1** 可观察持久化顺序缺陷和一个 **P2** 内部不变量缺口。全量测试绿色不能替代这两个
未进入生产测试的反例。因此本报告不宣布 B2、G1 或 M3 Gate 通过。

## 2. 三次返工已关闭的核心问题

### 2.1 非法状态只读门禁

独立状态矩阵共执行 14 个非法组合，结果 **14/14 通过**：

| 组合 | 数量 | connector/monotonic/sleep | raw 普通文件增量 | journal 普通文件增量 | 结果 |
|---|---:|---:|---:|---:|---|
| data only、metadata only | 2 | `0/0/0` | 0 | 0 | 通过 |
| request symlink、request 普通文件 | 2 | `0/0/0` | 0 | 0 | 通过 |
| 额外普通文件、未知目录 | 2 | `0/0/0` | 0 | 0 | 通过 |
| file symlink、directory symlink、FIFO | 3 | `0/0/0` | 0 | 0 | 通过 |
| raw COMPLETE 但缺 intent | 1 | `0/0/0` | 0 | 0 | 通过 |
| candidate 存在但缺 intent | 1 | `0/0/0` | 0 | 0 | 通过 |
| candidate + raw ABSENT/EMPTY（保留合法 intent） | 2 | `0/0/0` | 0 | 0 | 通过 |
| intent 非法 JSON | 1 | `0/0/0` | 0 | 0 | 通过 |

九种非法 raw 均返回稳定 `RAW_ORPHAN_OR_INVALID_LAYOUT`；闭包冲突返回
`REQUEST_EVIDENCE_CLOSURE_INVALID`；损坏 intent 返回 `INTENT_INVALID`。执行前后按 `lstat` 快照比较普通
文件集合，不把仅创建后清理的 writer lock 或空目录误报为普通文件。

### 2.2 合法状态、恢复和抗篡改

独立合法/回归组合共 **10/10 通过**：

| 组合 | connector/monotonic/sleep | raw 普通文件增量 | journal 普通文件增量 | 结果 |
|---|---:|---:|---:|---|
| raw ABSENT、无 intent 首次请求 | `1/1/0` | 2 | 3 | 通过 |
| raw EMPTY、无 intent 首次请求 | `1/1/0` | 2 | 3 | 通过 |
| intent-only 失败后重试 | `1/1/0` | 2 | 2 | 通过 |
| COMPLETE + 合法 intent，`after_metadata` 崩溃恢复 | `0/0/0` | 0 | 2 | 通过 |
| candidate + COMPLETE + 合法 intent，缺 receipt 恢复 | `0/0/0` | 0 | 1 | 通过 |
| committed receipt 幂等重跑 | `0/0/0` | 0 | 0 | 通过 |
| batch hash/phase 构造后篡改 | `0/0/0` | 0 | 0 | 通过 |
| 嵌套 request ID/parameters 构造后篡改 | `0/0/0` | 0 | 0 | 通过 |

后四项 `object.__setattr__` 篡改均在 raw/journal root 创建前以 `ValueError` 拒绝，说明原 P1-1 的公开
调用边界重建仍然有效。定向套件还覆盖原 P1-3 未知 journal 项、P1-4 IO/Parquet 异常脱敏以及 legacy
`RawStore.write` 行为，均未回归。

## 3. 新 finding

### P1：状态重验在闭包变化时先持久化 candidate，之后才拒绝

- **现象**：执行器在 `src/quant/data/m3_backfill.py:559` 得到 `NETWORK` 决策后，若 request raw 在进入
  `_recover_candidate` 前变成 COMPLETE，`_recover_candidate` 会先在 `src/quant/data/m3_backfill.py:801`
  写入 `candidate.json`，执行器随后才在 `src/quant/data/m3_backfill.py:573` 比较实际结果与旧 mode，并以
  `REQUEST_EVIDENCE_CLOSURE_CHANGED` 失败。错误码正确，但门禁晚于 journal 普通文件副作用。
- **根因**：`_recover_candidate` 同时承担“读取/验真当前状态”和“发布 candidate”两项职责；调用者只有
  在该函数返回后才有机会比较预检决策，因此无法在第一个持久化副作用前拒绝决策漂移。
- **应遵循规则**：重验必须先只读得到实际状态并与冻结决策比较；闭包改变时，在 connector、时钟、休眠
  以及 intent/candidate/receipt 新写入之前 fail-closed。不能用最终报错掩盖报错前已经产生的证据。
- **最小复现**：先通过一次永久 provider failure 形成合法 intent-only 状态；让 `_preflight_no_receipt`
  返回 `NETWORK` 后、`_recover_candidate` 调用前，由第二个 raw writer 使用公开
  `RawStore.write_request` 写入一致的完整 raw pair。随后执行器的 connector/monotonic/sleep 仍为
  `0/0/0`，但 journal 普通文件增量为唯一的 `<request_id>/candidate.json`，最后才抛
  `REQUEST_EVIDENCE_CLOSURE_CHANGED`。隔离探针只借助 monkeypatch 精确放置第二 writer 的时机；写入动作
  本身调用的是正常公开 RawStore API，并非伪造内存对象。
- **可达性与威胁模型**：正常单 executor 且不存在任何第二 raw writer 时，该状态不会自行变化；稳定复现
  需要另一进程、恢复脚本或注入 writer 恰好命中预检与恢复之间的窗口。journal 全局 writer lock 不锁
  RawStore，故第二 raw writer 在实现上可达，但这不是无需并发即可触发的静态布局缺陷。之所以仍列 P1，
  是本轮明确验收条件要求 closure changed 不产生新的 journal 普通文件，而且当前副作用是持久、可观察的
  evidence，而不只是内核级瞬时路径替换。
- **新增测试**：保留上述 intent-only + 预检后完整 raw 到达反例；断言错误码、`0/0/0` 调用计数，并分别
  比较 raw/journal 普通文件集合。raw pair 是夹具注入的外部变化，生产代码不得额外生成 candidate/receipt。
- **通过条件**：执行以 `REQUEST_EVIDENCE_CLOSURE_CHANGED` 失败，journal 普通文件集合零增量；建议把
  `_recover_candidate` 拆成只读验真和发布两阶段，或显式传入 expected mode 并在
  `_write_dataclass_once` 前完成比较。修复仍可诚实保留“不能抵御所有内核级恶意竞态”的首版限制。

### P2：私有 `_NoReceiptPreflight` 没有运行时 enum/type/跨字段不变量

- **现象**：`src/quant/data/m3_backfill.py:352` 的 frozen dataclass 没有 `__post_init__`。直接构造可接受
  非法 raw/mode 枚举、`intent_exists=1`，以及 `COMPLETE + no intent`、`candidate + no intent`、
  `COMPLETE + NETWORK`、`ABSENT + RECOVER` 等互相矛盾的组合；独立探针 7 类非法值全部构造成功。
- **根因**：`Literal` 和 `bool` 标注只供静态检查，不提供运行时验证；`frozen=True` 只禁止普通赋值，
  不建立构造时不变量。
- **应遵循规则**：承担执行分支决策的状态对象应在自己的构造边界闭合 enum、精确类型和跨字段关系，避免
  后续修改者或测试 seam 把不可能状态带入执行路径。
- **最小复现**：`_NoReceiptPreflight("COMPLETE", False, True, "NETWORK")` 和
  `_NoReceiptPreflight("BROKEN", 1, False, "RECOVER")` 均不报错。
- **可达性与严重度**：该类是私有、非持久化对象，不由 `execute_tushare_batch` caller 传入；正常生产入口
  只消费 `_preflight_no_receipt` 的内部返回，当前未证明 caller 能在不 monkeypatch/修改内存的情况下向
  执行器注入伪造对象。因此这是低成本应关闭的防御性不变量缺口，定为 P2，而不是公开信任边界 P1。
- **新增测试**：逐项覆盖非法 enum、非精确 bool 和四种矛盾组合；同时保留状态矩阵中所有合法构造。
- **通过条件**：非法直接构造均以 `ValueError` 拒绝；合法 NETWORK/RECOVER 组合不回归。建议添加窄小的
  `__post_init__`，不要把完整文件系统验真逻辑复制进状态对象。

## 4. 工具链与回归结果

全部命令在 WSL Miniforge base Python（`/home/mabw/miniforge3/bin/python`）执行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
106 passed in 6.80s

python -m pytest -q
407 passed, 1179 warnings in 13.75s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

warnings 均为现有 Pandera/Polars deprecation warning，本轮没有新增失败。真实网络和 token 未参与验证，
因此本报告不对真实 Tushare 配额、响应覆盖或网络恢复作结论。

## 5. 返工建议与下一轮通过条件

实现 Agent 下一轮应按以下最小范围返工：

1. 调整 no-receipt 的重验/发布顺序，确保决策漂移在 candidate 发布前失败，并加入 P1 隔离回归；
2. 为 `_NoReceiptPreflight` 增加精确类型、枚举和闭包关系校验，并加入 P2 直接构造测试；
3. 重跑本报告的 14 个非法状态、10 个合法/抗篡改组合、定向/全量 pytest、Ruff 和 mypy；
4. 返工报告逐项记录“现象—根因—应遵循规则—最小复现—新增测试—通过条件”，并链接本报告。

只有 P1、P2 均关闭，且非法状态继续保持 connector/clock/sleep 为零、raw/journal 普通文件零增量，才可进入
主 Agent 最终验收；独立复验通过本身仍不等于 B2、G1 或 M3 Gate 通过。
