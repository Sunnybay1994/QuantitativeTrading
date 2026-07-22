# M3 G1 B2A 请求计划与 Journal 独立初验报告

日期：2026-07-13  
任务书：[`M3_G1_B2A请求计划与Journal实现初验任务单.md`](M3_G1_B2A请求计划与Journal实现初验任务单.md)  
实现报告：[`M3_G1_B2A请求计划与Journal交付报告.md`](M3_G1_B2A请求计划与Journal交付报告.md)  
契约 SSOT：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) 4.10  
结论：**未通过独立初验；发现 4 个 P1、0 个 P0、0 个 P2，退回原实现 Agent 返工**

本结论只针对 B2A 子包。即使后续复验通过，也不代表 B2、G1 或 M3 通过。

## 1. 验收边界与方法

本轮由未参与实现的 Agent 只读核对任务书、SSOT、设计审查、生产代码、生产测试和实现报告。未读取
`_old/`、`configs/tushare.local.toml` 或任何 token，未访问真实网络，未修改生产代码或 `tests/`。
18 个新增对抗用例只在临时文件中运行，验收结束后已删除；检查结果为临时文件残留 0。

重点不只检查“现有测试绿色”，还重新验证了三类信任边界：调用方直接构造的领域对象、受控 raw/journal
路径，以及异常 message/repr/traceback 的完整脱敏。

## 2. Findings

### P1-1：公开 dataclass 没有闭合 direct-caller 信任边界

- **位置**：`src/quant/data/m3_backfill.py:128`、`:161`、`:287`。
- **现象**：
  1. `TushareRequestSpec.create` 可生成带 `marker`、缺日期和证券代码的非规范 `daily` spec；直接传给
     `TushareRequestBatch` 会被接受，只有执行器稍后才拒绝。
  2. 空 `HISTORY` batch 和由它组成的 `G1RequestPlan` 可直接构造成功。
  3. `VerifiedRawResponse` 接受 `receipt_sha256="0"*64` 及与 receipt 内容不同、但行列数相同的 frame。
- **根因**：batch 的 `__post_init__` 只检查类型、排序、phase 和自报 batch hash；plan 只信任嵌套 batch
  的 phase/hash；verified response 只检查 hash 形状及行列数。生产契约被延迟到 executor/verifier，公开
  对象本身却以 `Batch/Plan/Verified` 命名并可流入后续层。
- **被破坏的规则**：B2A 任务书第 2 节要求公开 dataclass 在 `__post_init__` 重算并验证嵌套身份、排序、
  唯一性、类型和枚举，且 direct caller 不能构造非规范 batch/plan。
- **最小复现**：独立用例 A01、A02、A03；三者都预期构造失败，实际均未抛异常。
- **修订建议**：
  1. batch 构造时逐个重建 spec 并执行 endpoint 参数/fields 契约；禁止空 HISTORY batch，或把仅供内部
     组装的中间状态改成不同类型，不能让空 batch 冒充最终阶段。
  2. plan 构造时重验两侧 batch，而不是只 hash 两个自报 batch hash。
  3. `VerifiedRawResponse` 重算 frame 内容 digest 并与 receipt 比较；receipt bytes hash 必须由严格 reader
     的实际 bytes 产生。若无法在 dataclass 内验证，就应收窄构造入口，并让所有消费边界重新调用生产 verifier。
- **新增测试与通过条件**：上述三种 direct construction 全部在任何文件 IO 前失败；正常 planner 和
  `verify_tushare_receipt` 返回值保持通过。

### P1-2：受控 raw/journal root 的 symlink 检查不完整且 raw 检查晚于网络调用

- **位置**：`src/quant/data/m3_backfill.py:444`、`:488`、`:494`、
  `src/quant/data/storage.py:508`。
- **现象**：
  1. `raw_root` 本身是 symlink 时，executor 先调用一次 connector，随后才在 `write_request` 失败；
     违反路径异常预检零 API 的要求。
  2. `raw_root` 或 `journal_root` 的父级是 symlink、而 root 本身不是 symlink 时，任务完整成功，并把证据
     写入 symlink 指向的物理目录。
- **根因**：executor 只检查 `journal_root.is_symlink()`，没有在获取 writer lock/联网前共同验证两个 root；
  `_reject_symlinks` 只从 root 自身向下检查，不检查 root 的既存父目录链；raw guard 又只在网络返回后的
  `RawStore.write_request` 内触发。
- **被破坏的规则**：受控相对路径必须仍位于受控 root；路径逃逸和 symlink 必须 fail-closed；预检异常
  不得产生 API 调用或新证据。
- **最小复现**：独立用例 A07 显示 raw-root symlink 下 `connector.calls == ["index_weight"]`；A08/A09
  显示父级 symlink 未被拒绝。
- **修订建议**：在创建 journal 目录、writer lock、intent 或调用 connector 前，对 raw/journal 两个 root
  做一次统一的、基于 `lstat` 的既存祖先链检查和 resolved containment 检查；`RawStore` 自身仍保留同样
  的二次防线。不要通过先联网、写入时再报错来补救。
- **新增测试与通过条件**：root 本身 symlink、任一既存父级 symlink、文件替换三类反例均稳定返回脱敏
  错误，connector/clock/sleep 调用数为 0，raw/journal 不产生新文件。

### P1-3：固定 journal 布局会忽略未知 symlink 目录

- **位置**：`src/quant/data/m3_backfill.py:929`。
- **现象**：已提交 request 目录中增加指向外部目录的 `extra-link` 后，receipt 仍被成功复用。
- **根因**：`_validate_journal_files` 只收集 `path.is_file()` 的名字；未知目录和指向目录的 symlink 被过滤掉，
  因而没有参与白名单比较。
- **被破坏的规则**：首版 journal 的物理布局固定为 `intent.json/candidate.json/receipt.json`，额外
  candidate-like、未知条目或 symlink 均应 fail-closed。
- **最小复现**：独立用例 A06；预期 `JOURNAL_*`/`SYMLINK` 错误，实际无异常且零网络复用了 receipt。
- **修订建议**：用 `list(directory.iterdir())` 检查**全部目录项**；任何 symlink、目录、设备文件或白名单外
  名称均拒绝。对白名单内三文件也继续执行逐路径 symlink 检查。
- **新增测试与通过条件**：额外普通文件、目录、文件 symlink、目录 symlink、FIFO（平台支持时）均拒绝；
  合法三文件闭包仍可零网络恢复。

### P1-4：异常脱敏只覆盖了部分分支，Journal/Parquet IO 仍可泄露 secret 和物理路径

- **位置**：`src/quant/data/m3_backfill.py:554`、`:743`、`:828`。
- **现象**：
  1. `os.link` 在 intent/candidate/receipt 原子发布时报 `OSError`，原异常及其中的 token/path 直接出现在 traceback。
  2. writer lock 的 `unlink` 抛 `OSError` 时，会掩盖原本已脱敏的 provider permanent failure，并泄露清理路径。
  3. candidate 验真中第二次 `pl.read_parquet` 抛 chained `OSError` 时，cause/context 中的 token 和物理路径
     原样可见。
- **根因**：实现只在 connector、部分 `RawStore` 调用和 `_read_bytes` 周围转换为稳定错误；原子发布、
  清理和 verifier 的二次 Parquet 读取没有统一的最外层 IO 安全边界。实现报告第 5、6 节所称“OSError
  cause suppression”只被一个 writer-lock 已存在分支覆盖，不能代表全路径成立。
- **被破坏的规则**：message、repr、traceback 和日志均不得包含 token、client repr、供应商原值或本机路径；
  对外异常必须使用稳定分类码，清理异常不得掩盖主异常。
- **最小复现**：独立用例 A10、A11、A12；A12 明确使用 `raise OSError("wrapper") from cause`，traceback
  显示 cause 中的敏感值。
- **修订建议**：为 journal publish/lock 和 receipt/candidate verifier 建立窄的稳定异常边界；捕获预期
  `OSError`/Parquet 读取错误并 `raise M3BackfillError(<stable-code>) from None`。清理失败若已有主异常，
  不得替换主异常；若单独失败，也只能抛稳定脱敏码。不要把 `BaseException` 用作普通 IO 捕获范围。
- **新增测试与通过条件**：分别注入 `mkdir/open/link/fsync/unlink/read_parquet` 的直接和 chained OSError；
  对 `str/repr/traceback` 做凭据与 Windows/WSL 私有路径扫描，且原业务错误不被 cleanup 覆盖。

## 3. 冻结契约逐项映射

| 契约面 | 证据 | 结论 |
|---|---|---|
| 七 endpoint fields 与 policy 精确值 | 生产测试 7 端点 fields、empty、limit；独立 A04 | 通过 |
| request ID、参数排序、重复 ID | `TushareRequestSpec` 重算；生产伪造 ID 测试 | 单 spec 通过；嵌套 batch/plan 未通过 |
| 完整自然月、闰年、60/10 SH sessions | 生产跨年/闰年测试；独立 A17/A18 | 通过 |
| 成分乱序/重复与 A 股代码 | 生产计数测试；独立 A18 | 通过 |
| receipt/intent/candidate/raw 闭包 | 生产故障注入与缺文件测试；独立 A05 | 内容闭包通过；路径白名单未通过 |
| raw 重复行与逻辑 digest | 生产 raw 两重复行测试；独立 A13 | 通过；重复行影响 digest，输入行序不影响 digest |
| stable digest 与物理路径分离 | 两个物理 root 的生产测试 | 通过 |
| cache/candidate 恢复零 connector/clock/sleep | 生产 cache 测试；独立 A14 | 通过 |
| 三类 transient、限频和指数退避 | 生产三分类测试；独立 A15/A16 | 通过；三次时间为 2s、4s，classifier 自身失败不重试 |
| 路径逃逸、symlink、并发不覆盖 | 生产常规路径/lock 测试；独立 A06–A12 | **未通过** |
| 旧 `RawStore.write` 语义 | `tests/unit/test_storage.py` 回归 | 通过 |
| `quant.data` 不反向 import `quant.research` | 源码搜索 0 处 | 通过 |

## 4. 新增对抗用例结果

| ID | 独立反例 | 结果 |
|---|---|---|
| A01 | factory 生成非规范 endpoint 参数后直接构造 batch | 失败：被接受 |
| A02 | 空 HISTORY batch 直接构造最终 plan | 失败：被接受 |
| A03 | 改 frame 内容并伪造 receipt hash 构造 `VerifiedRawResponse` | 失败：被接受 |
| A04 | 七 endpoint policy 精确值和只读 mapping | 通过 |
| A05 | 有效 receipt 下篡改 candidate 的完整闭包 | 通过：零网络拒绝 |
| A06 | request journal 增加未知 symlink 目录 | 失败：被忽略 |
| A07 | raw root 本身为 symlink | 失败：先调用一次 API 才拒绝 |
| A08 | raw root 的父级为 symlink | 失败：完整成功并写入外部目标 |
| A09 | journal root 的父级为 symlink | 失败：完整成功并写入外部目标 |
| A10 | `os.link` 原子发布抛含敏感值 OSError | 失败：原异常泄露 |
| A11 | writer lock 清理抛含敏感值 OSError | 失败：掩盖主异常并泄露 |
| A12 | Parquet 二次读取抛 chained OSError | 失败：cause/path 泄露 |
| A13 | 内容 digest 行序稳定且重复行敏感 | 通过 |
| A14 | candidate 恢复时 connector/clock/sleep 全禁用 | 通过 |
| A15 | 连续两次 transient 的 rate/backoff 较晚 deadline | 通过：sleep 为 2s、4s |
| A16 | classifier 自身抛 chained 敏感异常 | 通过：永久失败且脱敏 |
| A17 | 真实 weekday session 的精确 60/10 与重复日历 | 通过 |
| A18 | 成分乱序/重复不改变完整 plan hash | 通过 |

合计：**18 个，8 通过、10 失败**。失败按共同根因归并为上述 4 个 P1，避免把同一缺陷的三个表象
重复计数为三个 finding。

## 5. 实现报告自述的复核

### 5.1 首轮 26 通过、13 失败

当前生产测试使用七 endpoint 的真实规范参数，executor 仍通过 `_validate_request_contract` 拒绝 `marker`
式参数；限频/退避测试断言 2 秒较晚 deadline；IO 前失败检查业务 raw/journal 子目录；非开市日反例只改变
目标条件。未发现为了消除这 13 个 fixture 失败而放宽 executor 生产契约的证据。

但生产测试把“非规范 spec”只验证到 executor，遗漏了任务书要求的 direct batch/plan 构造边界，因此
独立 A01/A02 仍发现 P1-1。这是测试层次不完整，不是前述 fixture 修正本身有误。

### 5.2 实现自审两项

- receipt 全闭包：代码和生产缺 intent/candidate 测试真实存在；独立 A05 进一步证明篡改 candidate 会零网络失败。
- OSError cause suppression：connector 和 writer-lock 已存在分支通过，但实现报告将局部结果外推到全部 IO
  路径。A10–A12 证明原子发布、cleanup 和 Parquet 二次读取仍有泄露，因此该项自审**未形成全路径闭包**。

## 6. 验证命令

全部命令在 WSL Miniforge `base` 执行；未调用 Windows Python。

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
68 passed in 4.89s

python -m pytest -q
369 passed, 1179 warnings in 11.26s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

额外临时对抗测试结果：`10 failed, 8 passed in 2.74s`。1179 条 warning 仍来自既有 Pandera/Polars
deprecation 路径；本报告不把 warning 记为失败，也不把全量绿色当作独立反例通过。

## 7. 返工与复验门槛

原实现 Agent 应按 P1-1 至 P1-4 逐项补充生产回归，交付返工报告需写明“现象—根因—应遵循规则—
最小复现—新增测试—通过条件”。复验至少重跑本报告 A01–A18 的等价反例、四组标准命令，并扫描
`str/repr/traceback` 中的凭据与本机路径。

在独立复验和主 Agent 最终验收之前，B2A 状态保持**未通过**；不得更新 B2、G1、M3 或路线图 Gate。
