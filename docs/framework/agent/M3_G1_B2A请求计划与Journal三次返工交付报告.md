# M3 G1 B2A 请求计划与 Journal 三次返工交付报告

日期：2026-07-13  
独立二次复验：[`M3_G1_B2A请求计划与Journal独立二次复验报告.md`](M3_G1_B2A请求计划与Journal独立二次复验报告.md)  
二次返工：[`M3_G1_B2A请求计划与Journal二次返工交付报告.md`](M3_G1_B2A请求计划与Journal二次返工交付报告.md)  
状态：no-receipt 只读状态矩阵已返工并自测；等待独立三次复验，不代表 B2A/B2/G1/M3 通过

## 1. 返工边界与红灯证据

本轮只修改原 B2A 的 `m3_backfill.py`、`storage.py` 和两个单元测试文件，并新增本报告。未修改独立报告、
SSOT、路线图或 Gate；未读取 `_old/`、本地 token 配置，未联网。

先把独立二次复验的 9 类非法 raw 布局加入“raw/journal 普通文件集合前后相同”断言，并增加以下闭包组合：

- raw `COMPLETE` 但 intent 缺失；
- candidate 存在但 intent 缺失；
- candidate 存在但 raw 为 `ABSENT/EMPTY`。

修复前定向结果为 **91 通过、13 失败**：9 个非法布局都会新增 `intent.json`，raw COMPLETE 缺 intent 和
candidate 缺 intent 会被自动补齐，candidate/raw 不闭合虽最终失败但错误发生在联合闭包判断之后。

## 2. 为什么“零 API”不等于“零副作用”

前两轮实现和自测都把失败门禁的主要计数器放在 connector、monotonic 和 sleep 上。第二次返工已确保非法
raw 在供应商调用前失败，但 executor 顺序仍是：

```text
创建或验真 intent → 读取 raw 状态 → 决定恢复或联网
```

因此“没有联网”只证明外部供应商副作用为零，不能证明本地证据未改变。`intent.json` 是 journal 的正式
审计证据，不是可忽略的临时文件。对一个不可能由合法 writer 产生的 raw orphan/symlink 状态自动新增
intent，相当于在预检失败前部分修复证据闭包，破坏 fail-closed。

首次和二次自测都没有发现这一点，是因为测试只断言 API/clock/sleep 和最终错误码，没有在执行前后快照
journal 普通文件集合。通用教训是：门禁验收必须列出全部可观察副作用，包括本地持久化证据，并检查门禁
是否位于第一个副作用之前。

## 3. 冻结的 no-receipt 只读状态矩阵

新增私有 frozen 状态对象 `_NoReceiptPreflight`，一次返回：

- `raw_state`: `ABSENT/EMPTY/COMPLETE`；
- `intent_exists`；
- `candidate_exists`；
- `mode`: `NETWORK/RECOVER`。

`_preflight_no_receipt` 在任何 `_ensure_intent` 调用前：

1. 通过 `RawStore.inspect_request_state` 严格读取 raw 状态；
2. 通过 `lstat` 只读确认 intent/candidate 是否为实际普通文件；
3. 验证 candidate、intent、raw 的闭包关系；
4. 已有 intent 必须严格解析并与 spec 一致；
5. 返回 NETWORK 或 RECOVER 模式。

executor 只有在 `mode=NETWORK` 且 intent 不存在时才发布 intent。随后 `_recover_candidate` 仍独立重验 raw，
并要求实际结果与 preflight mode 一致，避免状态变化被静默解释为另一条路径。

状态矩阵如下：

| raw | intent | candidate | 只读结果 | 后续动作 |
|---|---|---|---|---|
| ABSENT/EMPTY | 无 | 无 | NETWORK | 允许创建 intent，再首次联网 |
| ABSENT/EMPTY | 合法 | 无 | NETWORK | 不改 intent，允许重试联网 |
| COMPLETE | 合法 | 无 | RECOVER | 零网络恢复 candidate/receipt |
| COMPLETE | 合法 | 合法 | RECOVER | 零网络验真并恢复 receipt |
| COMPLETE | 无 | 任意 | 失败 | 不自动补 intent，不写普通文件 |
| ABSENT/EMPTY | 任意 | 有 | 失败 | candidate/raw 不闭合，不写普通文件 |
| 任意非法 raw 布局 | 任意 | 任意 | 失败 | 不写 intent/candidate/receipt |
| 已有非法 intent | ABSENT/EMPTY | 无 | 失败 | 只读验真失败，不覆盖、不联网 |

committed receipt 分支保持原约束：intent、candidate、raw 和 receipt 必须形成完整闭包。

## 4. 生产回归

### 4.1 九类非法 raw

以下布局全部断言 connector/monotonic/sleep 为 0，且 raw/journal **普通文件集合执行前后完全相同**：

- data only；
- metadata only；
- request directory symlink；
- request path 普通文件；
- 额外未知普通文件；
- 未知目录；
- file symlink；
- directory symlink；
- FIFO。

异常 message、repr 和 traceback 继续不包含测试物理路径；request symlink 外部目录保持为空。

### 4.2 合法与闭包组合

- raw ABSENT + 无 intent：正常首次网络；
- raw EMPTY + 无 intent：正常首次网络；
- raw ABSENT/EMPTY + 已有合法 intent：严格验真后允许网络重试；
- raw COMPLETE + 已有合法 intent、无 candidate：既有 after-metadata 故障回归零网络恢复；
- raw COMPLETE 缺 intent：零写失败；
- candidate 缺 intent：零写失败；
- candidate + raw ABSENT/EMPTY：零写失败；
- 已有非法 intent：普通文件集合不变、零网络失败；
- committed receipt 的完整闭包和零网络复用保持通过。

## 5. 最终验证

全部命令在 WSL Miniforge base 执行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
106 passed in 6.89s

python -m pytest -q
407 passed, 1179 warnings in 13.42s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

1179 条 warning 仍是既有 Pandera/Polars deprecation warning。本轮未发现需要修改 SSOT 或扩大到
mapper/B3/B4 的新问题。

## 6. 状态

- 未联网、未读取 token；
- 未修改独立报告、路线图、Gate 或其他任务包；
- 当前只可写“等待独立三次复验”，不得宣称 B2A、B2、G1 或 M3 通过。

