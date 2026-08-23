# M3 G1 B2A 请求计划与 Journal 独立复验报告

日期：2026-07-13  
返工报告：[`M3_G1_B2A请求计划与Journal返工交付报告.md`](M3_G1_B2A请求计划与Journal返工交付报告.md)  
原初验：[`M3_G1_B2A请求计划与Journal独立初验报告.md`](M3_G1_B2A请求计划与Journal独立初验报告.md)  
任务书：[`M3_G1_B2A请求计划与Journal实现初验任务单.md`](M3_G1_B2A请求计划与Journal实现初验任务单.md)  
结论：**未通过独立复验；P1-1、P1-3、P1-4 已关闭，P1-2 仍有一个确定性缺口**

本轮只读验收当前生产代码和测试。未修改生产代码或 `tests/`，未读取 `_old/`、本地 Tushare 配置或
token，未访问真实网络。新增反例通过 Python 标准库临时目录和标准输入执行，没有在项目或系统临时目录
遗留测试文件。

## 1. 复验摘要

- 原 A01–A18 等价反例：**18/18 通过**。
- 新增返工专项反例：**25 个，23 通过、2 失败**。
- 两个失败属于同一根因，归并为原 **P1-2 未完全关闭**，不重复计数。
- 定向和全量 pytest、Ruff、mypy 全部通过；工具链绿色不替代失败的独立反例。
- 当前仍不得把 B2A、B2、G1 或 M3 标为通过，需原实现 Agent 再返工并由独立 Agent 复验。

## 2. 原 4 个 P1 逐项复验

### P1-1：公开 dataclass direct-caller 信任边界——已关闭

返工后：

- `TushareRequestBatch.__post_init__` 重建每个 spec 并执行 endpoint 参数、fields、日期和代码契约；
- INDEX_WEIGHT/HISTORY batch 都拒绝空请求；
- `G1RequestPlan` 递归重建两个 batch；
- `VerifiedRawResponse` 重建 spec/receipt，重算 canonical receipt bytes hash 和 frame content digest；
- strict receipt reader 拒绝语义相同但 bytes 非 canonical 的 receipt。

复验结果：

- 原 A01–A03 全部通过；
- 构造成功后用 `object.__setattr__` 篡改嵌套 spec/request ID，再进入 plan 构造或 executor，均在 IO 前失败；
- 伪造 `receipt_sha256`、frame 内容 digest、使用错误 endpoint 计算 content digest，均被拒绝；
- receipt 仅追加换行也被稳定拒绝为 non-canonical bytes。

结论：该 P1 已关闭。

### P1-2：raw/journal 受控路径与零 API 预检——仍未关闭

root 自身/既存祖先 symlink、root 被普通文件占用、深层未创建 root 位于 symlink 祖先下等原反例均已修复，
并满足 connector/monotonic/sleep 为 0。journal request 目录创建后被替换为 symlink 的专项反例也被第二次
检查拦截。

但每个 request 的 **raw request directory** 在恢复发现阶段仍有未关闭缺口，详见第 3 节。因此该 P1
不能标为关闭。

### P1-3：固定 journal 布局白名单——已关闭

`_validate_journal_files` 现在枚举全部目录项并用 `lstat` 要求白名单内普通文件。额外目录、文件 symlink、
目录 symlink、FIFO 和把合法 `receipt.json` 换成 symlink 均零网络失败；合法 committed journal 继续零网络
复用。

结论：原 A06 及新增 inode 类型变体全部通过，该 P1 已关闭。

### P1-4：IO 异常脱敏闭包——已关闭

对 `mkdir/os.open/os.close/os.link/fsync/unlink/pl.read_parquet` 分别注入 direct 和 chained OSError，
共 14 个专项分支，全部返回稳定 `M3BackfillError`，且 `str/repr/traceback.format_exception` 不含测试 token、
Windows 私有路径或 WSL 私有路径。cleanup 有主异常时保留主异常，无主异常时返回稳定 cleanup code。

结论：14/14 通过，该 P1 已关闭。

## 3. 仍未关闭的 P1-2 Finding

### 现象

位置：`src/quant/data/m3_backfill.py:770`–`:779`。

在网络调用前预置以下任一静态 raw 布局：

1. `<raw_root>/tushare/index_weight/request=<request_id>` 本身是指向空外部目录的 symlink；
2. 上述 request 目录是实际目录，但只包含一个未知子目录。

executor 最终都会返回稳定 `RAW_WRITE_CONFLICT`，也没有向外部目录写入文件；但是在失败前 connector 已经
被调用 **1 次**。预期是发现非法 raw 布局后零 API fail-closed。

### 根因

`_recover_candidate` 使用：

```python
ordinary = sorted(path.name for path in directory.iterdir() if path.is_file())
if ordinary == []:
    return None
```

这与返工前 journal 白名单的错误模式相同：先过滤掉非普通条目，再把过滤后的空集合解释为“没有 raw，
可以联网”。目录 symlink 指向空目录、未知目录和 FIFO 都可能因此被隐藏。`RawStore.write_request` 的二次
门禁确实会拒绝它们，但发生在 connector 返回以后，不能补偿已产生的供应商调用。

### 被破坏的规则

- candidate 不存在且**没有 raw 证据**时才允许联网；非法、歧义或 symlink raw 布局必须先失败。
- 路径、孤儿和恢复预检命中时不得调用 connector、clock 或 sleep。
- “枚举固定布局”必须检查全部目录项及其 inode 类型，不能用 `is_file()` 过滤掉异常证据。

### 最小复现与证据

新增专项 S08：预置 request directory symlink。结果：`M3BackfillError("RAW_WRITE_CONFLICT")`，
`connector.calls == 1`，外部目录为空。

新增专项 S10：预置实际 request directory，并新增 `unknown/` 子目录。结果同样为 connector 1 次后失败。

这两个反例不依赖瞬时并发替换或内核级竞态，是正常文件布局下可确定重现的问题，因此属于原 P1-2
验收范围，而不是超出首版单 executor 威胁模型的要求。

### 修订建议

在 `_recover_candidate` 返回 `None` 前，先严格检查 raw request directory：

1. 对 directory 自身使用 `lstat`，symlink 或非目录立即失败；
2. 枚举**全部**条目并检查 `lstat` 类型；
3. 空的实际普通目录才可视为没有 raw；
4. 精确两个普通文件 `data.parquet/metadata.json` 才进入恢复验真；
5. 单边文件、未知文件、目录、symlink、FIFO 或设备均在联网前失败。

宜让 `RawStore` 提供一个窄的 request-state 检查接口，由 executor 和写入层复用，避免 data 层再次复制一套
与 `_controlled_request_entries` 漂移的规则。

### 通过条件

- request directory symlink、未知目录、FIFO、单边文件、额外文件均在 connector/clock/sleep 为 0 时失败；
- 空的实际普通目录仍允许首次联网；
- 完整一致 raw pair 继续零网络恢复；
- 错误的 message/repr/traceback 保持脱敏。

## 4. post-mkdir 替换与首版威胁模型

返工报告明确说明不能消除所有外部恶意并发替换，这与首版单 executor 威胁模型一致，本轮不要求
`openat2`、目录 fd 锁定或内核级无竞态保证。

补充探针显示：若外部动作恰在 `RawStore.write_request` 的 `directory.mkdir()` 返回后把目录换成 symlink，
当前代码会通过 symlink 写出 `data.parquet/metadata.json`，随后在 `verify_request` 二次验真时失败。该探针
需要注入并发式替换，因此不单独升级为第二个 finding；但它说明返工报告所称“创建后第三层检查”并未位于
mkdir 与首次文件创建之间。

建议本次修复同时在 raw directory mkdir 后、首次 `_write_new_strict` 前再次执行 descendant symlink/
containment 检查，以缩小窗口。即使加入该检查，也应继续诚实说明不能抵御检查完成后的内核级恶意替换。

## 5. 新增专项反例结果

| 组 | 数量 | 结果 |
|---|---:|---|
| 嵌套 batch/plan 构造后篡改并进入信任边界 | 2 | 2 通过 |
| receipt canonical bytes、frame/content/endpoint digest 伪造 | 2 | 2 通过 |
| 深层祖先 symlink、root 普通文件、journal request dir 二次替换 | 3 | 3 通过 |
| 静态 raw request dir symlink、未知目录 | 2 | **2 失败** |
| journal directory、file/dir symlink、FIFO、白名单文件 symlink 变体 | 1 组 | 通过 |
| 7 类 IO × direct/chained OSError | 14 | 14 通过 |
| legacy `RawStore.write` 幂等及缺 metadata 后 FileExists 恢复语义 | 1 | 通过 |

按独立可执行断言计数为 **25 个，23 通过、2 失败**。另做的外部 post-mkdir 替换探针作为威胁模型记录，
不计入这 25 个确定性验收断言。

## 6. 原 A01–A18 等价回归

| 原用例 | 复验结论 |
|---|---|
| A01–A03 direct dataclass/verified 身份 | 通过 |
| A04 endpoint policy | 通过 |
| A05 committed closure 篡改 | 通过 |
| A06 journal 非普通条目 | 通过 |
| A07–A09 root/祖先 symlink | 通过 |
| A10–A12 journal、cleanup、Parquet IO 脱敏 | 通过 |
| A13 digest 行序稳定与重复敏感 | 通过 |
| A14 candidate 恢复零 connector/clock/sleep | 通过 |
| A15–A16 重试 deadline 与 classifier 脱敏 | 通过 |
| A17–A18 session/成分顺序稳定 | 通过 |

合计：**18/18 通过**。这证明返工修复了原始最小复现，但新增 raw descendant 反例证明 P1-2 的通用不变量
尚未完全闭合。

## 7. 工具链验证

全部命令在 WSL Miniforge `base` 执行：

```text
python -m pytest -q tests/unit/test_m3_backfill_requests.py tests/unit/test_storage.py
90 passed in 6.54s

python -m pytest -q
391 passed, 1179 warnings in 12.74s

python -m ruff check src tests
All checks passed!

python -m mypy src
Success: no issues found in 72 source files
```

1179 条 warning 仍来自既有 Pandera/Polars deprecation 路径。工具链全绿不能覆盖独立专项中两个失败。

## 8. 结论与下一步

本轮结论是：**未通过独立复验**。原实现 Agent 应只返工 P1-2 的 per-request raw 发现门禁，并补充静态
request-directory symlink、未知目录/FIFO、空普通目录和完整 pair 的零 API 回归；同时按第 4 节增加
mkdir 后的 best-effort 二次检查并准确记录威胁模型。

返工后仍需独立复验和主 Agent 最终验收；当前不得更新 B2、G1、M3 或路线图 Gate。
