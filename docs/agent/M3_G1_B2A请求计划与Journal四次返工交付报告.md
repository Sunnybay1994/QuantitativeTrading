# M3 G1 B2A 请求计划与 Journal 四次返工交付报告

日期：2026-07-13  
独立三次复验：[`M3_G1_B2A请求计划与Journal独立三次复验报告.md`](M3_G1_B2A请求计划与Journal独立三次复验报告.md)  
三次返工：[`M3_G1_B2A请求计划与Journal三次返工交付报告.md`](M3_G1_B2A请求计划与Journal三次返工交付报告.md)  
状态：已完成 P1 状态漂移和 P2 私有状态对象不变量返工并自测；等待独立四次复验，不代表 B2A/B2/G1/M3 通过

## 1. 返工边界

本轮只修改 `src/quant/data/m3_backfill.py` 和 `tests/unit/test_m3_backfill_requests.py`，并新增本报告。
`storage.py` 与 `test_storage.py` 仅参与回归，没有产生修改。未修改独立复验报告、SSOT、路线图、Gate 或其他
任务包；未读取 `_old/`、本地 token 配置，未联网。

## 2. 红灯与根因

先增加受控第二写者和私有对象直接构造测试。修复前定向结果为 **5 通过、10 失败**：

- P1：已有合法 intent、raw 初始 `ABSENT`。`_preflight_no_receipt` 判定 `NETWORK` 后，受控第二写者通过
  `RawStore.write_request` 写出同请求的合法 COMPLETE raw。旧 `_recover_candidate` 根据新状态恢复并先发布
  `candidate.json`，外层随后才以 `REQUEST_EVIDENCE_CLOSURE_CHANGED` 失败。connector、clock、sleep 都是 0，
  但 journal 普通文件集合已被本执行器改变。
- P2：`_NoReceiptPreflight` 只有 `Literal` 类型标注，没有运行时 `__post_init__`。非法枚举、`int` 冒充
  `bool` 以及 mode/证据闭包矛盾都能直接构造成功。

P1 的根因不是缺少最终错误，而是错误门禁位于首次持久化副作用之后。外层比较只能作为二级断言，不能
保护 candidate 的首次发布。

## 3. P1：在首次 candidate 持久化前验证 expected mode

`_recover_candidate` 现在必须显式接收 `expected_mode`：

- no-receipt 分支传入只读预检冻结的 `preflight.mode`；
- committed receipt 分支只能传入 `RECOVER`。

恢复函数首先只读检查 candidate 是否为普通文件以及 raw 当前状态，再按冻结模式执行：

| expected mode | 当前状态 | 结果 |
|---|---|---|
| NETWORK | candidate 不存在，raw ABSENT/EMPTY | 返回网络路径，不写 candidate |
| NETWORK | candidate 已出现或 raw COMPLETE | `REQUEST_EVIDENCE_CLOSURE_CHANGED`，不写 candidate/receipt |
| RECOVER | raw COMPLETE，candidate 已存在 | 验真既有 candidate，不新增证据 |
| RECOVER | raw COMPLETE，candidate 不存在 | 验真 raw，构造 candidate；写入紧前再次核对闭包 |
| RECOVER | raw ABSENT/EMPTY | `REQUEST_EVIDENCE_CLOSURE_CHANGED`，不写 candidate/receipt |

写入紧前的第二次检查要求 raw 仍为 COMPLETE 且 candidate 仍不存在。原外层 mode/result 比较保留为二级
防御，但不再承担首次副作用门禁。

### 3.1 对抗性回归

新增两个受控状态漂移反例：

1. `NETWORK → COMPLETE`：第二写者只写 raw。执行器返回 closure changed，connector/clock/sleep 为 0，
   journal 普通文件集合保持原来的 intent-only，不新增 candidate/receipt。
2. `RECOVER → EMPTY`：第二写者在预检后移除 raw data/metadata。执行器在恢复前失败，connector/clock/sleep
   为 0，journal 普通文件集合不变。

测试把外部第二写者引起的 raw 变化与当前执行器自身的 journal 副作用分开断言。这里的威胁模型是遵守
journal 全局 writer lock 的执行器，以及可能在预检与恢复检查之间改变 raw 的受控外部写者。实现采用
进入恢复时检查和首次 candidate 发布前复查；不宣称提供跨 raw 与 journal 两个存储根的通用事务隔离。

## 4. P2：`_NoReceiptPreflight` 内部防御不变量

新增 frozen dataclass 的运行时 `__post_init__`，要求：

- `raw_state` 只能是 `ABSENT/EMPTY/COMPLETE`；
- `intent_exists`、`candidate_exists` 必须是 exact `bool`，拒绝 `1/0`；
- `mode` 只能是 `NETWORK/RECOVER`；
- NETWORK 当且仅当 raw 为 ABSENT/EMPTY 且 candidate 不存在；
- RECOVER 当且仅当 raw 为 COMPLETE 且 intent 存在，candidate 可存在或不存在。

测试覆盖 4 个合法构造及 9 个非法构造，非法集合包含独立三次复验要求的全部类别：非法 raw enum、两种
非 exact-bool、非法 mode、NETWORK+COMPLETE、NETWORK+candidate、RECOVER+ABSENT、RECOVER+EMPTY、
RECOVER+intent false。

## 5. 验证结果

全部命令在 WSL Miniforge base 执行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py -k "no_receipt_preflight or second_writer or raw_regression"
15 passed, 98 deselected in 1.51s

python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
121 passed in 6.77s

python -m pytest -q
422 passed, 1179 warnings in 13.33s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

1179 条 warning 是既有 Pandera/Polars deprecation warning。本轮未修改警告来源。

## 6. 状态与后续验收

- P1/P2 的实现者自测已通过；
- 未修改路线图、Gate 或 SSOT 状态；
- 当前状态只能表述为“等待独立四次复验”；
- 独立复验通过后仍需主 Agent 最终验收，不能据此宣称 B2A、B2、G1 或 M3 通过。
