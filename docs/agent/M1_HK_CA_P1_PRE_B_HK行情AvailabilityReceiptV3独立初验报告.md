# M1-HK-CA-P1-PRE-B：HK 行情 Availability Receipt v3 独立初验报告

日期：2026-08-09  
角色：未参与实现的独立初验 Agent  
结论：**FAIL；不得进入主 Agent 终验或正式 v3 migration**

## 1. 初验边界

本轮完整阅读了项目 `AGENTS.md`、冻结任务单、实现交付报告以及直接相关的 P0/P1-PRE 契约，并只读核对
以下实现与测试：

- `src/quant/domain/schemas.py`
- `src/quant/domain/__init__.py`
- `src/quant/data/hkex_daily_quotations.py`
- `src/quant/data/hk_history_backfill.py`
- `tests/unit/test_schemas.py`
- `tests/unit/test_hkex_daily_quotations.py`
- `tests/unit/test_hk_history_backfill.py`

没有联网，没有读取或写入正式 02983/01065 data、journal 或候选目录，没有修改生产代码和实现者测试；
唯一写入是本报告。所有独立探针只使用系统临时目录中的 synthetic fixture。

## 2. 已通过的契约项

静态映射与既有定向测试确认以下部分已经实现：

1. legacy raw-only 路径保持 v1/v2，`load_verified_hk_bar_bundle` 对其返回稳定
   `HK_HISTORY_AVAILABILITY_UNSUPPORTED`，不会签发 formal bar capability；
2. v3 从 seed/request metadata 的 `fetched_at` 与 HKEX retained metadata 的
   `source_observed_at` 投影逐 key availability；
3. effective key 与 seed/request/HKEX source closure 做 exact set、无缺失、无重复检查；
4. v3 固定发布 `hkex-retained.raw`、`hkex-retained.metadata.json`、`availability.json`、
   `finalize.json`，并绑定 clean、availability、request receipts 与 HKEX identities；
5. clean 与 availability fresh 重建覆盖 HK symbol、`adj_factor == 1.0`、as-of、row count、内容摘要；
6. capability 为 exact final type、不可 pickle，公开属性返回 frame clone，public verifier 会 fresh 重建；
7. 实现者测试已覆盖 legacy、future availability、request metadata drift、跨来源重复、whole-rehash 后旧
   capability、root 跨路径复制/调用间替换、写失败 rollback 与 hostile message 的表面错误码。

上述通过项仍不足以关闭本轮，因为第 3 节的两个反例直接违反冻结任务单的必过条件。

## 3. 阻塞问题

### 3.1 [P1] 验证窗口内 root ABA 可被接受

**现象**

独立探针在 `_load_v3_state` 首轮取得四个 root identity 后，把 `journal_root` 原目录移走，将其完整复制品放回
同一路径；在末轮 identity 复核前删除复制品并恢复原目录。loader 最终成功签发 capability：

```text
ABA_ACCEPTED CALLS 8
```

该反例不同于实现者已有的“拿旧 capability 到复制 root 验证”与“在两次 public 调用之间替换 clean root”；
它发生在**同一次 fresh load 的验证窗口内部**。

**根因**

`src/quant/data/hk_history_backfill.py:1567` 的 `_root_identity` 只进行瞬时 path-based `lstat/resolve`。
`_load_v3_state` 在 `src/quant/data/hk_history_backfill.py:1689` 左右记录首轮 identity，随后全部文件仍通过普通
`Path.read_bytes` / `pl.read_parquet(path)` 读取，最后在约 `1808` 行再次按路径取 identity。代码没有在整个
窗口持有并使用绑定原目录对象的 handle/dir-fd，因此“原目录 → 同内容复制目录 → 原目录”的 ABA 使首尾
identity 相同，而中间读取实际来自另一个物理 root。

**应遵循规则**

冻结任务单 §6.6、§9.8 明确要求 capability 绑定 resolved/physical roots，并拒绝 copied/replaced root 与验证
窗口 TOCTOU；用户本轮还特别要求尝试跨 root 复制/ABA。仅比较首尾路径身份不满足该合同。

**最小复现**

1. 用 `_published_v3` synthetic fixture 生成可用 v3；
2. 包装 `_root_identity`，在首轮第 4 次调用后 park 原 journal 并 `copytree` 到原路径；
3. 在末轮第 1 次调用前删除 copy 并恢复原 journal；
4. 调用 `load_verified_hk_bar_bundle`；当前结果为成功，而不是稳定拒绝。

**新增测试要求**

- 同一次 `load_verified_hk_bar_bundle` 内对 journal、seed、raw-store、clean 四类 root 分别做 copy/replace/ABA；
- 复制 root 不仅要覆盖相同 bytes，还要覆盖内部自洽重签的另一 retained metadata/receipt/availability/finalize；
- Windows 与 POSIX 分别验证，不以一次调用之间的 replacement 测试代替窗口内 TOCTOU。

**通过条件**

读取必须锚定验证开始时的物理目录对象，并在完整验证期间保持锚定：Windows 使用不共享 delete/rename 的
目录 handle；POSIX 使用 `O_DIRECTORY|O_NOFOLLOW` dir-fd 并通过 anchored/open-at 读取后代。实现可以采用等价
机制，但不能继续依赖“开始/结束各 path-stat 一次”。上述窗口内 ABA 必须 fail closed，或所有读取被证明始终
来自起始锚定对象且 namespace replacement 不可能改变被验内容。

### 3.2 [P1] hostile reader 的原始异常仍可沿 `__context__` 链恢复

**现象**

独立探针让 `pl.read_parquet` 抛出 `RuntimeError("TOKEN_HOSTILE_PATH_MARKER")`，public loader 表面错误码和
格式化 traceback 虽然已脱敏，但异常对象链为：

```text
0 HKHistoryBackfillError HK_BAR_VERIFY_FAILED
1 HKHistoryBackfillError HK_HISTORY_REFERENCE_INVALID
2 RuntimeError TOKEN_HOSTILE_PATH_MARKER
```

顶层 `__cause__ is None`，但 `__context__` 非空；沿两层 `__context__` 即可恢复 marker。

**根因**

`src/quant/data/hk_history_backfill.py:1166`、`1815`、`1878` 等多层 `except Exception: raise ... from None`
只抑制 traceback 展示，不会清空 Python 异常对象的 `__context__`。每层重新包装保留了上一层 context，最终
仍把 hostile reader 的原异常对象挂在链上。

**应遵循规则**

冻结任务单 §7、§9.11 明确要求 hostile reader/parser/schema 异常固定脱敏，`cause/context` 均为 `None`，且
对象链、traceback 均不得泄漏路径、raw、TOKEN、SQL 或 marker。

**最小复现**

1. 生成 synthetic v3；
2. 将 `hk_history_backfill.pl.read_parquet` 临时替换为抛出带 marker 的 `RuntimeError`；
3. 调用 `load_verified_hk_bar_bundle`；
4. 遍历捕获异常的 `__context__`，当前第二层可见原 marker。

**新增测试要求**

- hostile reader、JSON parser、schema validator、root/path reader 各至少一例；
- 递归遍历完整 `__cause__` / `__context__` 图，而不只检查顶层 `__cause__` 与 `str(error)`；
- 检查格式化 traceback、`repr` 及链中所有异常均不含 marker/path/TOKEN/SQL/raw。

**通过条件**

public 边界抛出的稳定异常必须在离开 hostile exception handler 后创建/抛出，使最终异常对象的
`__cause__ is None` 且 `__context__ is None`；完整对象图和格式化 traceback 均不含原异常或 marker。

## 4. 验证结果

### Windows 原生 Miniforge

```text
PYTHONPATH=src D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_schemas.py tests/unit/test_hkex_daily_quotations.py \
  tests/unit/test_hk_history_backfill.py -q
109 passed, 1 skipped

D:\Miniforge3\python.exe -m ruff check <7 个定向文件>
All checks passed!

D:\Miniforge3\python.exe -m mypy <4 个 source 文件>
Success: no issues found in 4 source files
```

skip 是既有 official retained raw 条件，不影响 synthetic v3 合同矩阵。

### WSL Miniforge base

```text
PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_schemas.py tests/unit/test_hkex_daily_quotations.py \
  tests/unit/test_hk_history_backfill.py -q
110 passed

ruff: All checks passed!
mypy: Success: no issues found in 4 source files
```

工作树实际位于 `/mnt/f` DrvFS；该结果只属于双平台开发合同反馈，不是 ext4/Linux Gate。

### 其他检查

- 相关生产/测试 diff 的 `git diff --check`：通过（仅出现既有 LF/CRLF 提示）；
- 两个独立对抗探针均只使用系统临时目录，没有触碰正式数据与 journal；
- 未 add、未 commit。

## 5. 裁定与返工边界

本实现的大部分 availability/source/finalize/capability 语义已经成立，但 root ABA 与异常对象链泄漏均是任务单
明文冻结的高风险反例，因此独立初验为 **FAIL**。建议只在以下最小范围返工：

1. 为四类 root 增加贯穿一次 fresh load/verify 的物理锚定读取机制，补窗口内 ABA 测试；
2. 统一 public 边界的无 context 稳定错误构造，补完整 exception graph 脱敏测试；
3. 保持 v3 schema、四文件外部格式、source projection、legacy v1/v2 和正式数据完全不变。

返工后必须由未参与返工的全新 Agent 再次独立复验。即使复验通过，本包仍只解锁开发态 P1 total-return 输入
bar capability；正式 migration、真实 HK 公司行动、01065/HK60、ext4 与 M1 Gate 仍全部未通过。
