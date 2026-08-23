# M3 G1 B2A 请求计划与 Journal 独立二次复验报告

日期：2026-07-13  
二次返工：[`M3_G1_B2A请求计划与Journal二次返工交付报告.md`](M3_G1_B2A请求计划与Journal二次返工交付报告.md)  
第一次独立复验：[`M3_G1_B2A请求计划与Journal独立复验报告.md`](M3_G1_B2A请求计划与Journal独立复验报告.md)  
原独立初验：[`M3_G1_B2A请求计划与Journal独立初验报告.md`](M3_G1_B2A请求计划与Journal独立初验报告.md)  
结论：**未通过独立二次复验；P1-2 的零网络门禁已修复，但零新证据门禁仍未关闭**

本轮仍只读生产代码与测试。未读取 `_old/`、本地 Tushare 配置或 token，未访问真实网络，未修改生产
代码或 `tests/`。独立组合反例全部通过标准输入和 Python 临时目录执行，没有遗留临时测试文件。

## 1. 结论摘要

- 上次 25 个专项按原有断言重跑：**25/25 通过**。
- 新增 16 个状态/副作用组合：若只看 connector/clock/sleep，则 **16/16 通过**；加入任务要求的
  “新证据计数”后为 **7 通过、9 失败**。
- 9 个失败全部归属于同一 P1-2：既存非法 raw request layout 已能在联网前识别，但识别前已新增
  `journal/<request_id>/intent.json` 一份。
- `RawStore.inspect_request_state` 的三态闭包、direct-caller 严格性、root/descendant 检查和 post-mkdir
  二次检查本身通过。
- P1-1、P1-3、P1-4 关键反例及 legacy `RawStore.write` 回归通过。
- 定向/全量 pytest、Ruff、mypy 全绿，但不能覆盖上述副作用顺序问题。

因此当前不能写“通过独立二次复验”，也不能把 B2A、B2、G1 或 M3 标为通过。

## 2. 二次返工已正确关闭的部分

### 2.1 `inspect_request_state` 三态与 direct caller

`RawStore.inspect_request_state` 只有三个合法返回：

- `ABSENT`：request directory 不存在；
- `EMPTY`：request directory 是实际普通目录且无条目；
- `COMPLETE`：精确包含两个实际普通文件 `data.parquet/metadata.json`。

以下输入全部直接抛稳定 `ValueError`，不会伪装成三态：

- data/metadata 单边；
- request directory 是 symlink 或普通文件；
- 额外普通文件、目录、file symlink、directory symlink、FIFO；
- source/table 含路径分隔符、request ID 非 64 位小写 hex；
- root 或既存祖先是 symlink/非目录。

返回值没有第四种隐式状态，executor、`write_request` 和 `verify_request` 也复用同一接口。该部分通过。

### 2.2 raw 写入层二次检查

`write_request` 在 directory mkdir 后、首次 `_write_new_strict` 前再次要求状态为 `EMPTY`。独立探针在
mkdir 返回后将 request directory 换成 symlink，结果为稳定失败，外部目标目录保持 0 个文件；未再出现
第一次复验记录的 data/metadata 外写。

该 best-effort 检查符合首版单 executor 威胁模型；本轮不要求内核级消除检查完成后的恶意竞态。

### 2.3 上次两个失败

- 静态 request-directory symlink：connector/monotonic/sleep 从 `1/1/0` 修复为 `0/0/0`；
- 静态未知子目录：connector/monotonic/sleep 同样修复为 `0/0/0`。

因此二次返工确实关闭了“非法 descendant 先调用供应商”的直接缺陷。

## 3. 仍未关闭的 P1-2：非法 raw 预检之前发布 intent

### 3.1 现象

位置：`src/quant/data/m3_backfill.py:551`–`:557`。

无 receipt 的路径当前顺序是：

```python
_ensure_intent(intent_path, spec)
candidate = _recover_candidate(...)
```

`_recover_candidate` 内才调用 `inspect_request_state`。因此下列 9 类既存非法 raw 布局虽然都满足
connector/monotonic/sleep 为 0，却都会新增一个普通文件：

| 非法布局 | connector | monotonic | sleep | 新 raw 文件 | 新 journal 文件 |
|---|---:|---:|---:|---:|---:|
| data only | 0 | 0 | 0 | 0 | **1 intent** |
| metadata only | 0 | 0 | 0 | 0 | **1 intent** |
| request directory symlink | 0 | 0 | 0 | 0 | **1 intent** |
| request path 普通文件 | 0 | 0 | 0 | 0 | **1 intent** |
| 额外普通文件 | 0 | 0 | 0 | 0 | **1 intent** |
| 未知目录 | 0 | 0 | 0 | 0 | **1 intent** |
| file symlink | 0 | 0 | 0 | 0 | **1 intent** |
| directory symlink | 0 | 0 | 0 | 0 | **1 intent** |
| FIFO | 0 | 0 | 0 | 0 | **1 intent** |

request-directory symlink 指向的外部目录保持为空，异常 message/repr/traceback 也不含临时物理路径；失败点
只在“预检前新增 intent 证据”。

### 3.2 为什么 intent 也属于失败副作用

冻结契约要求 intent 必须在**首次合法网络调用之前**发布；这不是“无论现有证据是否合法都先写 intent”的
授权。raw orphan、symlink 或非法布局属于恢复预检失败，原 P1-2 的通过条件是 connector/clock/sleep 为 0，
且 raw/journal 不产生新文件或新证据。

此外，合法生产顺序是 intent 先于 raw。若磁盘已有 raw/candidate 却没有 intent，这本身是证据闭包异常；
自动创建 intent 会把一个不可能由合法 writer 产生的状态部分“修好”，削弱 fail-closed 审计语义。

因此不能只用“没有联网”判定 P1-2 关闭。用户本轮明确要求每种状态核对新证据计数，9 个 `intent=1`
是实质失败，而不是测试记账差异。

### 3.3 根因

二次返工正确集中化了 raw 状态检查，但只替换了 `_recover_candidate` 内部的发现逻辑，没有调整 executor
副作用顺序。`_ensure_intent` 仍早于 raw/journal 闭包的完整只读预检。

这也是多 Agent 返工应吸收的通用教训：修复“检查内容”时必须同时审查“检查发生在第一个副作用之前吗”；
门禁逻辑正确但位置过晚，仍不满足 fail-closed。

### 3.4 修订建议

对每个 request 先执行不写文件的联合状态检查，再分支：

1. raw 非法、孤儿、symlink 或未知条目：零新证据失败；
2. raw `ABSENT/EMPTY` 且没有 candidate/receipt：发布或验真 intent，然后才允许网络；
3. raw `COMPLETE`：合法 writer 理应已有 intent；缺 intent 应作为闭包异常失败，而不是自动补写；
4. candidate 存在但 raw 非 COMPLETE，或 raw COMPLETE 但 candidate/intent 冲突：零写失败；
5. 只有只读预检通过后，才进入 candidate/receipt 恢复或首次网络状态转换。

可以新增一个窄的 request preflight 结果对象，把 journal 与 raw 状态共同返回，避免 executor 继续以文件
存在判断和 raw 三态分别决策。

### 3.5 通过条件

- 上表 9 种非法布局均为 connector/monotonic/sleep `0/0/0`，且 raw/journal 新文件计数均为 0；
- ABSENT/EMPTY 合法首次请求仍各调用 connector 一次并形成 2 raw + 3 journal 文件；
- 合法 after-metadata 崩溃状态已有 intent，重跑零 connector/clock/sleep，只新增 candidate/receipt；
- COMPLETE raw 却缺 intent 的人工拼接状态明确 fail-closed，不自动生成闭包；
- 所有失败继续保持稳定脱敏错误。

## 4. 合法状态组合结果

| 初始状态 | direct state | connector | monotonic | sleep | 新证据 | 结果 |
|---|---|---:|---:|---:|---|---|
| request dir 不存在 | ABSENT | 1 | 1 | 0 | raw 2 + journal 3 | 通过 |
| 合法空实际目录 | EMPTY | 1 | 1 | 0 | raw 2 + journal 3 | 通过 |
| 合法完整 pair + 既有 intent | COMPLETE | 0 | 0 | 0 | candidate + receipt | 通过 |

另用 direct `RawStore.write_request` 生成 COMPLETE pair 验证三态 reader，返回值为 `COMPLETE`；生产恢复闭包
应使用已有 intent 的故障注入状态作为合法基准，不能把人工 raw-only 状态当成合法 writer 输出。

## 5. 专项与回归统计

### 5.1 上次 25 个专项

构造后嵌套篡改、Verified digest、root/ancestor、journal inode、14 个 direct/chained IO、legacy 幂等等价
断言均通过。上次两个 raw descendant 失败也已达到原断言中的零 API 要求。因此按上次断言口径为
**25/25 通过**。

### 5.2 本次 16 个组合

- 合法 ABSENT/EMPTY/COMPLETE：3 通过；
- 9 种非法布局：状态判断和零 API 通过，但零新证据失败；
- direct caller 非法 path/ID、祖先 symlink：2 通过；
- post-mkdir 替换二次检查：1 通过；
- legacy `RawStore.write` 幂等/FileExists 语义：1 通过。

按完整验收口径合计：**7 通过、9 失败**，9 个失败归并为一个 P1-2，不重复计数。

### 5.3 P1-1/P1-3/P1-4 防回归

- direct batch/plan 嵌套篡改与 Verified receipt/frame digest：通过；
- journal 额外目录、file/dir symlink、FIFO、白名单文件 symlink：通过；
- mkdir/open/close/link/fsync/unlink/Parquet direct/chained 异常脱敏与 cleanup 主异常保持：通过。

未发现二次返工导致这三个已关闭 P1 回归。

## 6. 工具链验证

全部命令在 WSL Miniforge `base` 执行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
98 passed in 6.47s

python -m pytest -q
399 passed, 1179 warnings in 13.26s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

1179 条 warning 仍来自既有 Pandera/Polars deprecation 路径。全量绿色不能覆盖 intent 发布顺序的未公开
副作用反例。

## 7. 最终结论

独立二次复验结论：**不通过**。二次返工已经修复 per-request raw 非法布局的零网络问题，但原 P1-2
要求的“路径/恢复预检失败不产生新证据”仍未闭合。

原实现 Agent 应只调整每 request 的只读预检与 intent 发布顺序，并补充 9 类非法 raw 布局的
`new_raw_files=0/new_journal_files=0` 回归。完成后仍需独立复验及主 Agent 最终验收；当前不代表
B2A、B2、G1 或 M3 通过。
